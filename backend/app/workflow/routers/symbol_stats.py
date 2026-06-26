"""Perps-only symbol stats endpoint.

GET /api/workflow/symbol-stats?symbols=A,B,C

Returns a map of symbol → stats for symbols that have at least one closed perps
position. Symbols with zero trades are omitted from the response.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.models import User
from app.database import get_db
from app.perps.models import Position as PerpsPosition, PositionStatus

router = APIRouter(prefix="/symbol-stats", tags=["workflow-symbol-stats"])


def _win_rate(winners: int, total: int) -> float:
    """Win rate as a fraction [0, 1]."""
    if total == 0:
        return 0.0
    return winners / total


def _iso_or_none(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.isoformat()


@router.get("")
def symbol_stats(
    symbols: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Per-symbol trade summary for closed perps positions.

    Query param ``symbols``: comma-separated list (case-insensitive; max 50).
    Response: a dict mapping UPPER-cased symbol to
        {trade_count, total_pnl, win_rate, last_traded (ISO|null), workspace}.
    Symbols with zero trades are omitted.
    """
    if not symbols:
        return {}

    raw = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    unique = list(dict.fromkeys(raw))  # preserve order, dedupe

    if len(unique) > 50:
        raise HTTPException(
            status_code=422,
            detail="Too many symbols: maximum is 50",
        )

    result: dict = {}

    for symbol in unique:
        # ── Perps: closed positions, exact symbol match ───────────────────────
        perps_positions = (
            db.query(PerpsPosition)
            .filter(
                PerpsPosition.user_id == user.id,
                PerpsPosition.status == PositionStatus.CLOSED,
                PerpsPosition.symbol == symbol,
            )
            .all()
        )
        total = len(perps_positions)
        if total == 0:
            continue  # omit symbols with zero trades

        total_pnl = sum(p.realized_pnl or 0.0 for p in perps_positions)
        winners = sum(1 for p in perps_positions if (p.realized_pnl or 0.0) > 0)
        win_rate = _win_rate(winners, total)
        last_traded = max(
            (p.closed_at for p in perps_positions if p.closed_at is not None),
            default=None,
        )

        result[symbol] = {
            "trade_count": total,
            "total_pnl": total_pnl,
            "win_rate": win_rate,
            "last_traded": _iso_or_none(last_traded),
            "workspace": "perps",
        }

    return result
