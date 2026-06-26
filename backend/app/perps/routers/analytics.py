from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.services import analytics as svc
from app.perps.services import costs as cost_svc
from app.perps.services import cross_analysis as cross_svc

router = APIRouter(prefix="/analytics", tags=["perps-analytics"])


def _filters(account_id, symbol, from_date, to_date):
    f = {}
    if account_id is not None: f["account_id"] = account_id
    if symbol: f["symbol"] = symbol
    if from_date: f["from_date"] = from_date
    if to_date: f["to_date"] = to_date
    return f


@router.get("/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db),
             account_id: int | None = None, symbol: str | None = None,
             from_date: str | None = None, to_date: str | None = None):
    return svc.compute_overview(db, _filters(account_id, symbol, from_date, to_date), user.id)


@router.get("/daily-pnl")
def daily_pnl(user: User = Depends(get_current_user), db: Session = Depends(get_db),
              account_id: int | None = None, symbol: str | None = None,
              from_date: str | None = None, to_date: str | None = None):
    return svc.compute_daily_pnl(db, _filters(account_id, symbol, from_date, to_date), user.id)


@router.get("/heatmap")
def heatmap(user: User = Depends(get_current_user), db: Session = Depends(get_db),
            account_id: int | None = None, symbol: str | None = None,
            from_date: str | None = None, to_date: str | None = None):
    return svc.compute_heatmap(db, _filters(account_id, symbol, from_date, to_date), user.id)


@router.get("/r-distribution")
def r_distribution(user: User = Depends(get_current_user), db: Session = Depends(get_db),
                   account_id: int | None = None, symbol: str | None = None,
                   from_date: str | None = None, to_date: str | None = None,
                   mode: str = "stored"):
    return svc.compute_r_distribution(db, _filters(account_id, symbol, from_date, to_date), user.id, mode=mode)


@router.get("/coverage")
def coverage(user: User = Depends(get_current_user), db: Session = Depends(get_db),
             account_id: int | None = None, symbol: str | None = None,
             from_date: str | None = None, to_date: str | None = None):
    return svc.compute_coverage(db, _filters(account_id, symbol, from_date, to_date), user.id)


@router.get("/funding")
def funding(user: User = Depends(get_current_user), db: Session = Depends(get_db),
            account_id: int | None = None,
            from_date: str | None = None, to_date: str | None = None):
    return cost_svc.compute_funding(db, account_id, user.id, from_date=from_date, to_date=to_date)


@router.get("/fees")
def fees(user: User = Depends(get_current_user), db: Session = Depends(get_db),
         account_id: int | None = None,
         from_date: str | None = None, to_date: str | None = None):
    return cost_svc.compute_fees(db, account_id, user.id, from_date=from_date, to_date=to_date)


@router.get("/leverage")
def leverage(user: User = Depends(get_current_user), db: Session = Depends(get_db),
             account_id: int | None = None,
             from_date: str | None = None, to_date: str | None = None):
    return cost_svc.compute_leverage(db, account_id, user.id, from_date=from_date, to_date=to_date)


@router.get("/dimensions")
def dimensions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [{"key": k, "label": v} for k, v in cross_svc.DIMENSIONS.items()]


@router.get("/cross")
def cross(primary: str, secondary: str | None = None,
          user: User = Depends(get_current_user), db: Session = Depends(get_db),
          account_id: int | None = None, symbol: str | None = None,
          from_date: str | None = None, to_date: str | None = None):
    return cross_svc.cross_analysis(
        db, primary, secondary, _filters(account_id, symbol, from_date, to_date), user.id)


@router.get("/insights")
def insights(user: User = Depends(get_current_user), db: Session = Depends(get_db),
             account_id: int | None = None,
             from_date: str | None = None, to_date: str | None = None):
    return cross_svc.compute_insights(
        db, _filters(account_id, None, from_date, to_date), user.id)


@router.get("/by-{group_by}")
def by_group(group_by: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
             account_id: int | None = None, symbol: str | None = None,
             from_date: str | None = None, to_date: str | None = None):
    f = _filters(account_id, symbol, from_date, to_date)
    if group_by == "session": return svc.compute_by_session(db, f, user.id)
    if group_by == "holdtime": return svc.compute_by_holdtime(db, f, user.id)
    return svc.compute_performance_by_group(db, group_by, f, user.id)
