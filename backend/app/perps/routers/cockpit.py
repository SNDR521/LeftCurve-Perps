"""Live cockpit endpoint: single account, or aggregate across all active perps
accounts when no account_id is given."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.models import ExchangeAccount
from app.perps.services.venue_sync import client_for, SUPPORTED_VENUES
from app.perps.services.cockpit import build_cockpit, _account_live, build_cockpit_aggregate

router = APIRouter(prefix="/cockpit", tags=["perps-cockpit"])


@router.get("")
def get_cockpit(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                account_id: int | None = Query(default=None)):
    base = (db.query(ExchangeAccount)
            .filter(ExchangeAccount.user_id == user.id,
                    ExchangeAccount.venue.in_(SUPPORTED_VENUES),
                    ExchangeAccount.is_active.is_(True)))

    if account_id is not None:
        account = base.filter(ExchangeAccount.id == account_id).first()
        if account is None:
            raise HTTPException(status_code=404, detail="No active perps account")
        client = client_for(account)
        try:
            return build_cockpit(db, account, client)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(e))
        finally:
            try:
                client._client.close()
            except Exception:  # noqa: BLE001
                pass

    # All accounts: aggregate live across every active perps account, failure-isolated.
    accounts = base.order_by(ExchangeAccount.id).all()
    if not accounts:
        raise HTTPException(status_code=404, detail="No active perps account")
    live_results, unavailable, errors = [], [], []
    for account in accounts:
        client = client_for(account)
        try:
            live_results.append(_account_live(db, account, client))
        except Exception as e:  # noqa: BLE001 — isolate a flaky venue
            unavailable.append(account.venue.value)
            errors.append(f"{account.venue.value}: {e}")
        finally:
            try:
                client._client.close()
            except Exception:  # noqa: BLE001
                pass
    if not live_results:
        raise HTTPException(status_code=502, detail="; ".join(errors))
    return build_cockpit_aggregate(db, user.id, live_results, unavailable)
