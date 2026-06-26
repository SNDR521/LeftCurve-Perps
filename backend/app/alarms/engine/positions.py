"""Position snapshot + PLAN alarm evaluation.

A scheduler job (Task 4) calls refresh() every ~15s: it reuses the authenticated
cockpit per account (whose user has active POSITION/PLAN alarms) to build a cache
of position context (keyed by (user_id, symbol)) that the real-time WS evaluator
reads, plus a per-user plan context that PLAN alarms evaluate against. PLAN alarms
are NOT price-driven, so they are evaluated here on the timer. Failure-isolated."""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import or_

from app.alarms.models import Alarm
from app.alarms import delivery

log = logging.getLogger(__name__)

_POSITION_CTX: dict = {}   # {(user_id, symbol): {direction, entry, qty, stop, liq, risk_usd}}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_position_ctx() -> dict:
    return dict(_POSITION_CTX)


def _accounts_needing_snapshot(db):
    from app.perps.models import ExchangeAccount
    from app.perps.services.venue_sync import SUPPORTED_VENUES
    user_ids = {uid for (uid,) in db.query(Alarm.user_id)
                .filter(Alarm.status == "ACTIVE", Alarm.enabled.is_(True),
                        Alarm.target_type.in_(["POSITION", "PLAN"])).distinct().all()}
    if not user_ids:
        return []
    return (db.query(ExchangeAccount)
            .filter(ExchangeAccount.venue.in_(SUPPORTED_VENUES),
                    ExchangeAccount.is_active.is_(True),
                    ExchangeAccount.user_id.in_(user_ids),
                    ExchangeAccount.encrypted_credentials.isnot(None)).all())


def refresh(db) -> list:
    """Rebuild the position + plan caches from each account's cockpit, then
    evaluate PLAN alarms. Returns the fired PLAN Alerts. Failure-isolated per account."""
    from app.perps.services.venue_sync import client_for
    from app.perps.services.cockpit import build_cockpit
    pos_ctx: dict = {}
    plan_ctx: dict = {}
    for acc in _accounts_needing_snapshot(db):
        client = None
        try:
            client = client_for(acc)
            ck = build_cockpit(db, acc, client)
            for p in ck.get("positions", []):
                pos_ctx[(acc.user_id, p["symbol"])] = {
                    "direction": p["direction"], "entry": p["avg_entry"], "qty": p["qty"],
                    "stop": p.get("stop_price"), "liq": p.get("liq_price"),
                    "risk_usd": p.get("risk_usd"),
                }
            if ck.get("plan"):
                plan_ctx[acc.user_id] = ck["plan"]
        except Exception:  # noqa: BLE001
            log.exception("position snapshot failed for account %s", acc.id)
        finally:
            if client is not None:
                try:
                    client._client.close()
                except Exception:  # noqa: BLE001
                    pass
    global _POSITION_CTX
    _POSITION_CTX = pos_ctx
    return evaluate_plan_alarms(db, plan_ctx)


def evaluate_plan_alarms(db, plan_by_user: dict) -> list:
    """Fire PLAN_LOSS_LIMIT / PLAN_MAX_TRADES once per plan-day when breached.
    Dedupe via params['last_fired_date'] == the active card date. Returns fired Alerts."""
    now = _now()
    alarms = (db.query(Alarm)
              .filter(Alarm.status == "ACTIVE", Alarm.enabled.is_(True),
                      Alarm.target_type == "PLAN",
                      or_(Alarm.snoozed_until.is_(None), Alarm.snoozed_until <= now))
              .all())
    fired = []
    for alarm in alarms:
        plan = plan_by_user.get(alarm.user_id)
        if not plan:
            continue
        breached = (plan.get("loss_breached") if alarm.condition == "PLAN_LOSS_LIMIT"
                    else plan.get("trades_over") if alarm.condition == "PLAN_MAX_TRADES"
                    else False)
        if not breached:
            continue
        date_key = plan.get("date") or "__nodate__"
        if (alarm.params or {}).get("last_fired_date") == date_key:
            continue
        alert = delivery.fire(db, alarm, plan.get("realized") or 0.0, source="plan")
        params = dict(alarm.params or {}); params["last_fired_date"] = date_key
        alarm.params = params
        if alert is not None:
            fired.append(alert)
    db.commit()
    return fired


_scheduler = BackgroundScheduler(daemon=True)
SNAPSHOT_SECONDS = 15


def _job():
    # runs in the scheduler thread → blocking HTTP (Telegram) is fine here
    from app.database import SessionLocal
    from app.alarms.telegram import notify
    db = SessionLocal()
    try:
        fired = refresh(db)
    except Exception:  # noqa: BLE001
        log.exception("alarm position snapshot job failed")
        fired = []
    try:
        notify.send_all(notify.collect_targets(db, fired))
    except Exception:  # noqa: BLE001
        log.exception("alarm PLAN telegram dispatch failed")
    finally:
        db.close()


def start_scheduler() -> None:
    _scheduler.add_job(_job, "interval", seconds=SNAPSHOT_SECONDS,
                       id="alarm_positions", replace_existing=True)
    if not _scheduler.running:
        _scheduler.start()
    log.info("alarm position scheduler started (every %ss)", SNAPSHOT_SECONDS)


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
