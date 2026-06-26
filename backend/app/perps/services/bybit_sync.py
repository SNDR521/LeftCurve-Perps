"""Incremental, idempotent Bybit account sync: executions + funding -> fills -> positions."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.security import decrypt_credentials
from app.perps.connectors.bybit import BybitClient
from app.perps.models import (
    ExchangeAccount, Fill, AssetClass, Side, Position, PositionStatus, Direction,
    OpenedAtSource,
)
from app.perps.services.recompute import recompute_positions

log = logging.getLogger(__name__)

SEVEN_DAYS_MS = 7 * 24 * 3600 * 1000
# Bybit's /v5/execution/list rejects startTime older than ~2 years (retCode 10001).
# "now" advances between computing the start and the request firing, so stay a few
# days inside the limit (we still capture essentially all retained history).
BACKFILL_MS = (2 * 365 - 5) * 24 * 3600 * 1000  # ~2 years (5-day safety margin) on first sync

# In-process guard so manual + scheduled syncs don't overlap per account.
_syncing: set[int] = set()


def is_syncing(account_id: int) -> bool:
    return account_id in _syncing


def _client_for(account: ExchangeAccount) -> BybitClient:
    from app.config import get_settings
    creds = decrypt_credentials(account.encrypted_credentials)
    return BybitClient(creds["api_key"], creds["api_secret"],
                       min_interval_s=get_settings().bybit_min_interval_s)


def _windows(start_ms: int, end_ms: int):
    ws = start_ms
    while ws < end_ms:
        we = min(ws + SEVEN_DAYS_MS, end_ms)
        yield ws, we
        ws = we


def _exec_to_fill(account, ex) -> dict:
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, venue=account.venue,
        external_fill_id=str(ex["execId"]), order_id=ex.get("orderId"),
        symbol=ex["symbol"], asset_class=AssetClass.PERP,
        side=Side.BUY if str(ex["side"]).upper().startswith("B") else Side.SELL,
        price=float(ex["execPrice"]), quantity=float(ex["execQty"]),
        fee=float(ex.get("execFee") or 0.0), fee_currency=ex.get("feeCurrency"),
        executed_at=datetime.fromtimestamp(int(ex["execTime"]) / 1000, tz=timezone.utc),
        raw=ex,
    )


def _funding_to_fill(account, fn) -> dict:
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, venue=account.venue,
        external_fill_id="funding:" + str(fn["id"]), order_id=None,
        symbol=fn["symbol"], asset_class=AssetClass.PERP, side=Side.BUY,
        price=0.0, quantity=0.0, fee=0.0,
        funding_amount=float(fn.get("change") or 0.0),
        executed_at=datetime.fromtimestamp(int(fn["transactionTime"]) / 1000, tz=timezone.utc),
        raw=fn,
    )


def _closed_pnl_to_position(account, r) -> dict:
    # `side` is the CLOSING order side: Sell closes a long, Buy closes a short.
    side = str(r.get("side", "")).upper()
    direction = Direction.LONG if side.startswith("S") else Direction.SHORT
    closed_at = datetime.fromtimestamp(int(r["updatedTime"]) / 1000, tz=timezone.utc)
    opened_at = datetime.fromtimestamp(int(r.get("createdTime") or r["updatedTime"]) / 1000, tz=timezone.utc)
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, symbol=r["symbol"],
        asset_class=AssetClass.PERP, direction=direction, status=PositionStatus.CLOSED,
        opened_at=opened_at, closed_at=closed_at,
        avg_entry=float(r.get("avgEntryPrice") or 0.0), avg_exit=float(r.get("avgExitPrice") or 0.0),
        quantity=float(r.get("closedSize") or 0.0), realized_pnl=float(r.get("closedPnl") or 0.0),
        total_fees=float(r.get("openFee") or 0.0) + float(r.get("closeFee") or 0.0),
        total_funding=0.0, r_multiple=None, duration_seconds=None,
        position_key=f"{account.id}:{r['symbol']}:cpnl:{r['orderId']}",
        opened_at_source=OpenedAtSource.ESTIMATED,
        leverage=float(r.get("leverage") or 0.0) or None,
    )


def _open_position_to_row(account, r) -> dict:
    # position/list `side`: Buy = long, Sell = short.
    side = str(r.get("side", "")).upper()
    direction = Direction.LONG if side.startswith("B") else Direction.SHORT
    ct = r.get("createdTime")
    opened_at = datetime.fromtimestamp(int(ct) / 1000, tz=timezone.utc) if ct else datetime.now(timezone.utc)
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, symbol=r["symbol"],
        asset_class=AssetClass.PERP, direction=direction, status=PositionStatus.OPEN,
        opened_at=opened_at, closed_at=None,
        avg_entry=float(r.get("avgPrice") or 0.0), avg_exit=None,
        quantity=float(r.get("size") or 0.0), realized_pnl=0.0,
        total_fees=0.0, total_funding=0.0, r_multiple=None, duration_seconds=None,
        position_key=f"{account.id}:{r['symbol']}:open",
        opened_at_source=OpenedAtSource.EXACT,
        leverage=float(r.get("leverage") or 0.0) or None,
    )


def sync_account(db: Session, account: ExchangeAccount) -> dict:
    if not account.encrypted_credentials:
        return {"error": "no credentials", "fills_added": 0, "funding_added": 0}
    _syncing.add(account.id)
    summary = {"fills_added": 0, "funding_added": 0, "windows": 0,
               "closed_added": 0, "open_count": 0, "error": None}
    now_iso = lambda: datetime.now(timezone.utc).isoformat()
    try:
        client = _client_for(account)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = int(account.sync_cursor) if account.sync_cursor else now_ms - BACKFILL_MS
        start_ms = max(start_ms, now_ms - BACKFILL_MS)  # never query older than Bybit allows
        windows = list(_windows(start_ms, now_ms))
        affected: set[str] = set()
        max_exec_ms = start_ms

        progress = {
            "state": "running", "started_at": now_iso(), "updated_at": now_iso(),
            "from_ms": start_ms, "to_ms": now_ms, "cursor_ms": start_ms,
            "fills": 0, "funding": 0, "windows_done": 0, "windows_total": len(windows),
        }
        account.sync_progress = dict(progress); db.commit()

        for wi, (ws, we) in enumerate(windows):
            wd = datetime.fromtimestamp(ws / 1000, tz=timezone.utc).date()
            log.info("bybit acct %s window %d/%d %s — fetching", account.id, wi + 1, len(windows), wd)
            candidates: list[dict] = []
            for ex in client.iter_executions(ws, we):
                candidates.append(_exec_to_fill(account, ex))
                max_exec_ms = max(max_exec_ms, int(ex["execTime"]))
            for fn in client.iter_funding(ws, we):
                candidates.append(_funding_to_fill(account, fn))
            log.info("bybit acct %s window %d/%d %s — %d rows fetched", account.id, wi + 1, len(windows), wd, len(candidates))

            if candidates:
                # Dedup WITHIN the batch first — Bybit can return the same exec/funding
                # id across overlapping pages, and two rows with the same external_fill_id
                # in one commit violate the unique index (IntegrityError) and abort the window.
                seen: set[str] = set()
                batch = []
                for c in candidates:
                    eid = c["external_fill_id"]
                    if eid in seen:
                        continue
                    seen.add(eid)
                    batch.append(c)
                existing = {
                    r[0] for r in db.query(Fill.external_fill_id).filter(
                        Fill.exchange_account_id == account.id,
                        Fill.external_fill_id.in_(list(seen)),
                    ).all()
                }
                for c in batch:
                    if c["external_fill_id"] in existing:
                        continue
                    db.add(Fill(**c))
                    affected.add(c["symbol"])
                    key = "funding_added" if c["external_fill_id"].startswith("funding:") else "fills_added"
                    summary[key] += 1
                db.commit()

            # Balance snapshots ride the same window sweep (own try: a
            # transaction-log hiccup must not fail the fill sync).
            try:
                from app.perps.services.balance_sync import snapshot_window
                summary["balance_rows"] = summary.get("balance_rows", 0) + snapshot_window(
                    db, account, list(client.iter_transaction_log(ws, we)))
            except Exception:
                log.exception("balance snapshot window failed for account %s", account.id)

            summary["windows"] += 1

            # Per-window progress (assign a fresh dict so SQLAlchemy flushes the JSON).
            progress.update(cursor_ms=we, fills=summary["fills_added"], funding=summary["funding_added"],
                            windows_done=summary["windows"], updated_at=now_iso())
            account.sync_progress = dict(progress)
            # Advance the durable cursor per completed window so an interrupted sync
            # resumes from here instead of re-scanning the whole 2-year backfill.
            account.sync_cursor = str(we)
            db.commit()

        account.sync_cursor = str(max_exec_ms)
        account.last_synced_at = datetime.now(timezone.utc)
        account.last_sync_error = None
        progress.update(state="ok", updated_at=now_iso())
        account.sync_progress = dict(progress); db.commit()

        # Closed positions: authoritative, from Bybit's closed-P&L (correct past the
        # 2-year fill wall). Upsert by stable :cpnl:<orderId> key (idempotent for both
        # full and incremental syncs).
        for ws, we in windows:
            for r in client.iter_closed_pnl(ws, we):
                row = _closed_pnl_to_position(account, r)
                db.query(Position).filter(
                    Position.exchange_account_id == account.id,
                    Position.position_key == row["position_key"],
                ).delete(synchronize_session=False)
                db.add(Position(**row))
                summary["closed_added"] += 1
        db.commit()

        # Self-healing cleanup: purge legacy fill-netted closed positions (no :cpnl: key)
        # that the old broken pipeline produced.
        db.query(Position).filter(
            Position.exchange_account_id == account.id,
            Position.status == PositionStatus.CLOSED,
            or_(Position.position_key.is_(None), ~Position.position_key.like("%:cpnl:%")),
        ).delete(synchronize_session=False)
        db.commit()

        # Open positions: full snapshot replace from live position/list.
        db.query(Position).filter(
            Position.exchange_account_id == account.id,
            Position.status == PositionStatus.OPEN,
        ).delete(synchronize_session=False)
        for r in client.fetch_open_positions():
            db.add(Position(**_open_position_to_row(account, r)))
            summary["open_count"] += 1
        db.commit()

        # Attribution pass: link fills to closed-pnl positions (real entry
        # times, executions, funding) and fill in MFE/MAE. Failures here must
        # never fail the sync itself.
        try:
            from app.perps.services.position_linker import link_account
            from app.perps.services.mfe import compute_mfe_mae
            linked = link_account(db, account)
            summary["linked_exact"] = linked["exact"]
            summary["linked_estimated"] = linked["estimated"]
            summary["mfe_computed"] = compute_mfe_mae(db, account)
        except Exception:
            log.exception("post-sync link/mfe failed for account %s", account.id)
    except Exception as e:  # noqa: BLE001 — record, don't crash the caller/scheduler
        log.exception("bybit sync failed for account %s", account.id)
        account.last_sync_error = str(e)[:500]
        try:
            prog = dict(account.sync_progress or {})
            prog.update(state="error", error=str(e)[:500], updated_at=now_iso())
            account.sync_progress = prog
        except Exception:
            pass
        db.commit()
        summary["error"] = str(e)
    finally:
        _syncing.discard(account.id)
    return summary
