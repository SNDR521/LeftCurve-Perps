"""Incremental, idempotent Hyperliquid account sync.

Ingest fills + funding (windowed, deduped by external_fill_id), then REBUILD all
closed positions from the full stored trade-fill set (Hyperliquid has no
closed-pnl endpoint, so a round trip can span the incremental cursor — a full
rebuild keeps it correct and idempotent), then full-replace the open snapshot.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.security import decrypt_credentials
from app.perps.connectors.hyperliquid import HyperliquidClient
from app.perps.models import (
    ExchangeAccount, Fill, AssetClass, Side, Position, PositionStatus, Direction,
    OpenedAtSource, PositionFill,
)
from app.perps.services.hyperliquid_positions import build_closed_positions

log = logging.getLogger(__name__)

SEVEN_DAYS_MS = 7 * 24 * 3600 * 1000
# Hyperliquid retains ~10k most-recent fills. Backfill from ~2 years ago; older
# fills simply won't be returned (accepted limit, documented in the spec).
BACKFILL_MS = (2 * 365) * 24 * 3600 * 1000

_syncing: set[int] = set()


def _ms(dt) -> int:
    """Epoch ms for a UTC datetime, tolerating naive (DB-reloaded) and aware values."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def is_syncing(account_id: int) -> bool:
    return account_id in _syncing


def _client_for(account: ExchangeAccount) -> HyperliquidClient:
    creds = decrypt_credentials(account.encrypted_credentials)
    return HyperliquidClient(creds["address"])


def _windows(start_ms: int, end_ms: int):
    ws = start_ms
    while ws < end_ms:
        we = min(ws + SEVEN_DAYS_MS, end_ms)
        yield ws, we
        ws = we


def _fill_to_row(account, fl) -> dict:
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, venue=account.venue,
        external_fill_id=str(fl["hash"]), order_id=str(fl.get("oid")) if fl.get("oid") is not None else None,
        symbol=fl["coin"], asset_class=AssetClass.PERP,
        side=Side.BUY if str(fl["side"]).upper().startswith("B") else Side.SELL,
        price=float(fl["px"]), quantity=float(fl["sz"]),
        fee=float(fl.get("fee") or 0.0), fee_currency=fl.get("feeToken"),
        executed_at=datetime.fromtimestamp(int(fl["time"]) / 1000, tz=timezone.utc),
        raw=fl,
    )


def _funding_to_row(account, fn) -> dict:
    delta = fn.get("delta") or fn
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, venue=account.venue,
        external_fill_id="funding:" + str(fn["hash"]), order_id=None,
        symbol=delta.get("coin"), asset_class=AssetClass.PERP, side=Side.BUY,
        price=0.0, quantity=0.0, fee=0.0,
        funding_amount=float(delta.get("usdc") or 0.0),
        executed_at=datetime.fromtimestamp(int(fn["time"]) / 1000, tz=timezone.utc),
        raw=fn,
    )


def _open_position_to_row(account, r) -> dict:
    side = str(r.get("side", "")).upper()
    direction = Direction.LONG if side.startswith("B") else Direction.SHORT
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, symbol=r["symbol"],
        asset_class=AssetClass.PERP, direction=direction, status=PositionStatus.OPEN,
        # clearinghouseState has no open time, so opened_at is synthetic (now) —
        # ESTIMATED keeps it out of time-based analytics, matching its provenance.
        opened_at=datetime.now(timezone.utc), closed_at=None,
        avg_entry=float(r.get("avgPrice") or 0.0), avg_exit=None,
        quantity=float(r.get("size") or 0.0), realized_pnl=0.0,
        total_fees=0.0, total_funding=0.0, r_multiple=None, duration_seconds=None,
        position_key=f"{account.id}:{r['symbol']}:open",
        opened_at_source=OpenedAtSource.ESTIMATED,
        leverage=float(r.get("leverage")) if r.get("leverage") else None,
    )


