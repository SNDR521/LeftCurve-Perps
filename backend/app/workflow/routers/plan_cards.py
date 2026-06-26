"""Daily plan-card endpoints.

Plan cards capture the morning commitment (shortlist, max trades, max loss) and
evening reflection for each session. The ``regime_snapshot`` column is left
nullable and unused after removing the market-board dependency; a later migration
will drop it.
"""
from __future__ import annotations

from datetime import date as _date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.workflow.models import PlanCard
from app.workflow.schemas import PlanCardIn, PlanCardOut
from app.workflow.services.scoring import score_card


def snapshot_regime():
    """Stub — regime snapshots are no longer populated. Returns None."""
    return None


router = APIRouter(prefix="/plan-cards", tags=["workflow-plan-cards"])


def _parse_date(value: str) -> _date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=422,
                            detail="date must be YYYY-MM-DD")


@router.put("/{date}", response_model=PlanCardOut)
def upsert_plan_card(date: str, body: PlanCardIn,
                     user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    card_date = _parse_date(date)
    card = (db.query(PlanCard)
            .filter(PlanCard.user_id == user.id, PlanCard.date == card_date)
            .first())
    data = body.model_dump(exclude_unset=True)
    if card is None:
        # regime_snapshot is no longer populated (stub returns None).
        snap = snapshot_regime()
        card = PlanCard(user_id=user.id, date=card_date, regime_snapshot=snap, **data)
        db.add(card)
    else:
        # Partial update — only sent fields change; regime_snapshot is frozen.
        for k, v in data.items():
            setattr(card, k, v)
    db.commit(); db.refresh(card)
    return card


@router.get("/{date}", response_model=PlanCardOut)
def get_plan_card(date: str,
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    card_date = _parse_date(date)
    card = (db.query(PlanCard)
            .filter(PlanCard.user_id == user.id, PlanCard.date == card_date)
            .first())
    if card is None:
        raise HTTPException(status_code=404, detail="Plan card not found")
    return card


@router.get("")
def list_plan_cards(from_: str | None = Query(default=None, alias="from"),
                    to: str | None = Query(default=None, alias="to"),
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    q = db.query(PlanCard).filter(PlanCard.user_id == user.id)
    if from_:
        q = q.filter(PlanCard.date >= _parse_date(from_))
    if to:
        q = q.filter(PlanCard.date <= _parse_date(to))
    cards = q.order_by(PlanCard.date).all()
    out = []
    for card in cards:
        score = score_card(db, user.id, card)
        out.append({
            "date": card.date.isoformat(),
            "adherent": score["adherent"],
            "trades_count": score["trades_count"],
        })
    return out


@router.get("/{date}/score")
def get_plan_card_score(date: str,
                        workspace: str = Query(default="all"),
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    # Perps-only: ``workspace`` is accepted for API compatibility but the score
    # always reflects perps data.
    if workspace not in ("all", "perps", "prop"):
        raise HTTPException(status_code=422, detail="workspace must be all|perps|prop")
    card_date = _parse_date(date)
    card = (db.query(PlanCard)
            .filter(PlanCard.user_id == user.id, PlanCard.date == card_date)
            .first())
    if card is None:
        raise HTTPException(status_code=404, detail="Plan card not found")
    return score_card(db, user.id, card, workspace="perps")
