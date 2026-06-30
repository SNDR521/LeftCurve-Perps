from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.models import (
    ExchangeAccount, Position, Fill, PositionStatus, PerpsJournal, PositionFill,
    perps_position_tags,
)
from app.perps.schemas import PositionOut, FillOut
from app.perps.services.risk import compute_risk
from app.perps.routers.journal import _serialize as serialize_journal
from app.perps.services.recompute import recompute_positions
from app.perps.services.venue_sync import is_syncing
from app.perps.services.position_linker import link_account
from app.perps.services.mfe import compute_mfe_mae

router = APIRouter(prefix="/positions", tags=["perps-positions"])


@router.get("", response_model=list[PositionOut])
def list_positions(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                   account_id: int | None = None, symbol: str | None = None,
                   status: PositionStatus | None = None):
    q = db.query(Position).filter(Position.user_id == user.id)
    if account_id is not None:
        q = q.filter(Position.exchange_account_id == account_id)
    if symbol is not None:
        q = q.filter(Position.symbol == symbol)
    if status is not None:
        q = q.filter(Position.status == status)
    return q.order_by(Position.opened_at).all()


@router.post("/relink")
def relink(user: User = Depends(get_current_user), db: Session = Depends(get_db),
           account_id: int | None = Query(default=None)):
    """Manually re-run fill↔position attribution + MFE/MAE for the user's
    accounts (e.g. right after a deploy, without waiting for the scheduler).
    May take ~1 min on a large account (one kline fetch per unprocessed trade)."""
    q = db.query(ExchangeAccount).filter(ExchangeAccount.user_id == user.id)
    if account_id is not None:
        q = q.filter(ExchangeAccount.id == account_id)
    out = {"accounts": 0, "exact": 0, "estimated": 0, "mfe_computed": 0, "skipped_syncing": 0}
    for acc in q.all():
        # A concurrent sync runs the same wipe+rebuild; overlapping would hit
        # the position_fills unique constraint. Skip and let the sync do it.
        if is_syncing(acc.id):
            out["skipped_syncing"] += 1
            continue
        res = link_account(db, acc)
        out["accounts"] += 1
        out["exact"] += res["exact"]
        out["estimated"] += res["estimated"]
        out["mfe_computed"] += compute_mfe_mae(db, acc)
    return out


def _build_detail(db: Session, user: User, pos: Position) -> dict:
    """Build the full detail payload for an already-resolved Position row."""
    journal = None
    if pos.position_key:
        journal = db.query(PerpsJournal).filter(
            PerpsJournal.user_id == user.id,
            PerpsJournal.position_key == pos.position_key).first()
    fills = (db.query(Fill).join(PositionFill, PositionFill.fill_id == Fill.id)
             .filter(PositionFill.position_id == pos.id)
             .order_by(Fill.executed_at.asc(), Fill.id.asc()).all())
    journal_out = serialize_journal(db, user, journal) if journal else None
    if journal_out is None and pos.position_key:
        # Tags can exist without a journal row (mirror GET /journal's fallback)
        # so the detail page never hides linked tags.
        tag_ids = [r.tag_id for r in db.execute(
            perps_position_tags.select().where(
                (perps_position_tags.c.user_id == user.id) &
                (perps_position_tags.c.position_key == pos.position_key))
        ).all()]
        if tag_ids:
            journal_out = {"position_key": pos.position_key, "tag_ids": tag_ids}
    return {
        "position": PositionOut.model_validate(pos).model_dump(mode="json"),
        "journal": journal_out,
        "fills": [{**FillOut.model_validate(f).model_dump(mode="json"),
                   "is_funding": bool((f.quantity or 0) <= 1e-9 and f.funding_amount)}
                  for f in fills],
        "risk": compute_risk(pos, journal),
    }


@router.get("/detail")
def position_detail_by_key(key: str, user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    """Stable key-based trade-detail lookup.

    Survives the id churn that occurs when sync rebuilds positions with
    delete-then-reinsert: position_key is stable across reinserts, numeric
    Position.id is not.
    """
    pos = db.query(Position).filter(Position.position_key == key,
                                    Position.user_id == user.id).first()
    if pos is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _build_detail(db, user, pos)


@router.get("/{position_id}/detail")
def position_detail(position_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Everything the trade-detail page needs in one call (id-based, kept for
    backward compatibility — prefer the key-based /detail endpoint)."""
    pos = db.query(Position).filter(Position.id == position_id,
                                    Position.user_id == user.id).first()
    if pos is None:
        raise HTTPException(status_code=404, detail="Not found")
    return _build_detail(db, user, pos)


@router.get("/{position_id}", response_model=PositionOut)
def get_position(position_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    pos = db.query(Position).filter(Position.id == position_id, Position.user_id == user.id).first()
    if pos is None:
        raise HTTPException(status_code=404, detail="Not found")
    return pos


@router.post("/recompute")
def force_recompute(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                    account_id: int | None = None, symbol: str | None = None):
    q = db.query(Fill.exchange_account_id, Fill.symbol).filter(Fill.user_id == user.id)
    if account_id is not None:
        q = q.filter(Fill.exchange_account_id == account_id)
    if symbol is not None:
        q = q.filter(Fill.symbol == symbol)
    scopes = {(aid, sym) for aid, sym in q.distinct().all()}
    for aid, sym in scopes:
        recompute_positions(db, user.id, aid, sym)
    return {"ok": True, "scopes": len(scopes)}
