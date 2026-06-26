from dataclasses import dataclass
from datetime import datetime

_EPS = 1e-9


@dataclass
class FillInput:
    side: str                 # "BUY" | "SELL"
    price: float
    quantity: float
    executed_at: datetime
    fee: float = 0.0
    funding_amount: float | None = None
    stop_price: float | None = None
    risk_amount: float | None = None
    asset_class: str = "PERP"


@dataclass
class PositionResult:
    direction: str            # "LONG" | "SHORT"
    status: str               # "OPEN" | "CLOSED"
    opened_at: datetime
    closed_at: datetime | None
    avg_entry: float
    avg_exit: float | None
    quantity: float
    realized_pnl: float
    total_fees: float
    total_funding: float
    r_multiple: float | None
    duration_seconds: int | None
    asset_class: str


def _open(f: FillInput, direction: int) -> dict:
    return {
        "direction": direction, "opened_at": f.executed_at, "asset_class": f.asset_class,
        "entry_qty": 0.0, "entry_notional": 0.0, "exit_qty": 0.0, "exit_notional": 0.0,
        "fees": 0.0, "funding": 0.0, "max_qty": 0.0, "open_remaining": 0.0,
        "stop_price": f.stop_price, "risk_amount": f.risk_amount,
    }


def _finalize(p: dict, closed_at: datetime | None) -> PositionResult:
    avg_entry = p["entry_notional"] / p["entry_qty"] if p["entry_qty"] > _EPS else 0.0
    avg_exit = p["exit_notional"] / p["exit_qty"] if p["exit_qty"] > _EPS else None
    if avg_exit is not None:
        realized = (avg_exit - avg_entry) * p["exit_qty"] * p["direction"] - p["fees"] + p["funding"]
    else:
        realized = -p["fees"] + p["funding"]
    risk = None
    if p["risk_amount"] is not None:
        risk = p["risk_amount"]
    elif p["stop_price"] is not None:
        risk = abs(avg_entry - p["stop_price"]) * p["max_qty"]
    r_multiple = realized / risk if risk not in (None, 0) else None
    closed = closed_at is not None and p["open_remaining"] <= _EPS
    duration = int((closed_at - p["opened_at"]).total_seconds()) if closed else None
    return PositionResult(
        direction="LONG" if p["direction"] > 0 else "SHORT",
        status="CLOSED" if closed else "OPEN",
        opened_at=p["opened_at"], closed_at=closed_at if closed else None,
        avg_entry=avg_entry, avg_exit=avg_exit, quantity=p["max_qty"],
        realized_pnl=realized, total_fees=p["fees"], total_funding=p["funding"],
        r_multiple=r_multiple, duration_seconds=duration, asset_class=p["asset_class"],
    )


def build_positions(fills: list[FillInput]) -> list[PositionResult]:
    """Derive positions from one (account, symbol)'s time-ordered fills. Pure & deterministic."""
    positions: list[PositionResult] = []
    pos: dict | None = None

    for f in fills:
        # Funding-only settlement (qty 0): attach its funding to the open position
        # without affecting size or avg price. Ignored when flat (no open position).
        if f.quantity <= _EPS:
            if pos is not None and f.funding_amount:
                pos["funding"] += f.funding_amount
            continue

        fdir = 1 if str(f.side).upper().endswith("BUY") else -1
        q = f.quantity
        fee_per = f.fee / f.quantity if f.quantity > _EPS else 0.0
        fund_per = (f.funding_amount or 0.0) / f.quantity if f.quantity > _EPS else 0.0

        while q > _EPS:
            if pos is None:
                pos = _open(f, fdir)
            if pos["direction"] == fdir:
                pos["entry_qty"] += q
                pos["entry_notional"] += f.price * q
                pos["open_remaining"] += q
                pos["max_qty"] = max(pos["max_qty"], pos["open_remaining"])
                pos["fees"] += fee_per * q
                pos["funding"] += fund_per * q
                q = 0.0
            else:
                close_qty = min(q, pos["open_remaining"])
                pos["exit_qty"] += close_qty
                pos["exit_notional"] += f.price * close_qty
                pos["open_remaining"] -= close_qty
                pos["fees"] += fee_per * close_qty
                pos["funding"] += fund_per * close_qty
                q -= close_qty
                if pos["open_remaining"] <= _EPS:
                    positions.append(_finalize(pos, f.executed_at))
                    pos = None

    if pos is not None:
        positions.append(_finalize(pos, None))
    return positions
