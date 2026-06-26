from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.models import ExchangeAccount, Fill
from app.perps.schemas import FillCreate, FillOut
from app.perps.services.recompute import recompute_positions

router = APIRouter(prefix="/fills", tags=["perps-fills"])


def _own_account_or_404(db, user, account_id):
    acc = db.query(ExchangeAccount).filter(
        ExchangeAccount.id == account_id, ExchangeAccount.user_id == user.id).first()
    if acc is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return acc


def _insert_fill(db, user, body: FillCreate, acc) -> Fill:
    fill = Fill(
        user_id=user.id, exchange_account_id=acc.id, venue=acc.venue, symbol=body.symbol,
        asset_class=body.asset_class, side=body.side, price=body.price, quantity=body.quantity,
        fee=body.fee, fee_currency=body.fee_currency, funding_amount=body.funding_amount,
        stop_price=body.stop_price, risk_amount=body.risk_amount, executed_at=body.executed_at,
        order_id=body.order_id, external_fill_id=body.external_fill_id,
    )
    db.add(fill)
    return fill


@router.post("", response_model=FillOut)
def create_fill(body: FillCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    acc = _own_account_or_404(db, user, body.exchange_account_id)
    fill = _insert_fill(db, user, body, acc)
    db.commit(); db.refresh(fill)
    recompute_positions(db, user.id, acc.id, fill.symbol)
    return fill


@router.post("/bulk", response_model=list[FillOut])
def create_fills_bulk(bodies: list[FillCreate], user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    created = []
    affected = set()
    for body in bodies:
        acc = _own_account_or_404(db, user, body.exchange_account_id)
        fill = _insert_fill(db, user, body, acc)
        created.append(fill)
        affected.add((acc.id, body.symbol))
    db.commit()
    for f in created:
        db.refresh(f)
    for account_id, symbol in affected:
        recompute_positions(db, user.id, account_id, symbol)
    return created


@router.get("", response_model=list[FillOut])
def list_fills(user: User = Depends(get_current_user), db: Session = Depends(get_db),
               account_id: int | None = None, symbol: str | None = None):
    q = db.query(Fill).filter(Fill.user_id == user.id)
    if account_id is not None:
        q = q.filter(Fill.exchange_account_id == account_id)
    if symbol is not None:
        q = q.filter(Fill.symbol == symbol)
    return q.order_by(Fill.executed_at, Fill.id).all()


@router.delete("/{fill_id}")
def delete_fill(fill_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    fill = db.query(Fill).filter(Fill.id == fill_id, Fill.user_id == user.id).first()
    if fill is None:
        raise HTTPException(status_code=404, detail="Not found")
    account_id, symbol = fill.exchange_account_id, fill.symbol
    db.delete(fill); db.commit()
    recompute_positions(db, user.id, account_id, symbol)
    return {"ok": True}
