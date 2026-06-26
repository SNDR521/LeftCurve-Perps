from datetime import datetime, timedelta, timezone
import pytest

from app.perps.services.position_builder import build_positions, FillInput

T0 = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)


def f(side, price, qty, mins=0, fee=0.0, funding=None, stop=None, risk=None, ac="PERP"):
    return FillInput(side=side, price=price, quantity=qty, executed_at=T0 + timedelta(minutes=mins),
                     fee=fee, funding_amount=funding, stop_price=stop, risk_amount=risk, asset_class=ac)


def test_empty():
    assert build_positions([]) == []


def test_simple_long_full_close():
    ps = build_positions([f("BUY", 100, 1, 0, fee=1), f("SELL", 110, 1, 5, fee=1)])
    assert len(ps) == 1
    p = ps[0]
    assert p.direction == "LONG" and p.status == "CLOSED"
    assert p.quantity == pytest.approx(1)
    assert p.avg_entry == pytest.approx(100) and p.avg_exit == pytest.approx(110)
    assert p.total_fees == pytest.approx(2)
    assert p.realized_pnl == pytest.approx(10 - 2)
    assert p.duration_seconds == 300
    assert p.r_multiple is None


def test_short_profit_when_price_drops():
    ps = build_positions([f("SELL", 100, 1), f("BUY", 90, 1)])
    assert ps[0].direction == "SHORT"
    assert ps[0].realized_pnl == pytest.approx(10)


def test_partial_closes_weighted_exit():
    ps = build_positions([f("BUY", 100, 2, 0, fee=2), f("SELL", 110, 1, 1, fee=1), f("SELL", 120, 1, 2, fee=1)])
    p = ps[0]
    assert p.avg_exit == pytest.approx(115)
    assert p.realized_pnl == pytest.approx((115 - 100) * 2 - 4)


def test_add_to_position_weighted_entry():
    ps = build_positions([f("BUY", 100, 1), f("BUY", 102, 1), f("SELL", 110, 2)])
    assert ps[0].avg_entry == pytest.approx(101)
    assert ps[0].realized_pnl == pytest.approx((110 - 101) * 2)


def test_open_position_has_no_exit():
    ps = build_positions([f("BUY", 100, 1, fee=1)])
    p = ps[0]
    assert p.status == "OPEN" and p.avg_exit is None and p.closed_at is None
    assert p.duration_seconds is None
    assert p.realized_pnl == pytest.approx(-1)


def test_direction_flip_splits():
    ps = build_positions([f("BUY", 100, 2, 0, fee=3), f("SELL", 110, 3, 5, fee=3)])
    assert len(ps) == 2
    closed, opened = ps[0], ps[1]
    assert closed.direction == "LONG" and closed.status == "CLOSED"
    assert closed.quantity == pytest.approx(2)
    assert closed.total_fees == pytest.approx(3 + 2)
    assert closed.realized_pnl == pytest.approx((110 - 100) * 2 - 5)
    assert opened.direction == "SHORT" and opened.status == "OPEN"
    assert opened.quantity == pytest.approx(1)
    assert opened.avg_entry == pytest.approx(110)
    assert opened.total_fees == pytest.approx(1)


def test_signed_funding():
    ps = build_positions([f("BUY", 100, 1, 0, funding=-1), f("SELL", 110, 1, 1, funding=2)])
    p = ps[0]
    assert p.total_funding == pytest.approx(1)
    assert p.realized_pnl == pytest.approx(10 + 1)


def test_r_multiple_from_risk_amount():
    ps = build_positions([f("BUY", 100, 1, 0, risk=5), f("SELL", 108, 1, 1)])
    assert ps[0].realized_pnl == pytest.approx(8)
    assert ps[0].r_multiple == pytest.approx(8 / 5)


def test_r_multiple_from_stop_price():
    ps = build_positions([f("BUY", 100, 1, 0, stop=95), f("SELL", 110, 1, 1)])
    assert ps[0].r_multiple == pytest.approx(10 / 5)


def test_spot_no_funding_same_math():
    ps = build_positions([f("BUY", 100, 1, ac="SPOT"), f("SELL", 105, 1, 1, ac="SPOT")])
    assert ps[0].asset_class == "SPOT"
    assert ps[0].realized_pnl == pytest.approx(5)
