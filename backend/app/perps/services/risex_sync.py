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
    ExchangeAccount, BalanceSnapshot, Fill, Position, PositionFill,
    AssetClass, Side, Direction, PositionStatus, OpenedAtSource,
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
        # fill_ids is NOT a Position column — it is popped by the caller (sync_account)
        # before constructing the Position ORM object, and used to create PositionFill links.
        fill_ids=list(epi.get("fill_ids", [])),
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
                       "open_ns": f["time_ns"], "close_ns": f["time_ns"], "last_id": f["id"],
                       "fill_ids": []}
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
            epi["fill_ids"].append(f["id"])
            if epi["open_qty"] > _EPS and epi["close_qty"] >= epi["open_qty"] - _EPS:
                out.append(_episode_to_row(account, symbol, epi))
                epi = None
    return out


def build_balance_snapshots(account, realized_now: float, events: list[dict],
                            transfers: list[dict]) -> list[dict]:
    """Reconstruct daily-last balance snapshots + transfer markers.

    `events`: realized-pnl deltas [{ts_ns, delta=pnl+funding}].
    `transfers`: [{ts_ns, delta=signed_amount, kind="TRANSFER_IN"/"TRANSFER_OUT"}].
    Anchor: the running balance after ALL events/transfers == realized_now. So
    initial = realized_now - sum(all deltas); walk ascending accumulating; the
    daily-last running balance is each day's SNAPSHOT. Returns row dicts
    {ts(naive UTC datetime), balance, kind}."""
    # Drop events with an unparseable/zero timestamp — they can't be placed on the
    # time axis (a 0 ts would land at 1970-01-01 and wreck the chart's x-range).
    # The anchor stays correct: a dropped delta is absorbed into the initial baseline.
    combined = sorted([e for e in (*events, *transfers) if e["ts_ns"] > 0],
                      key=lambda e: e["ts_ns"])
    total = sum(e["delta"] for e in combined)
    running = realized_now - total
    out: list[dict] = []
    daily_last: dict = {}  # day(naive midnight) -> (ts_ns, balance)
    for e in combined:
        running += e["delta"]
        when = datetime.fromtimestamp(e["ts_ns"] / 1_000_000_000, tz=timezone.utc).replace(tzinfo=None)
        if e.get("kind", "").startswith("TRANSFER"):
            out.append({"ts": when, "balance": running, "kind": e["kind"]})
        day = when.replace(hour=0, minute=0, second=0, microsecond=0)
        prev = daily_last.get(day)
        if prev is None or e["ts_ns"] >= prev[0]:
            daily_last[day] = (e["ts_ns"], running)
    if not daily_last:  # no events at all -> a single point at today's anchor
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
        daily_last[today] = (0, realized_now)
    for day, (_, bal) in daily_last.items():
        out.append({"ts": day, "balance": bal, "kind": "SNAPSHOT"})
    return out


def _rebuild_balance_snapshots(db: Session, account: ExchangeAccount, client) -> int:
    """Wipe + rebuild this account's BalanceSnapshot rows from the current
    realized balance + realized-pnl/funding + transfer history."""
    summary = (client.fetch_portfolio().get("summary") or {})
    realized_now = float(summary.get("total_account_value") or 0.0) - \
                   float(summary.get("total_unrealized_pnl") or 0.0)
    now_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
    start_ns = now_ns - BACKFILL_NS
    events = [{"ts_ns": int(ev["timestamp"]),
               "delta": float(ev.get("pnl") or 0.0) + float(ev.get("funding") or 0.0)}
              for ev in client.iter_realized_pnl(start_ns, now_ns)]
    transfers = []
    for t in client.iter_transfers(start_ns, now_ns):
        amt = abs(float(t.get("amount") or 0.0))
        # Real RiseX transfer shape: {"type": "DEPOSIT"/"WITHDRAW...",
        # "amount": "<positive>", "block_time": "<ns>"}. Deposits add, withdrawals
        # subtract; timestamp is block_time (ns).
        is_in = str(t.get("type") or "").upper().startswith("DEP")
        transfers.append({"ts_ns": int(t.get("block_time") or 0),
                          "delta": amt if is_in else -amt,
                          "kind": "TRANSFER_IN" if is_in else "TRANSFER_OUT"})
    rows = build_balance_snapshots(account, realized_now, events, transfers)
    db.query(BalanceSnapshot).filter(
        BalanceSnapshot.exchange_account_id == account.id).delete(synchronize_session=False)
    for r in rows:
        db.add(BalanceSnapshot(user_id=account.user_id, exchange_account_id=account.id,
                               ts=r["ts"], balance=r["balance"], kind=r["kind"]))
    db.commit()
    return len(rows)


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
        # Explicitly delete PositionFill links for this account's closed positions BEFORE
        # deleting the positions themselves. SQLite does not enforce FK cascades, so
        # relying on ondelete="CASCADE" alone would leave orphan rows in SQLite test DBs.
        # On Postgres the cascade would fire, but being explicit keeps both dialects clean
        # and prevents link accumulation across re-syncs.
        closed_pos_ids = [r[0] for r in db.query(Position.id).filter(
            Position.exchange_account_id == account.id,
            Position.status == PositionStatus.CLOSED).all()]
        if closed_pos_ids:
            db.query(PositionFill).filter(
                PositionFill.position_id.in_(closed_pos_ids)
            ).delete(synchronize_session=False)
        db.query(Position).filter(
            Position.exchange_account_id == account.id,
            Position.status == PositionStatus.CLOSED,
        ).delete(synchronize_session=False)
        # Build a lookup from external_fill_id -> Fill.id for this account so we can
        # resolve the external ids in each round-trip's fill_ids list.
        fill_id_by_ext = {ext: fid for ext, fid in db.query(Fill.external_fill_id, Fill.id).filter(
            Fill.exchange_account_id == account.id).all()}
        pending: list[tuple] = []  # (Position, [external_fill_id, ...])
        for row in build_closed_positions(account, views):
            fill_ids = row.pop("fill_ids", [])
            pos = Position(**row)
            db.add(pos)
            pending.append((pos, fill_ids))
            summary["closed_added"] += 1
        db.flush()  # assign pos.id before creating PositionFill links
        for pos, fill_ids in pending:
            for ext_id in fill_ids:
                fid = fill_id_by_ext.get(ext_id)
                if fid is not None:
                    db.add(PositionFill(position_id=pos.id, fill_id=fid))
        db.commit()

        # fetch_markets() (step 0) primed the portfolio memo before the fill
        # backfill above, which can take minutes on a first sync — drop it so the
        # open-positions snapshot and balance anchor below see a fresh portfolio.
        client.invalidate_portfolio()

        # --- 3. Open positions: full snapshot replace ---
        db.query(Position).filter(
            Position.exchange_account_id == account.id,
            Position.status == PositionStatus.OPEN,
        ).delete(synchronize_session=False)
        for r in client.fetch_open_positions():
            db.add(Position(**_open_position_to_row(account, r)))
            summary["open_count"] += 1
        db.commit()

        # --- 4. Reconstruct the true-equity balance snapshots (failure-isolated) ---
        try:
            summary["balance_rows"] = _rebuild_balance_snapshots(db, account, client)
        except Exception:  # noqa: BLE001 — never fail the sync over the equity curve
            log.exception("risex balance snapshot rebuild failed for account %s", account.id)

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
