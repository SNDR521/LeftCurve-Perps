"""Live cockpit endpoint: read-only risk/discipline/funding snapshot for the
trader's active perps account (Bybit or Hyperliquid)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.models import ExchangeAccount
from app.perps.services.venue_sync import client_for, SUPPORTED_VENUES
from app.perps.services.cockpit import build_cockpit

router = APIRouter(prefix="/cockpit", tags=["perps-cockpit"])


@router.get("")
def get_cockpit(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                account_id: int | None = Query(default=None)):
    q = (db.query(ExchangeAccount)
         .filter(ExchangeAccount.user_id == user.id,
                 ExchangeAccount.venue.in_(SUPPORTED_VENUES),
                 ExchangeAccount.is_active.is_(True)))
    if account_id is not None:
        q = q.filter(ExchangeAccount.id == account_id)
    account = q.order_by(ExchangeAccount.id).first()
    if account is None:
        raise HTTPException(status_code=404, detail="No active perps account")
    client = client_for(account)
    try:
        return build_cockpit(db, account, client)
    except Exception as e:  # noqa: BLE001 — surface upstream/exchange errors as 502
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        # one client per poll; close the httpx pool so it doesn't leak sockets
        try:
            client._client.close()
        except Exception:  # noqa: BLE001
            pass