def sync_account(db: Session, account: ExchangeAccount) -> dict:
    if not account.encrypted_credentials:
        return {"error": "no credentials", "fills_added": 0, "funding_added": 0}
    _syncing.add(account.id)
    summary = {"fills_added": 0, "funding_added": 0, "windows": 0,
               "closed_added": 0, "open_count": 0, "error": None}
    now_iso = lambda: datetime.now(timezone.utc).isoformat()
    client = None
    try:
        client = _client_for(account)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms = int(account.sync_cursor) if account.sync_cursor else now_ms - BACKFILL_MS
        start_ms = max(start_ms, now_ms - BACKFILL_MS)
        windows = list(_windows(start_ms, now_ms))
        max_fill_ms = start_ms

        progress = {
            "state": "running", "started_at": now_iso(), "updated_at": now_iso(),
            "from_ms": start_ms, "to_ms": now_ms, "cursor_ms": start_ms,
            "fills": 0, "funding": 0, "windows_done": 0, "windows_total": len(windows),
        }
        account.sync_progress = dict(progress); db.commit()

        # --- 1. Ingest fills + funding (windowed, deduped) ---
        for wi, (ws, we) in enumerate(windows):
            wd = datetime.fromtimestamp(ws / 1000, tz=timezone.utc).date()
            log.info("hyperliquid acct %s window %d/%d %s — fetching",
                     account.id, wi + 1, len(windows), wd)
            candidates: list[dict] = []
            for fl in client.iter_fills_by_time(ws, we):
                candidates.append(_fill_to_row(account, fl))
                max_fill_ms = max(max_fill_ms, int(fl["time"]))
            for fn in client.iter_funding(ws, we):
                candidates.append(_funding_to_row(account, fn))
            log.info("hyperliquid acct %s window %d/%d %s — %d rows fetched",
                     account.id, wi + 1, len(windows), wd, len(candidates))

            if candidates:
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
                    key = "funding_added" if c["external_fill_id"].startswith("funding:") else "fills_added"
                    summary[key] += 1
                db.commit()

            summary["windows"] += 1
            progress.update(cursor_ms=we, fills=summary["fills_added"],
                            funding=summary["funding_added"],
                            windows_done=summary["windows"], updated_at=now_iso())
            account.sync_progress = dict(progress)
            account.sync_cursor = str(we)
            db.commit()

        account.sync_cursor = str(max_fill_ms)
        account.last_synced_at = datetime.now(timezone.utc)
        account.last_sync_error = None
        progress.update(state="ok", updated_at=now_iso())
        account.sync_progress = dict(progress); db.commit()

        # --- 2. Rebuild ALL closed positions from the full stored trade-fill set ---
        trade_fills = [
            row.raw for row in db.query(Fill).filter(
                Fill.exchange_account_id == account.id,
                ~Fill.external_fill_id.like("funding:%"),
            ).all() if row.raw
        ]
        # external_fill_id -> Fill.id for this account (built once, before adding
        # positions, so the per-trip lookup needs no mid-loop query/autoflush).
        fill_id_by_ext = {
            ext: fid for fid, ext in db.query(Fill.id, Fill.external_fill_id).filter(
                Fill.exchange_account_id == account.id,
                Fill.external_fill_id.isnot(None),
            ).all()
        }
        # Carry MFE/MAE forward by the stable position_key: the rebuild deletes +
        # reinserts every closed position each sync, so without this every sync would
        # recompute MFE for all positions and hammer Hyperliquid's candle endpoint.
        prev_mfe = {
            pk: (mp, mae, mu, mau) for pk, mp, mae, mu, mau in db.query(
                Position.position_key, Position.mfe_price, Position.mae_price,
                Position.mfe_usd, Position.mae_usd,
            ).filter(
                Position.exchange_account_id == account.id,
                Position.status == PositionStatus.CLOSED,
                Position.mfe_usd.isnot(None),
            ).all()
        }
        # Funding fills (qty-0, external_fill_id "funding:<hash>") grouped by symbol,
        # attributed to the closed position whose time window contains them.
        funding_by_symbol: dict[str, list] = defaultdict(list)
        for fn in db.query(Fill).filter(
            Fill.exchange_account_id == account.id,
            Fill.external_fill_id.like("funding:%"),
        ).all():
            funding_by_symbol[fn.symbol].append(fn)

        # Wipe this account's fill↔position links before rebuilding (SQLite has no
        # FK cascade; on Postgres the cascade would handle it, but be explicit so
        # both dialects behave identically and re-syncs don't accumulate links).
        db.query(PositionFill).filter(
            PositionFill.fill_id.in_(list(fill_id_by_ext.values()))
        ).delete(synchronize_session=False)
        db.query(Position).filter(
            Position.exchange_account_id == account.id,
            Position.status == PositionStatus.CLOSED,
        ).delete(synchronize_session=False)

        # Add all rebuilt positions, flush once to assign ids, then link their fills.
        # PositionFill links are what /positions/{id}/detail returns as executions —
        # they make the trade-detail chart render entry/exit markers for HL trades.
        pending: list[tuple] = []  # (Position, [trade external_fill_id, ...])
        for row in build_closed_positions(account, trade_fills):
            fill_ext_ids = row.pop("fill_external_ids", [])
            pos = Position(**row)
            carried = prev_mfe.get(pos.position_key)
            if carried is not None:
                pos.mfe_price, pos.mae_price, pos.mfe_usd, pos.mae_usd = carried
            db.add(pos)
            pending.append((pos, fill_ext_ids))
            summary["closed_added"] += 1
        db.flush()
        for pos, fill_ext_ids in pending:
            for ext in set(fill_ext_ids):
                fid = fill_id_by_ext.get(ext)
                if fid is not None:
                    db.add(PositionFill(position_id=pos.id, fill_id=fid))
            # Attribute funding settled while this position was open → total_funding,
            # and link those funding fills so the chart shows funding ticks.
            # Half-open window (open, close]: funding settled at the exact open
            # instant belongs to the prior period, so a flip fill (where one trip's
            # close == the next trip's open) never double-attributes funding.
            open_ms, close_ms = _ms(pos.opened_at), _ms(pos.closed_at)
            total_funding = 0.0
            for fn in funding_by_symbol.get(pos.symbol, []):
                if open_ms < _ms(fn.executed_at) <= close_ms:
                    total_funding += float(fn.funding_amount or 0.0)
                    db.add(PositionFill(position_id=pos.id, fill_id=fn.id))
            pos.total_funding = total_funding
        db.commit()

        # --- 3. Open positions: full snapshot replace ---
        db.query(Position).filter(
            Position.exchange_account_id == account.id,
            Position.status == PositionStatus.OPEN,
        ).delete(synchronize_session=False)
        for r in client.fetch_open_positions():
            db.add(Position(**_open_position_to_row(account, r)))
            summary["open_count"] += 1
        db.commit()

        # --- 4. MFE/MAE for newly-rebuilt closed positions (carry-forward above
        # means only genuinely-new round trips are recomputed). Failure-isolated:
        # a candle-fetch hiccup must never fail the sync. ---
        try:
            from app.perps.services.mfe import compute_mfe_mae
            summary["mfe_computed"] = compute_mfe_mae(db, account)
        except Exception:  # noqa: BLE001
            log.exception("HL mfe/mae failed for account %s", account.id)
    except Exception as e:  # noqa: BLE001 — record, never crash the scheduler/caller
        log.exception("hyperliquid sync failed for account %s", account.id)
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
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
    return summary
