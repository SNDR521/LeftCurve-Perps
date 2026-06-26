"""Alerts inbox endpoints.

GET  /alerts           — paginated alert list + unseen count
POST /alerts/seen      — mark alerts seen (by ids or all)
GET  /alerts/check     — near-live crypto level check (polled ~60s)
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.workflow.models import Alert
from app.workflow.schemas import AlertOut

log = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["workflow-alerts"])


class SeenBody(BaseModel):
    ids: Optional[list[int]] = None
    all: Optional[bool] = None


@router.get("")
def list_alerts(
    limit: int = Query(default=20, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's alerts (newest first) plus unseen_count.

    Response envelope: ``{alerts: [AlertOut, ...], unseen_count: int}``
    """
    alerts = (
        db.query(Alert)
        .filter(Alert.user_id == user.id)
        .order_by(Alert.triggered_at.desc(), Alert.id.desc())
        .limit(limit)
        .all()
    )
    unseen_count = (
        db.query(Alert)
        .filter(Alert.user_id == user.id, Alert.seen.is_(False))
        .count()
    )
    return {
        "alerts": [AlertOut.model_validate(a).model_dump() for a in alerts],
        "unseen_count": unseen_count,
    }


@router.post("/seen")
def mark_alerts_seen(
    body: SeenBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark alerts seen.

    Body: ``{ids: [int, ...]}`` — mark specific ids (user-scoped)
          ``{all: true}``      — mark all user's alerts seen

    Returns: ``{unseen_count: int}`` after the operation.
    """
    q = db.query(Alert).filter(Alert.user_id == user.id, Alert.seen.is_(False))

    if body.all:
        q.update({"seen": True}, synchronize_session=False)
    elif body.ids:
        q.filter(Alert.id.in_(body.ids)).update({"seen": True}, synchronize_session=False)

    db.commit()

    unseen_count = (
        db.query(Alert)
        .filter(Alert.user_id == user.id, Alert.seen.is_(False))
        .count()
    )
    return {"unseen_count": unseen_count}


@router.get("/check")
def check(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Polled by the UI (~60s). Must never 5xx — a failed exchange fetch
    just means no new alerts this round."""
    from app.workflow.services.alerts import check_crypto_levels
    try:
        created = check_crypto_levels(db, user.id)
    except Exception:  # noqa: BLE001
        log.exception("crypto level check failed")
        created = []
    unseen = db.query(Alert).filter(Alert.user_id == user.id, Alert.seen.is_(False)).count()
    return {"unseen_count": unseen, "new": [AlertOut.model_validate(a).model_dump(mode="json") for a in created]}
