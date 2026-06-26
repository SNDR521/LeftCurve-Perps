"""Review-draft and saved-review endpoints — the self-writing weekly/monthly review.

The DRAFT (`GET /reviews/draft`) is computed live for a WEEK or MONTH window: it
pulls the perps overview stats, worst perps positions, a per-day adherence
breakdown (days that had a plan card with commitments AND trades), and a count of
days that traded without a plan.  The ``workspace`` query param is accepted for
API compatibility but only 'perps' data is returned.

The SAVED review (`GET`/`PUT /reviews`) holds the user's three written judgments,
upserted by `(user, period_type, period_start, workspace)`.
"""
from __future__ import annotations

from datetime import date as _date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.workflow.models import PlanCard, Review
from app.workflow.schemas import ReviewIn, ReviewOut
from app.workflow.services.scoring import score_card, score_window

from app.perps.models import Position as PerpsPosition, PositionStatus, PerpsJournal
from app.perps.services.analytics import compute_overview as perps_overview
from app.core.streaks import max_streaks

router = APIRouter(prefix="/reviews", tags=["workflow-reviews"])


# ── period helpers ────────────────────────────────────────────────────────────

def _parse_date(value: str) -> _date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="start must be YYYY-MM-DD")


def _period_end(period_type: str, start: _date) -> _date:
    """End of the [start, end) period.

    WEEK  → start + 7 days.
    MONTH → first day of the following calendar month (rolls the year in Dec).

    ``start`` is accepted as-is — it is NOT validated to be a Monday (WEEK) or
    the 1st (MONTH); callers conventionally pass the period's first day.
    """
    if period_type == "WEEK":
        return start + timedelta(days=7)
    if start.month == 12:
        return _date(start.year + 1, 1, 1)
    return _date(start.year, start.month + 1, 1)


def _overview_keys(metrics) -> dict:
    """Project a perps OverviewMetrics to the three shared keys."""
    return {
        "total_trades": metrics.total_trades,
        "total_pnl": metrics.total_pnl,
        "win_rate": metrics.win_rate,
    }


# ── all trades ───────────────────────────────────────────────────────────────

def _period_trades(db: Session, user_id: int, start_dt: datetime,
                   end_dt: datetime) -> list[dict]:
    """ALL closed perps positions in the window, sorted by pnl ascending (worst first).

    Attaches ``setup`` from PerpsJournal and ``date`` as an ISO date string.
    """
    positions = (db.query(PerpsPosition)
                 .filter(PerpsPosition.user_id == user_id,
                         PerpsPosition.status == PositionStatus.CLOSED,
                         PerpsPosition.closed_at >= start_dt,
                         PerpsPosition.closed_at < end_dt).all())
    keys = [p.position_key for p in positions if p.position_key]
    jmap: dict = {}
    if keys:
        rows = db.query(PerpsJournal).filter(
            PerpsJournal.user_id == user_id,
            PerpsJournal.position_key.in_(keys)).all()
        jmap = {j.position_key: j for j in rows}

    result: list[dict] = []
    for p in positions:
        j = jmap.get(p.position_key) if p.position_key else None
        result.append({
            "id": p.id,
            "symbol": (p.symbol or "").upper(),
            "pnl": p.realized_pnl or 0.0,
            "r": p.r_multiple,
            "date": p.closed_at.date().isoformat() if p.closed_at else None,
            "setup": (j.setup_name if j else None),
        })
    result.sort(key=lambda x: x["pnl"])  # worst (most negative) first
    return result


# ── bright spots (positive inverse of demon finder) ───────────────────────────

