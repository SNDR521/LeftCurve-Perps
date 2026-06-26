"""Alarm CRUD. Mounted at /api/alarms. All routes user-scoped."""
from datetime import datetime
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.alarms.models import Alarm
from app.alarms.schemas import AlarmIn, AlarmOut

router = APIRouter(prefix="/alarms", tags=["alarms"])


class AlarmPatch(BaseModel):
    enabled: Optional[bool] = None
    status: Optional[Literal["ACTIVE", "PAUSED", "TRIGGERED", "EXPIRED"]] = None
    message: Optional[str] = None
    expires_at: Optional[datetime] = None


@router.get("")
def list_alarms(status: Optional[str] = None, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    q = db.query(Alarm).filter(Alarm.user_id == user.id)
    if status:
        q = q.filter(Alarm.status == status)
    rows = q.order_by(Alarm.created_at.desc()).all()
    return [AlarmOut.model_validate(a).model_dump(mode="json") for a in rows]


@router.post("")
def create_alarm(body: AlarmIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    a = Alarm(user_id=user.id, **body.model_dump())
    if a.deliver is None:
        a.deliver = {"in_app": True, "telegram": False}
    db.add(a); db.commit(); db.refresh(a)
    return AlarmOut.model_validate(a).model_dump(mode="json")


@router.patch("/{alarm_id}")
def update_alarm(alarm_id: int, body: AlarmPatch, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    a = db.query(Alarm).filter(Alarm.id == alarm_id, Alarm.user_id == user.id).first()
    if not a:
        raise HTTPException(404, "alarm not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(a, k, v)
    if data.get("status") == "ACTIVE":
        a.enabled = True
    db.commit(); db.refresh(a)
    return AlarmOut.model_validate(a).model_dump(mode="json")


@router.delete("/{alarm_id}")
def delete_alarm(alarm_id: int, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    a = db.query(Alarm).filter(Alarm.id == alarm_id, Alarm.user_id == user.id).first()
    if not a:
        raise HTTPException(404, "alarm not found")
    db.delete(a); db.commit()
    return {"ok": True}
