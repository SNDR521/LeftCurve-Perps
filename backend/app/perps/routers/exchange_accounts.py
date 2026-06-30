import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db, make_engine
from app.core.deps import get_current_user
from app.core.models import User
from app.core.security import encrypt_credentials
from app.perps.models import ExchangeAccount, Fill, Position, Venue
from app.perps.schemas import ExchangeAccountCreate, ExchangeAccountOut
from app.perps.services import venue_sync
from app.config import get_settings

router = APIRouter(prefix="/accounts", tags=["perps-accounts"])


def _to_out(acc: ExchangeAccount) -> ExchangeAccountOut:
    return ExchangeAccountOut(
        id=acc.id, venue=acc.venue, label=acc.label, is_active=acc.is_active,
        created_at=acc.created_at, has_credentials=bool(acc.encrypted_credentials),
        last_synced_at=acc.last_synced_at, last_sync_error=acc.last_sync_error,
        syncing=venue_sync.is_syncing(acc.id),
        sync_progress=acc.sync_progress,
    )


@router.get("", response_model=list[ExchangeAccountOut])
def list_accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    accs = db.query(ExchangeAccount).filter(ExchangeAccount.user_id == user.id).order_by(ExchangeAccount.id).all()
    return [_to_out(a) for a in accs]


@router.post("", response_model=ExchangeAccountOut)
def create_account(body: ExchangeAccountCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = ExchangeAccount(user_id=user.id, venue=body.venue, label=body.label)
    if body.venue in (Venue.HYPERLIQUID, Venue.RISEX):
        if not body.address:
            raise HTTPException(status_code=422,
                                detail=f"{body.venue.value} account needs a wallet address")
        acc.encrypted_credentials = encrypt_credentials({"address": body.address})
    elif body.api_key and body.api_secret:
        acc.encrypted_credentials = encrypt_credentials(
            {"api_key": body.api_key, "api_secret": body.api_secret})
    db.add(acc); db.commit(); db.refresh(acc)
    return _to_out(acc)


@router.delete("/{account_id}")
def delete_account(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = db.query(ExchangeAccount).filter(
        ExchangeAccount.id == account_id, ExchangeAccount.user_id == user.id).first()
    if acc is None:
        raise HTTPException(status_code=404, detail="Not found")
    db.query(Position).filter(
        Position.user_id == user.id, Position.exchange_account_id == account_id
    ).delete(synchronize_session=False)
    db.query(Fill).filter(
        Fill.user_id == user.id, Fill.exchange_account_id == account_id
    ).delete(synchronize_session=False)
    db.delete(acc)
    db.commit()
    return {"ok": True}


def _sync_in_background(account_id: int):
    # Own DB session for the worker thread.
    engine = make_engine(get_settings().database_url)
    db = Session(engine)
    try:
        acc = db.query(ExchangeAccount).get(account_id)
        if acc:
            venue_sync.sync_account(db, acc)
    finally:
        db.close()


@router.post("/{account_id}/sync")
def sync_account(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = db.query(ExchangeAccount).filter(
        ExchangeAccount.id == account_id, ExchangeAccount.user_id == user.id).first()
    if acc is None:
        raise HTTPException(status_code=404, detail="Not found")
    if acc.venue not in venue_sync.SUPPORTED_VENUES or not acc.encrypted_credentials:
        raise HTTPException(status_code=400, detail="Account needs exchange credentials")
    if venue_sync.is_syncing(acc.id):
        return JSONResponse({"started": False, "reason": "already running"}, status_code=409)
    threading.Thread(target=_sync_in_background, args=(acc.id,), daemon=True).start()
    return JSONResponse({"started": True}, status_code=202)