def compute_bright_spots(db, user_id: int, start_dt: datetime,
                         end_dt: datetime) -> dict:
    """Aggregate net realized_pnl by symbol and by setup over the period.

    Returns the single highest net-positive group per dimension.  Groups that
    are net-negative (or zero) are excluded — ``None`` is returned for a
    dimension when no group is net-positive.  ``best_setup`` ignores positions
    that carry no setup.
    """
    positions = (db.query(PerpsPosition)
                 .filter(PerpsPosition.user_id == user_id,
                         PerpsPosition.status == PositionStatus.CLOSED,
                         PerpsPosition.closed_at >= start_dt,
                         PerpsPosition.closed_at < end_dt).all())
    keys = [p.position_key for p in positions if p.position_key]
    jmap: dict = {}
    if keys:
        rows = db.query(PerpsJournal).filter(
            PerpsJournal.user_id == user_id,
            PerpsJournal.position_key.in_(keys)).all()
        jmap = {j.position_key: j for j in rows}

    sym_agg: dict = {}   # symbol -> [pnl_sum, count]
    setup_agg: dict = {}  # setup_name -> [pnl_sum, count]
    for p in positions:
        pnl = p.realized_pnl or 0.0
        sym = (p.symbol or "").upper()
        s = sym_agg.setdefault(sym, [0.0, 0])
        s[0] += pnl
        s[1] += 1

        j = jmap.get(p.position_key) if p.position_key else None
        setup = j.setup_name if j and j.setup_name else None
        if setup:
            t = setup_agg.setdefault(setup, [0.0, 0])
            t[0] += pnl
            t[1] += 1

    def _best(agg: dict):
        positives = [(name, vals) for name, vals in agg.items() if vals[0] > 0]
        if not positives:
            return None
        name, vals = max(positives, key=lambda x: x[1][0])
        return {"name": name, "pnl": round(vals[0], 2), "count": vals[1]}

    return {
        "best_symbol": _best(sym_agg),
        "best_setup": _best(setup_agg),
    }


# ── demons (recurring mistakes) ───────────────────────────────────────────────

def _demon_rows_perps(db, user_id, start_dt, end_dt):
    positions = (db.query(PerpsPosition)
                 .filter(PerpsPosition.user_id == user_id,
                         PerpsPosition.status == PositionStatus.CLOSED,
                         PerpsPosition.closed_at >= start_dt,
                         PerpsPosition.closed_at < end_dt)
                 .order_by(PerpsPosition.closed_at.asc(), PerpsPosition.id.asc()).all())
    keys = [p.position_key for p in positions if p.position_key]
    jmap = {}
    if keys:
        rows = db.query(PerpsJournal).filter(
            PerpsJournal.user_id == user_id,
            PerpsJournal.position_key.in_(keys)).all()
        jmap = {j.position_key: j for j in rows}

    def tags(p):
        j = jmap.get(p.position_key)
        return (j.mistake_tags if j and j.mistake_tags else []) or []

    return [(tags(p), p.realized_pnl or 0.0) for p in positions]


def compute_demons(db, user_id, start_dt, end_dt, workspace) -> dict:
    """Rank recurring mistake tags for the perps workspace over the period, with the
    longest consecutive run per demon and an alarm tier (warn >=3, stop >=10).

    ``workspace`` is accepted for API compatibility but only perps data is used."""
    rows = _demon_rows_perps(db, user_id, start_dt, end_dt)
    streaks = max_streaks([tags for tags, _ in rows])
    agg: dict = {}  # demon -> [count, pnl]
    for tags, pnl in rows:
        for d in set(tags):
            a = agg.setdefault(d, [0, 0.0])
            a[0] += 1
            a[1] += pnl
    ranked = sorted(
        ({"demon": d, "count": c, "total_pnl": round(p, 2),
          "max_streak": streaks.get(d, 0)} for d, (c, p) in agg.items()),
        key=lambda r: (-r["count"], r["total_pnl"]))
    max_run = max((r["max_streak"] for r in ranked), default=0)
    alarm = "stop" if max_run >= 10 else ("warn" if max_run >= 3 else None)
    return {"ranked": ranked, "top": (ranked[0] if ranked else None), "alarm": alarm}


# ── draft ─────────────────────────────────────────────────────────────────────

