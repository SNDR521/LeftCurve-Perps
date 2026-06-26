from datetime import datetime, timezone
from app.perps.services.position_builder import build_positions, FillInput

def _dt(s): return datetime(2026, 1, 1, s, 0, tzinfo=timezone.utc)

def test_funding_only_fill_adds_to_open_position():
    fills = [
        FillInput(side="BUY",  price=100.0, quantity=2.0, executed_at=_dt(1), fee=0.2),
        FillInput(side="BUY",  price=0.0,   quantity=0.0, executed_at=_dt(2), funding_amount=-0.5),  # funding paid
        FillInput(side="SELL", price=110.0, quantity=2.0, executed_at=_dt(3), fee=0.2),
    ]
    [p] = build_positions(fills)
    assert p.quantity == 2.0                       # qty-0 fill doesn't change size
    assert p.avg_entry == 100.0                    # nor avg entry
    assert round(p.total_funding, 6) == -0.5
    # realized = (110-100)*2 - fees(0.4) + funding(-0.5)
    assert round(p.realized_pnl, 6) == round(20.0 - 0.4 - 0.5, 6)

def test_funding_while_flat_is_ignored():
    # A funding fill with no open position must not create a phantom position.
    fills = [FillInput(side="BUY", price=0.0, quantity=0.0, executed_at=_dt(1), funding_amount=-0.5)]
    assert build_positions(fills) == []
