"""Reconstruct closed positions from Hyperliquid fills.

Hyperliquid has no closed-pnl endpoint, so we net fills per coin chronologically.
A round trip runs from when the signed position leaves 0 until it returns to 0
(a flip through 0 closes the old trip and opens a new one). Realized P&L is the
sum of the closing fills' `closedPnl` — exact, straight from Hyperliquid. Pure
function over raw HL fill dicts (the stored `Fill.raw`); no DB, no network.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from app.perps.models import AssetClass, Direction, OpenedAtSource, PositionStatus


def _signed(fill) -> float:
    sz = float(fill["sz"])
    return sz if str(fill["side"]).upper().startswith("B") else -sz


def _ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _finalize(account, coin, rt) -> dict:
    # rt["opened_at"]/["closed_at"] are millisecond ints during the walk; the
    # Position columns are DateTime, so convert on the way out (duration is
    # computed from the raw ms before conversion).
    opened = rt["opened_qty"] or 1.0
    closed = rt["closed_qty"] or 1.0
    open_ms, close_ms = rt["opened_at"], rt["closed_at"]
    return dict(
        user_id=account.user_id, exchange_account_id=account.id, symbol=coin,
        asset_class=AssetClass.PERP,
        direction=Direction.LONG if rt["sign"] > 0 else Direction.SHORT,
        status=PositionStatus.CLOSED,
        opened_at=_ms_to_dt(open_ms), closed_at=_ms_to_dt(close_ms),
        avg_entry=rt["entry_notional"] / opened,
        avg_exit=rt["exit_notional"] / closed,
        quantity=rt["opened_qty"],
        realized_pnl=rt["realized"],
        total_fees=rt["fees"], total_funding=0.0,
        r_multiple=None,
        duration_seconds=int((close_ms - open_ms) / 1000) if close_ms >= open_ms else None,
        position_key=f"{account.id}:{coin}:hl:{rt['open_hash']}",
        opened_at_source=OpenedAtSource.EXACT,
        leverage=None,
        # external_fill_ids of the trades that compose this round trip; the sync
        # turns these into PositionFill links so the trade-detail chart can render
        # entry/exit markers. NOT a Position column — the sync pops it.
        fill_external_ids=list(rt["fill_ids"]),
    )


def _new_rt(fill, t, sign) -> dict:
    # closed_at starts as the open time (placeholder); overwritten by the first
    # closing fill. A trip with no closing fill is never finalized/emitted.
    return {"sign": sign, "opened_at": t, "closed_at": t, "open_hash": fill["hash"],
            "opened_qty": 0.0, "closed_qty": 0.0,
            "entry_notional": 0.0, "exit_notional": 0.0, "realized": 0.0, "fees": 0.0,
            "fill_ids": []}


def build_closed_positions(account, hl_trade_fills) -> list[dict]:
    by_coin: dict[str, list] = defaultdict(list)
    for fl in hl_trade_fills:
        by_coin[fl["coin"]].append(fl)

    positions: list[dict] = []
    for coin, fills in by_coin.items():
        fills.sort(key=lambda fl: (int(fl["time"]), int(fl.get("tid") or fl.get("oid") or 0)))
        rt = None
        for fl in fills:
            t = int(fl["time"])
            px = float(fl["px"])
            signed = _signed(fl)
            before = float(fl.get("startPosition") or 0.0)
            after = before + signed
            closed_pnl = float(fl.get("closedPnl") or 0.0)
            fee = float(fl.get("fee") or 0.0)

            if before == 0.0 or (before > 0) == (signed > 0):
                closed_qty = 0.0
                opened_qty = abs(signed)
            else:
                closed_qty = min(abs(signed), abs(before))
                opened_qty = abs(signed) - closed_qty  # > 0 only when flipping through 0

            # 1) Closing portion applies to the current round trip.
            if closed_qty > 0 and rt is not None:
                rt["closed_qty"] += closed_qty
                rt["exit_notional"] += px * closed_qty
                rt["realized"] += closed_pnl
                rt["fees"] += fee
                rt["closed_at"] = t
                rt["fill_ids"].append(fl["hash"])
                if after == 0.0 or (before > 0) != (after > 0):  # fully closed or flipped
                    positions.append(_finalize(account, coin, rt))
                    rt = None

            # 2) Opening portion starts or extends a round trip.
            if opened_qty > 0:
                if rt is None:
                    rt = _new_rt(fl, t, sign=1 if signed > 0 else -1)
                rt["opened_qty"] += opened_qty
                rt["entry_notional"] += px * opened_qty
                # Record the fill on this (new/extended) trip. On a flip the same
                # fill is also recorded on the closed trip above — it's both a
                # close and an open — and PositionFill's (position,fill) uniqueness
                # makes that correct, not a duplicate.
                rt["fill_ids"].append(fl["hash"])
                # On a flip fill (closed_qty > 0 AND opened_qty > 0) the single
                # fee was already booked to the closing trip above — a single
                # fill's fee can't be split, so the new trip carries none of it.
                if closed_qty == 0:
                    rt["realized"] += closed_pnl  # normally 0 on opens
                    rt["fees"] += fee
        # A leftover open round trip is intentionally not emitted — the open
        # snapshot in the sync owns currently-open positions.
    return positions
