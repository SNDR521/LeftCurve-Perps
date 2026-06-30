"""Incremental, idempotent RiseX account sync.

Fills come from trade-history (the ledger + fees). Closed positions are
RECONSTRUCTED from those fills as round-trips — RiseX's realized-pnl endpoint
emits one event PER FILL (including the opening fill, which shows exit=0 and
pnl=-entry-fee), so it is NOT a clean per-position feed; netting the fills into
round-trips (like the Hyperliquid connector) is the correct model. RiseX gives
realized_pnl per fill, so a round-trip's net P&L is just the sum. Open positions
are a full-snapshot replace from portfolio/details.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.security import decrypt_credentials
from app.perps.connectors.risex import RiseXClient
from app.perps.models import (
    ExchangeAccount, Fill, Position, AssetClass, Side, Direction,
    PositionStatus, OpenedAtSource,
)

log = logging.getLogger(__name__)
settings = get_settings()
_syncing: set[int] = set()
# RiseX history retention is unstated (on-chain — assume full); backfill ~2 years
# like the other venues. trade-history start_time/end_time are nanoseconds.
BACKFILL_NS = (2 * 365) * 24 * 3600 * 1_000_000_000
_EPS = 1e-9


def is_syncing(account_id: int) -> bool:
    return account_id in _syncing


def _client_for(account: ExchangeAccount) -> RiseXClient:
    creds = decrypt_credentials(account.encrypted_credentials)
    return RiseXClient(creds["address"], settings.risex_api_base)


def _fill_view(row: Fill) -> dict:
    """Reconstruction view of a stored Fill. realized_pnl + position_side live
    only in the original trade-history payload (Fill.raw); price/size/fee/symbol
    fall back to the stored columns."""
    raw = row.raw or {}
    side = str(raw.get("side") or (row.side.value if row.side else "")).upper()
    return {
        "id": row.external_fill_id,
        "symbol": row.symbol,
        "side": side,
        "position_side": str(raw.get("position_side") or side).upper(),
        "price": float(raw.get("price") if raw.get("price") not in (None, "") else (row.price or 0.0)),
        "size": float(raw.get("size") if raw.get("size") not in (None, "") else (row.quantity or 0.0)),
        "fee": float(raw.get("fee") if raw.get("fee") not in (None, "") else (row.fee or 0.0)),
        "realized_pnl": float(raw.get("realized_pnl") or 0.0),
        "time_ns": int(raw.get("time") or int(row.executed_at.replace(tzinfo=timezone.utc).timestamp() * 1e9)),
    }


def _episode_to_row(account, symbol: str, epi: dict) -> dict:
    direction = Direction.LONG if epi["ps"].startswith("B") else Direction.SHORT
    open_qty = epi["open_qty"]
    avg_entry = epi["entry_notional"] / open_qty if open_qty > _EPS else 0.0
    avg_exit = epi["exit_notional"] / epi["close_qty"] if epi["close_qty"] > _EPS else 0.0
    opened_at = datetime.fromtimestamp(epi["open_ns"] / 1_000_000_000, tz=timezone.utc)
    closed_at = datetime.fromtimestamp(epi["close_ns"] / 1_000_000_000, tz=timezone.utc)
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, symbol=symbol,
        asset_class=AssetClass.PERP, direction=direction, status=PositionStatus.CLOSED,
        opened_at=opened_at, closed_at=closed_at,
        avg_entry=avg_entry, avg_exit=avg_exit, quantity=open_qty,
        realized_pnl=epi["pnl"], total_fees=epi["fees"], total_funding=0.0,
        r_multiple=None,
        duration_seconds=max(0, int((closed_at - opened_at).total_seconds())),
        # stable per round-trip = the closing fill's id; idempotent across re-syncs
        position_key=f"{account.id}:{symbol}:rt:{epi['last_id']}",
        opened_at_source=OpenedAtSource.EXACT,  # real open+close times from fills
        leverage=None,
    )


def build_closed_positions(account, views: list[dict]) -> list[dict]:
    """Net fills into closed round-trips, per symbol. A fill is an ENTRY when its
    side equals the position_side (adds to the position) and an EXIT otherwise; an
    episode closes when exit qty >= entry qty (flat). Each fill's realized_pnl and
    fee are summed, so the round-trip's net P&L includes fees exactly as RiseX
    reports them. A change in position_side starts a new episode. The trailing
    un-flat episode (the live open position) is skipped — the open snapshot owns
    it. Returns Position-row dicts."""
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    for v in views:
        by_symbol[v["symbol"]].append(v)
    out: list[dict] = []
    for symbol, fills in by_symbol.items():
        fills = sorted(fills, key=lambda f: f["time_ns"])
        epi = None
        for f in fills:
            ps = f["position_side"] or f["side"]
            if epi is None or epi["ps"] != ps:
                epi = {"ps": ps, "open_qty": 0.0, "close_qty": 0.0,
                       "entry_notional": 0.0, "exit_notional": 0.0,
                       "pnl": 0.0, "fees": 0.0,
                       "open_ns": f["time_ns"], "close_ns": f["time_ns"], "last_id": f["id"]}
            sz = f["size"]
            if f["side"] == ps:  # entry (adds to position)
                epi["open_qty"] += sz
                epi["entry_notional"] += f["price"] * sz
            else:                 # exit (reduces / closes)
                epi["close_qty"] += sz
                epi["exit_notional"] += f["price"] * sz
            epi["pnl"] += f["realized_pnl"]
            epi["fees"] += f["fee"]
            epi["close_ns"] = f["time_ns"]
            epi["last_id"] = f["id"]
            if epi["open_qty"] > _EPS and epi["close_qty"] >= epi["open_qty"] - _EPS:
                out.append(_episode_to_row(account, symbol, epi))
                epi = None
    return out


def _fill_to_row(account, t, symbol: str) -> dict:
    side = str(t.get("side", "")).upper()
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, venue=account.venue,
        external_fill_id=str(t["id"]),
        order_id=str(t.get("order_id")) if t.get("order_id") is not None else None,
        symbol=symbol, asset_class=AssetClass.PERP,
        side=Side.BUY if side.startswith("B") else Side.SELL,
        price=float(t.get("price") or 0.0), quantity=float(t.get("size") or 0.0),
        fee=float(t.get("fee") or 0.0),
        executed_at=datetime.fromtimestamp(int(t["time"]) / 1_000_000_000, tz=timezone.utc),
        raw=t,
    )


def _open_position_to_row(account, r) -> dict:
    direction = Direction.LONG if str(r.get("side", "")).upper().startswith("B") else Direction.SHORT
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, symbol=r["symbol"],
        asset_class=AssetClass.PERP, direction=direction, status=PositionStatus.OPEN,
        opened_at=datetime.now(timezone.utc), closed_at=None,
        avg_entry=float(r.get("avgPrice") or 0.0), avg_exit=None,
        quantity=float(r.get("size") or 0.0), realized_pnl=0.0,
        total_fees=0.0, total_funding=0.0, r_multiple=None, duration_seconds=None,
        position_key=f"{account.id}:{r['symbol']}:open",
        opened_at_source=OpenedAtSource.ESTIMATED,
        leverage=float(r["leverage"]) if r.get("leverage") else None,
    )


def sync_account(db: Session, account: ExchangeAccount) -> dict:
    if not account.encrypted_credentials:
        return {"error": "no credentials", "closed_added": 0, "fills_added": 0, "open_count": 0}
    _syncing.add(account.id)
    summary = {"closed_added": 0, "fills_added": 0, "open_count": 0, "error": None}
    now_iso = lambda: datetime.now(timezone.utc).isoformat()
    client = None
    try:
        client = _client_for(account)
        now_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
        start_ns = int(account.sync_cursor) if account.sync_cursor else now_ns - BACKFILL_NS
        start_ns = max(start_ns, now_ns - BACKFILL_NS)
        max_ns = start_ns

        progress = {
            "state": "running", "started_at": now_iso(), "updated_at": now_iso(),
            "from_ms": start_ns // 1_000_000, "to_ms": now_ns // 1_000_000,
            "cursor_ms": start_ns // 1_000_000, "fills": 0, "funding": 0,
        }
        account.sync_progress = dict(progress)
        db.commit()

        markets = client.fetch_markets()

        # --- 1. Fills from trade-history (dedup within-batch + against DB) ---
        candidates = []
        for t in client.iter_trade_history(start_ns, now_ns):
            symbol = markets.get(int(t["market_id"]), client.market_name(t["market_id"]))
            candidates.append(_fill_to_row(account, t, symbol))
            max_ns = max(max_ns, int(t["time"]))
        if candidates:
            seen, batch = set(), []
            for c in candidates:
                if c["external_fill_id"] in seen:
                    continue
                seen.add(c["external_fill_id"]); batch.append(c)
            CHUNK = 500
            for i in range(0, len(batch), CHUNK):
                chunk = batch[i:i + CHUNK]
                ids = [c["external_fill_id"] for c in chunk]
                existing = {r[0] for r in db.query(Fill.external_fill_id).filter(
                    Fill.exchange_account_id == account.id,
                    Fill.external_fill_id.in_(ids)).all()}
                for c in chunk:
                    if c["external_fill_id"] in existing:
                        continue
                    db.add(Fill(**c)); summary["fills_added"] += 1
                db.commit()
        progress.update(cursor_ms=max_ns // 1_000_000, fills=summary["fills_added"], updated_at=now_iso())
        account.sync_progress = dict(progress)
        db.commit()

        # --- 2. Rebuild ALL closed positions by netting the full stored fill set
        # into round-trips (a round-trip can span the incremental cursor, so a full
        # rebuild stays correct + idempotent — mirrors hyperliquid_sync). ---
        views = [_fill_view(r) for r in
                 db.query(Fill).filter(Fill.exchange_account_id == account.id).all()]
        db.query(Position).filter(
            Position.exchange_account_id == account.id,
            Position.status == PositionStatus.CLOSED,
        ).delete(synchronize_session=False)
        for row in build_closed_positions(account, views):
            db.add(Position(**row))
            summary["closed_added"] += 1
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

        account.sync_cursor = str(max_ns)
        account.last_synced_at = datetime.now(timezone.utc)
        account.last_sync_error = None
        progress.update(state="ok", cursor_ms=now_ns // 1_000_000,
                        fills=summary["fills_added"], updated_at=now_iso())
        account.sync_progress = dict(progress)
        db.commit()
    except Exception as e:  # noqa: BLE001 — record, never crash the scheduler/caller
        log.exception("risex sync failed for account %s", account.id)
        account.last_sync_error = str(e)[:500]
        try:
            account.sync_progress = {"state": "error", "error": str(e)[:500], "updated_at": now_iso()}
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
