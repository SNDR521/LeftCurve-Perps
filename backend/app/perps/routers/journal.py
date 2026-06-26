import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.models import Position, PerpsJournal, PerpsTag, perps_position_tags
from app.perps.schemas import PerpsJournalIn, PerpsTagIn, PerpsTagOut, TagLink

router = APIRouter(prefix="/journal", tags=["perps-journal"])

_FIELDS = ["setup_name", "notes", "emotion_before", "emotion_after", "rating",
           "mistakes", "lessons", "grade", "mistake_tags", "followed_plan", "was_overtrading",
           "stop_price", "stop_triggered", "targets", "screenshot_path"]


def _own_position_or_404(db, user, position_key):
    pos = db.query(Position).filter(Position.user_id == user.id, Position.position_key == position_key).first()
    if pos is None:
        # Open-position keys ({account_id}:{symbol}:open) may precede their
        # snapshot row: the cockpit shows a freshly opened position live from
        # Bybit before the next sync writes the Position row. A stop set in
        # that window must not 404 — ownership is provable via the account.
        if position_key.endswith(":open"):
            from app.perps.models import ExchangeAccount
            acct_part = position_key.split(":", 1)[0]
            if acct_part.isdigit():
                acct = db.query(ExchangeAccount).filter(
                    ExchangeAccount.id == int(acct_part),
                    ExchangeAccount.user_id == user.id).first()
                if acct is not None:
                    return None
        raise HTTPException(status_code=404, detail="Position not found")
    return pos


def _serialize(db, user, j: PerpsJournal) -> dict:
    tag_ids = [r.tag_id for r in db.execute(
        perps_position_tags.select().where(
            (perps_position_tags.c.user_id == user.id) & (perps_position_tags.c.position_key == j.position_key))
    ).all()]
    out = {f: getattr(j, f) for f in _FIELDS}
    out.update({"id": j.id, "position_key": j.position_key, "tag_ids": tag_ids})
    return out


@router.get("")
def get_journal(position_key: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    j = db.query(PerpsJournal).filter(PerpsJournal.user_id == user.id,
                                      PerpsJournal.position_key == position_key).first()
    if j:
        return _serialize(db, user, j)
    # No journal entry yet — return tag_ids if any exist, else None
    tag_ids = [r.tag_id for r in db.execute(
        perps_position_tags.select().where(
            (perps_position_tags.c.user_id == user.id) &
            (perps_position_tags.c.position_key == position_key))
    ).all()]
    if tag_ids:
        return {"position_key": position_key, "tag_ids": tag_ids}
    return None


@router.put("")
def upsert_journal(body: PerpsJournalIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _own_position_or_404(db, user, body.position_key)
    j = db.query(PerpsJournal).filter(PerpsJournal.user_id == user.id,
                                      PerpsJournal.position_key == body.position_key).first()
    data = body.model_dump(exclude_unset=True, exclude={"position_key"})
    if j is None:
        j = PerpsJournal(user_id=user.id, position_key=body.position_key, **data)
        db.add(j)
    else:
        for k, v in data.items():
            setattr(j, k, v)
    db.commit(); db.refresh(j)
    return _serialize(db, user, j)


SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(exist_ok=True)


@router.get("/bulk")
def journal_bulk(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """{position_key: {setup_name, grade}} for the user's journals — feeds
    trade-log badges without bloating the positions response."""
    rows = db.query(PerpsJournal).filter(PerpsJournal.user_id == user.id).all()
    return {j.position_key: {"setup_name": j.setup_name, "grade": j.grade} for j in rows}


@router.post("/screenshot")
def upload_screenshot(position_key: str, file: UploadFile = File(...),
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _own_position_or_404(db, user, position_key)
    j = db.query(PerpsJournal).filter(PerpsJournal.user_id == user.id,
                                      PerpsJournal.position_key == position_key).first()
    if j is None:
        j = PerpsJournal(user_id=user.id, position_key=position_key)
        db.add(j); db.commit(); db.refresh(j)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", file.filename or "shot.png")
    dest = SCREENSHOTS_DIR / f"perps_{j.id}_{safe}"
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    j.screenshot_path = str(dest)
    db.commit()
    return {"path": str(dest)}


@router.get("/tags", response_model=list[PerpsTagOut])
def list_tags(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(PerpsTag).filter(PerpsTag.user_id == user.id).order_by(PerpsTag.name).all()


@router.post("/tags", response_model=PerpsTagOut)
def create_tag(body: PerpsTagIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tag = PerpsTag(user_id=user.id, name=body.name, color=body.color)
    db.add(tag); db.commit(); db.refresh(tag)
    return tag


@router.post("/tag-link")
def link_tag(body: TagLink, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _own_position_or_404(db, user, body.position_key)
    tag = db.query(PerpsTag).filter(PerpsTag.id == body.tag_id, PerpsTag.user_id == user.id).first()
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    exists = db.execute(perps_position_tags.select().where(
        (perps_position_tags.c.user_id == user.id) &
        (perps_position_tags.c.position_key == body.position_key) &
        (perps_position_tags.c.tag_id == body.tag_id))).first()
    if not exists:
        db.execute(perps_position_tags.insert().values(
            user_id=user.id, position_key=body.position_key, tag_id=body.tag_id))
        db.commit()
    return {"ok": True}


@router.post("/tag-unlink")
def unlink_tag(body: TagLink, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(perps_position_tags.delete().where(
        (perps_position_tags.c.user_id == user.id) &
        (perps_position_tags.c.position_key == body.position_key) &
        (perps_position_tags.c.tag_id == body.tag_id)))
    db.commit()
    return {"ok": True}
