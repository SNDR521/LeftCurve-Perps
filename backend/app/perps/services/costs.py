"""Funding, fee, and leverage cost analytics for perps positions.

Standard Bybit linear rates (approximations only — individual account rates
may differ by tier or promotion):
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.perps.models import BalanceSnapshot, Fill, Position, PositionStatus

# Standard Bybit linear perpetuals rates
TAKER_BPS = 0.055   # taker fee %, e.g. 0.055% per side
MAKER_BPS = 0.02    # maker fee %, e.g. 0.020% per side
# Savings estimate is an approximation: assumes taker volume fully converted to maker.


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _as_dt(value, end_of_day: bool = False):
    """Coerce a 'YYYY-MM-DD' string (or datetime) into a naive datetime.

    Postgres/psycopg3 rejects ``timestamp >= text``, so date-range filters must
    bind a real datetime.  Mirrors the helper in app.perps.services.analytics.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    d = datetime.fromisoformat(str(value)[:10])
    return d.replace(hour=23, minute=59, second=59, microsecond=999999) if end_of_day else d


def _gross_profit(db: Session, account_id: int | None, user_id: int,
                  from_date=None, to_date=None) -> float:
    """Sum of positive realized_pnl across closed positions for the user/account.

    When from_date/to_date are supplied only positions closed within that window
    contribute (filters by closed_at, matching the other perps analytics helpers).
    """
    q = (db.query(Position)
         .filter(Position.user_id == user_id,
                 Position.status == PositionStatus.CLOSED))
    if account_id is not None:
        q = q.filter(Position.exchange_account_id == account_id)
    if from_date is not None:
        q = q.filter(Position.closed_at >= _as_dt(from_date))
    if to_date is not None:
        q = q.filter(Position.closed_at <= _as_dt(to_date, end_of_day=True))
    return sum(p.realized_pnl for p in q.all() if p.realized_pnl > 0)


def _closed_positions(db: Session, account_id: int | None, user_id: int,
                      from_date=None, to_date=None):
    q = (db.query(Position)
         .filter(Position.user_id == user_id,
                 Position.status == PositionStatus.CLOSED))
    if account_id is not None:
        q = q.filter(Position.exchange_account_id == account_id)
    if from_date is not None:
        q = q.filter(Position.closed_at >= _as_dt(from_date))
    if to_date is not None:
        q = q.filter(Position.closed_at <= _as_dt(to_date, end_of_day=True))
    return q.all()


# ---------------------------------------------------------------------------
# compute_funding
# ---------------------------------------------------------------------------

def compute_funding(db: Session, account_id: int | None, user_id: int,
                    from_date: str | None = None, to_date: str | None = None) -> dict:
    """Aggregate funding payments for the user (optionally filtered by account/dates).

    Returns:
        total_paid    – sum of negative funding_amount values (always <= 0)
        total_received – sum of positive funding_amount values (always >= 0)
        net           – total_paid + total_received
        pct_of_gross  – abs(net) / gross_profit * 100 when gross > 0, else None
        by_symbol     – [{symbol, paid, received, net}] sorted net ascending (worst first)
        by_month      – [{month: "YYYY-MM", net}] sorted by month
    """
    q = (db.query(Fill)
         .filter(Fill.user_id == user_id,
                 Fill.funding_amount.isnot(None),
                 Fill.quantity <= 1e-9))
    if account_id is not None:
        q = q.filter(Fill.exchange_account_id == account_id)
    if from_date is not None:
        q = q.filter(Fill.executed_at >= _as_dt(from_date))
    if to_date is not None:
        q = q.filter(Fill.executed_at <= _as_dt(to_date, end_of_day=True))
    fills = q.all()

    total_paid = 0.0
    total_received = 0.0
    by_symbol: dict[str, dict] = defaultdict(lambda: {"paid": 0.0, "received": 0.0, "net": 0.0})
    by_month: dict[str, float] = defaultdict(float)

    for f in fills:
        amt = f.funding_amount
        if amt is None:
            continue
        sym = by_symbol[f.symbol]
        month = f.executed_at.strftime("%Y-%m")
        if amt < 0:
            total_paid += amt
            sym["paid"] += amt
        else:
            total_received += amt
            sym["received"] += amt
        sym["net"] += amt
        by_month[month] += amt

    net = total_paid + total_received
    gross = _gross_profit(db, account_id, user_id, from_date, to_date)
    pct_of_gross = abs(net) / gross * 100 if gross > 0 else None

    sym_list = sorted(
        [{"symbol": s, "paid": round(v["paid"], 10), "received": round(v["received"], 10),
          "net": round(v["net"], 10)} for s, v in by_symbol.items()],
        key=lambda r: r["net"],
    )
    month_list = sorted(
        [{"month": m, "net": round(n, 10)} for m, n in by_month.items()],
        key=lambda r: r["month"],
    )

    return {
        "total_paid": total_paid,
        "total_received": total_received,
        "net": net,
        "pct_of_gross": pct_of_gross,
        "by_symbol": sym_list,
        "by_month": month_list,
    }


