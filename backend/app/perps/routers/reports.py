from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.services import analytics as svc
from app.perps.services.costs import compute_equity

router = APIRouter(prefix="/reports", tags=["perps-reports"])


@router.get("/drawdown")
def drawdown(user: User = Depends(get_current_user), db: Session = Depends(get_db),
             account_id: int | None = None, symbol: str | None = None,
             from_date: str | None = None, to_date: str | None = None,
             exclude_breakeven: bool = False, breakeven_threshold: float | None = None):
    f = {}
    if account_id is not None: f["account_id"] = account_id
    if symbol: f["symbol"] = symbol
    if from_date: f["from_date"] = from_date
    if to_date: f["to_date"] = to_date
    if exclude_breakeven:
        f["exclude_breakeven"] = True
        if breakeven_threshold is not None:
            f["breakeven_threshold"] = breakeven_threshold
    daily = svc.compute_daily_pnl(db, f, user.id)
    peak = 0.0; out = []
    for d in daily:
        peak = max(peak, d.cumulative_pnl)
        out.append({"date": d.date, "equity": d.cumulative_pnl, "drawdown": d.cumulative_pnl - peak})
    return out


@router.get("/equity")
def equity(user: User = Depends(get_current_user), db: Session = Depends(get_db),
           account_id: int | None = None):
    return compute_equity(db, account_id, user.id)
