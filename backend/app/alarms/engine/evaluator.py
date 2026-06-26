"""DB batch evaluation: given a snapshot of {symbol: price}, evaluate every
active CRYPTO alarm on those symbols, fire as needed, advance state. Pure of
any network IO so it is fully unit-testable; the realtime WS loop just feeds
it prices. Commits once."""
from datetime import datetime, timezone
from sqlalchemy import or_
from app.alarms.models import Alarm
from app.alarms.conditions import should_fire
from app.alarms import delivery


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def evaluate_ticks(db, prices: dict, position_ctx: dict | None = None) -> list:
    if not prices:
        return []
    symbols = [s for s in prices]
    now = _now()
    alarms = (db.query(Alarm)
              .filter(Alarm.status == "ACTIVE", Alarm.enabled.is_(True),
                      Alarm.market == "CRYPTO", Alarm.symbol.in_(symbols),
                      or_(Alarm.snoozed_until.is_(None), Alarm.snoozed_until <= now))
              .all())
    fired = []
    pos = position_ctx or {}
    for alarm in alarms:
        if alarm.expires_at is not None and alarm.expires_at <= now:
            alarm.status = "EXPIRED"
            alarm.enabled = False
            continue
        price = prices.get(alarm.symbol)
        if price is None:
            continue
        ctx = pos.get((alarm.user_id, alarm.symbol)) if alarm.target_type == "POSITION" else None
        prev = alarm.last_price
        will_fire = should_fire(alarm, prev, price, ctx)
        alarm.last_price = price
        if not will_fire:
            continue
        if alarm.trigger_mode == "EVERY" and alarm.cooldown_seconds and alarm.last_fired_at:
            if (now - alarm.last_fired_at).total_seconds() < alarm.cooldown_seconds:
                continue
        alert = delivery.fire(db, alarm, price, source="live")
        if alert is not None:
            fired.append(alert)
    db.commit()
    return fired
