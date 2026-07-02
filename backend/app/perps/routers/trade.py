"""Trade-execution routes (cockpit close). Kept separate from positions.py:
that router serves the journal's derived data; this one talks to exchanges."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.models import User
from app.database import get_db
from app.perps.models import ExchangeAccount
from app.perps.routers.exchange_accounts import _sync_in_background
from app.perps.services import venue_sync, venue_trade

router = APIRouter(prefix="/positions", tags=["perps-trade"])

_STATUS = {"bad_request": 400, "unsupported": 400, "permission": 403,
           "no_position": 409, "qty_too_small": 422,
           "qty_exceeds_position": 422, "venue_rejected": 502}


class CloseIn(BaseModel):
    account_id: int
    symbol: str
    fraction: float | None = None
    qty: float | None = None

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.fraction is None) == (self.qty is None):
            raise ValueError("provide exactly one of fraction or qty")
        return self


def _kick_sync(account_id: int) -> None:
    """Converge the trade log/journal quickly after a close (cockpit reads the
    exchange live anyway). Failure-isolated; skipped when a sync is running."""
    if not venue_sync.is_syncing(account_id):
        threading.Thread(target=_sync_in_background, args=(account_id,), daemon=True).start()


@router.post("/close")
def close_position(payload: CloseIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    acc = (db.query(ExchangeAccount)
           .filter(ExchangeAccount.id == payload.account_id,
                   ExchangeAccount.user_id == user.id).first())
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        result = venue_trade.close_position(db, acc, payload.symbol,
                                            fraction=payload.fraction, qty=payload.qty)
    except venue_trade.CloseError as e:
        raise HTTPException(status_code=_STATUS.get(e.code, 502), detail=e.message)
    _kick_sync(acc.id)
    return result