# ---------------------------------------------------------------------------
# compute_fees
# ---------------------------------------------------------------------------

def compute_fees(db: Session, account_id: int | None, user_id: int,
                 from_date: str | None = None, to_date: str | None = None) -> dict:
    """Aggregate trading fees for the user (optionally filtered by account/dates).

    Taker vs maker is determined from fill.raw["isMaker"]:
        - raw missing or None → treated as taker (conservative default)
        - isMaker False or absent key → taker
        - isMaker True → maker

    Returns:
        total                 – total fees paid
        taker_fees            – fees from taker fills
        maker_fees            – fees from maker fills
        taker_share_pct       – taker fill COUNT / total fill count * 100
        pct_of_gross          – total / gross_profit * 100, else None
        maker_savings_estimate – savings if all taker volume had been maker
        by_symbol             – [{symbol, fees_total, round_trip_cost}]
                                round_trip_cost = fees / max(closed_position_count, 1)
    """
    q = (db.query(Fill)
         .filter(Fill.user_id == user_id,
                 Fill.quantity > 1e-9))
    if account_id is not None:
        q = q.filter(Fill.exchange_account_id == account_id)
    if from_date is not None:
        q = q.filter(Fill.executed_at >= _as_dt(from_date))
    if to_date is not None:
        q = q.filter(Fill.executed_at <= _as_dt(to_date, end_of_day=True))
    fills = q.all()

    total = 0.0
    taker_fees = 0.0
    maker_fees = 0.0
    taker_count = 0
    maker_count = 0
    by_symbol_fees: dict[str, float] = defaultdict(float)

    for f in fills:
        is_maker = bool(f.raw and f.raw.get("isMaker"))
        fee = f.fee or 0.0
        total += fee
        by_symbol_fees[f.symbol] += fee
        if is_maker:
            maker_fees += fee
            maker_count += 1
        else:
            taker_fees += fee
            taker_count += 1

    fill_count = taker_count + maker_count
    taker_share_pct = taker_count / fill_count * 100 if fill_count > 0 else 0.0

    gross = _gross_profit(db, account_id, user_id, from_date, to_date)
    pct_of_gross = total / gross * 100 if gross > 0 else None

    maker_savings_estimate = taker_fees * (TAKER_BPS - MAKER_BPS) / TAKER_BPS if taker_fees > 0 else 0.0

    # closed position count per symbol (same date window as fills)
    closed_pos_q = (db.query(Position)
                    .filter(Position.user_id == user_id,
                            Position.status == PositionStatus.CLOSED))
    if account_id is not None:
        closed_pos_q = closed_pos_q.filter(Position.exchange_account_id == account_id)
    if from_date is not None:
        closed_pos_q = closed_pos_q.filter(Position.closed_at >= _as_dt(from_date))
    if to_date is not None:
        closed_pos_q = closed_pos_q.filter(Position.closed_at <= _as_dt(to_date, end_of_day=True))
    sym_pos_count: dict[str, int] = defaultdict(int)
    for p in closed_pos_q.all():
        sym_pos_count[p.symbol] += 1

    # NOTE: fees_total includes open-position fills while round_trip_cost
    # divides by CLOSED count only — a symbol with an open position slightly
    # overstates its per-trade cost until the position closes.
    by_symbol = sorted(
        (
            {
                "symbol": sym,
                "fees_total": fees,
                "round_trip_cost": fees / max(sym_pos_count[sym], 1),
            }
            for sym, fees in by_symbol_fees.items()
        ),
        key=lambda r: -r["fees_total"],
    )

    return {
        "total": total,
        "taker_fees": taker_fees,
        "maker_fees": maker_fees,
        "taker_share_pct": taker_share_pct,
        "pct_of_gross": pct_of_gross,
        "maker_savings_estimate": maker_savings_estimate,
        "by_symbol": by_symbol,
    }


