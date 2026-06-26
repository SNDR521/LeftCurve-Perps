"""Perps-only day scoring: the evening confrontation with the morning plan."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy.orm import Session

from app.perps.models import Position as PerpsPosition, PositionStatus


def window_for_card(card) -> tuple[datetime, datetime]:
    """The [start, end) session window for a plan card.

    The day starts at ``session_start_hour`` UTC on ``card.date`` and runs 24h.
    A trade at 05:00 UTC on the card's date with ``session_start_hour=6`` falls
    BEFORE this window's start and therefore belongs to the previous day's card.
    """
    start = datetime.combine(card.date, time(hour=card.session_start_hour or 0))
    return start, start + timedelta(days=1)


def score_window(db: Session, user_id: int, start: datetime, end: datetime,
                 workspace: str = "perps") -> dict:
    """Count closed perps positions whose ``closed_at`` falls in [start, end);
    sum realized P&L; return the sorted union of traded symbols (uppercased).

    ``workspace`` is accepted for API compatibility but only perps data is scored.
    """
    perps = (db.query(PerpsPosition)
             .filter(PerpsPosition.user_id == user_id,
                     PerpsPosition.status == PositionStatus.CLOSED,
                     PerpsPosition.closed_at >= start,
                     PerpsPosition.closed_at < end).all())
    realized = sum(p.realized_pnl or 0 for p in perps)
    symbols = sorted({p.symbol.upper() for p in perps})
    return {"trades_count": len(perps),
            "realized": realized, "traded_symbols": symbols}


def score_card(db: Session, user_id: int, card, workspace: str = "perps") -> dict:
    """Confront a plan card's commitments with the realized perps session outcome."""
    start, end = window_for_card(card)
    base = score_window(db, user_id, start, end, workspace=workspace)
    shortlist = [s.upper() for s in (card.shortlist or [])]
    offlist = [s for s in base["traded_symbols"] if shortlist and s not in shortlist]
    flags = {
        "trades_over": bool(card.max_trades is not None
                            and base["trades_count"] > card.max_trades),
        "loss_breached": bool(card.max_daily_loss is not None
                              and base["realized"] <= -abs(card.max_daily_loss)),
        "offlist": bool(offlist),
    }
    return {
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        **base,
        "max_trades": card.max_trades,
        "max_daily_loss": card.max_daily_loss,
        "offlist_symbols": offlist,
        "flags": flags,
        "adherent": not any(flags.values()),
    }
