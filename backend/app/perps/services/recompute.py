from sqlalchemy.orm import Session

from app.perps.models import AssetClass, Fill, Position, Direction, PositionStatus, OpenedAtSource
from app.perps.services.position_builder import build_positions, FillInput


def recompute_positions(db: Session, user_id: int, exchange_account_id: int, symbol: str) -> None:
    """Rebuild persisted positions for one (user, account, symbol) scope from its fills."""
    fills = (
        db.query(Fill)
        .filter(Fill.user_id == user_id,
                Fill.exchange_account_id == exchange_account_id,
                Fill.symbol == symbol)
        .order_by(Fill.executed_at, Fill.id)
        .all()
    )
    inputs = [
        FillInput(
            side=f.side.value, price=f.price, quantity=f.quantity, executed_at=f.executed_at,
            fee=f.fee or 0.0, funding_amount=f.funding_amount,
            stop_price=f.stop_price, risk_amount=f.risk_amount, asset_class=f.asset_class.value,
        )
        for f in fills
    ]
    results = build_positions(inputs)

    db.query(Position).filter(
        Position.user_id == user_id,
        Position.exchange_account_id == exchange_account_id,
        Position.symbol == symbol,
    ).delete(synchronize_session=False)

    for r in results:
        db.add(Position(
            user_id=user_id, exchange_account_id=exchange_account_id, symbol=symbol,
            asset_class=AssetClass(r.asset_class), direction=Direction(r.direction),
            status=PositionStatus(r.status), opened_at=r.opened_at, closed_at=r.closed_at,
            avg_entry=r.avg_entry, avg_exit=r.avg_exit, quantity=r.quantity,
            realized_pnl=r.realized_pnl, total_fees=r.total_fees, total_funding=r.total_funding,
            r_multiple=r.r_multiple, duration_seconds=r.duration_seconds,
            position_key=f"{exchange_account_id}:{symbol}:{r.opened_at.isoformat()}",
            opened_at_source=OpenedAtSource.EXACT,
        ))
    db.commit()