# ---------------------------------------------------------------------------
# compute_leverage
# ---------------------------------------------------------------------------

# Bucket definitions: (label, lo_exclusive, hi_inclusive)
_LEVERAGE_BUCKETS = [
    ("≤3x",   0,    3),
    ("3–5x",  3,    5),
    ("5–10x", 5,   10),
    ("10–20x",10,  20),
    (">20x",  20, 1e9),
]


def compute_leverage(db: Session, account_id: int | None, user_id: int,
                     from_date: str | None = None, to_date: str | None = None) -> dict:
    """Bucket closed positions by leverage.

    Returns:
        {"buckets": [
            {"bucket": label, "trade_count": int, "win_rate": float,
             "total_pnl": float, "avg_pnl": float | None},
            ...
            {"bucket": "unknown", ...}   # positions with no leverage stored
        ]}
    """
    positions = _closed_positions(db, account_id, user_id, from_date, to_date)

    # accumulate per bucket
    bucket_data: dict[str, dict] = {
        label: {"pnls": []}
        for label, *_ in _LEVERAGE_BUCKETS
    }
    bucket_data["unknown"] = {"pnls": []}

    for p in positions:
        lev = p.leverage
        if lev is None:
            bucket_data["unknown"]["pnls"].append(p.realized_pnl)
            continue
        assigned = False
        for label, lo, hi in _LEVERAGE_BUCKETS:
            if lo < lev <= hi:
                bucket_data[label]["pnls"].append(p.realized_pnl)
                assigned = True
                break
        if not assigned:
            # e.g. leverage == 0
            bucket_data["unknown"]["pnls"].append(p.realized_pnl)

    def _make_row(label: str) -> dict:
        pnls = bucket_data[label]["pnls"]
        count = len(pnls)
        win_rate = sum(1 for x in pnls if x > 0) / count * 100 if count > 0 else 0.0
        total_pnl = sum(pnls)
        avg_pnl = total_pnl / count if count > 0 else None
        row: dict = {
            "bucket": label,
            "trade_count": count,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
        }
        if count > 0:
            row["avg_pnl"] = avg_pnl
        return row

    buckets = [_make_row(label) for label, *_ in _LEVERAGE_BUCKETS]
    buckets.append(_make_row("unknown"))

    return {"buckets": buckets}


# ---------------------------------------------------------------------------
# compute_equity
# ---------------------------------------------------------------------------

def compute_equity(db: Session, account_id: int | None, user_id: int) -> dict:
    """True wallet curve from balance snapshots, with transfer markers and
    the two discipline stats a trader sizes down by: drawdown from peak and
    days since the last equity high."""
    q = db.query(BalanceSnapshot).filter(BalanceSnapshot.user_id == user_id)
    if account_id is not None:
        q = q.filter(BalanceSnapshot.exchange_account_id == account_id)
    rows = q.order_by(BalanceSnapshot.ts.asc()).all()
    points = [{"date": r.ts.strftime("%Y-%m-%d"), "balance": r.balance}
              for r in rows if r.kind == "SNAPSHOT"]
    transfers = [{"ts": r.ts.isoformat(), "kind": r.kind, "balance": r.balance}
                 for r in rows if r.kind != "SNAPSHOT"]
    stats = None
    if points:
        peak = max(p["balance"] for p in points)
        peak_date = next(p["date"] for p in points if p["balance"] == peak)
        current = points[-1]["balance"]
        stats = {
            "peak": peak,
            "current": current,
            "drawdown_from_peak_pct": ((peak - current) / peak * 100) if peak > 0 else None,
            "days_since_high": max(0, (datetime.now(timezone.utc).date()
                                       - datetime.strptime(peak_date, "%Y-%m-%d").date()).days),
        }
    return {"points": points, "transfers": transfers, "stats": stats}