@router.get("/draft")
def review_draft(type: str = Query(...),
                 start: str = Query(...),
                 workspace: str = Query("perps"),
                 user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    period_type = (type or "").upper()
    if period_type not in ("WEEK", "MONTH"):
        raise HTTPException(status_code=422, detail="type must be WEEK or MONTH")
    ws = (workspace or "").lower()
    if ws not in ("prop", "perps"):
        raise HTTPException(status_code=422, detail="workspace must be prop or perps")
    # Perps-only: ignore the requested workspace and always report perps so the
    # response never claims to be prop data while returning perps figures.
    ws = "perps"
    start_date = _parse_date(start)
    end_date = _period_end(period_type, start_date)

    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.min)
    from_s = start_date.isoformat()
    # Inclusive 'to' bound for the overview services (they treat to_date as <=).
    to_s = (end_date - timedelta(days=1)).isoformat()

    stats = _overview_keys(
        perps_overview(db, {"from_date": from_s, "to_date": to_s}, user_id=user.id))

    # ── adherence: one row per plan card in the period ──
    cards = (db.query(PlanCard)
             .filter(PlanCard.user_id == user.id,
                     PlanCard.date >= start_date,
                     PlanCard.date < end_date)
             .order_by(PlanCard.date).all())

    def _has_commitments(card) -> bool:
        return (card.max_trades is not None
                or card.max_daily_loss is not None
                or bool(card.shortlist))

    per_day = []
    days_evaluated = 0
    adherent_days = 0
    for card in cards:
        score = score_card(db, user.id, card, workspace=ws)
        trades_count = score["trades_count"]
        if not _has_commitments(card) or trades_count == 0:
            adherent = None  # excluded from the rate
        else:
            adherent = score["adherent"]
            days_evaluated += 1
            if adherent:
                adherent_days += 1
        per_day.append({
            "date": card.date.isoformat(),
            "adherent": adherent,
            "trades_count": trades_count,
        })

    rate_pct = (round(adherent_days / days_evaluated * 100, 2)
                if days_evaluated else None)

    # ── days that traded without a plan card ──
    card_dates = {c.date for c in cards}
    days_without_card = 0
    d = start_date
    while d < end_date:
        if d not in card_dates:
            day_start = datetime.combine(d, time.min)
            day_score = score_window(db, user.id, day_start,
                                     day_start + timedelta(days=1), workspace=ws)
            if day_score["trades_count"] > 0:
                days_without_card += 1
        d += timedelta(days=1)

    return {
        "period": {"type": period_type,
                   "start": start_date.isoformat(),
                   "end": end_date.isoformat()},
        "workspace": ws,
        "stats": stats,
        "adherence": {
            "days_with_cards": len(cards),
            "days_evaluated": days_evaluated,
            "adherent_days": adherent_days,
            "rate_pct": rate_pct,
            "per_day": per_day,
        },
        "trades": _period_trades(db, user.id, start_dt, end_dt),
        "bright_spots": compute_bright_spots(db, user.id, start_dt, end_dt),
        "days_without_card": days_without_card,
        "demons": compute_demons(db, user.id, start_dt, end_dt, ws),
    }


# ── saved review ──────────────────────────────────────────────────────────────

@router.get("", response_model=ReviewOut)
def get_review(type: str = Query(...),
               start: str = Query(...),
               workspace: str = Query("perps"),
               user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    period_type = (type or "").upper()
    if period_type not in ("WEEK", "MONTH"):
        raise HTTPException(status_code=422, detail="type must be WEEK or MONTH")
    ws = (workspace or "").lower()
    if ws not in ("prop", "perps"):
        raise HTTPException(status_code=422, detail="workspace must be prop or perps")
    start_date = _parse_date(start)
    review = (db.query(Review)
              .filter(Review.user_id == user.id,
                      Review.period_type == period_type,
                      Review.period_start == start_date,
                      Review.workspace == ws)
              .first())
    if review is not None:
        return review
    # Skeleton (200) when no review is saved yet.
    return ReviewOut(period_type=period_type, period_start=start_date, workspace=ws)


@router.put("", response_model=ReviewOut)
def upsert_review(body: ReviewIn,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    review = (db.query(Review)
              .filter(Review.user_id == user.id,
                      Review.period_type == body.period_type,
                      Review.period_start == body.period_start,
                      Review.workspace == body.workspace)
              .first())
    if review is None:
        review = Review(user_id=user.id,
                        period_type=body.period_type,
                        period_start=body.period_start,
                        workspace=body.workspace)
        db.add(review)
    review.what_worked = body.what_worked
    review.what_didnt = body.what_didnt
    review.next_focus = body.next_focus
    review.probe_flags = body.probe_flags
    review.problem = body.problem
    review.why = body.why
    db.commit(); db.refresh(review)
    return review
