import pytest
from types import SimpleNamespace as NS

from app.perps.models import Direction
from app.perps.services.risk import compute_risk


def _pos(direction=Direction.LONG, entry=100.0, exit_=110.0, mae=None):
    return NS(direction=direction, avg_entry=entry, avg_exit=exit_, mae_price=mae)


def _j(stop=None, triggered=False, targets=None):
    return NS(stop_price=stop, stop_triggered=triggered, targets=targets)


def test_actual_r_with_stop_long():
    r = compute_risk(_pos(), _j(stop=95.0))
    assert r["actual_r"] == pytest.approx(2.0)        # +10 move / 5 risk
    assert r["risk_source"] == "stop"


def test_actual_r_short_sign():
    r = compute_risk(_pos(direction=Direction.SHORT, entry=100.0, exit_=110.0), _j(stop=105.0))
    assert r["actual_r"] == pytest.approx(-2.0)       # short, price up = loss


def test_actual_r_mae_fallback():
    r = compute_risk(_pos(mae=4.0), _j())
    assert r["actual_r"] == pytest.approx(2.5)        # 10 / 4
    assert r["risk_source"] == "mae"


def test_actual_r_triggered_stop_is_minus_one():
    r = compute_risk(_pos(exit_=94.0), _j(stop=95.0, triggered=True))
    assert r["actual_r"] == -1.0


def test_actual_r_null_without_any_risk():
    r = compute_risk(_pos(), _j())
    assert r["actual_r"] is None and r["risk_source"] is None


def test_planned_rr_weighted_targets():
    j = _j(stop=95.0, targets=[{"price": 110.0, "pct": 50.0}, {"price": 120.0, "pct": 50.0}])
    r = compute_risk(_pos(), j)
    assert r["planned_rr"] == pytest.approx(3.0)      # avg target 115 → 15 / 5


def test_planned_rr_null_without_stop_or_targets():
    assert compute_risk(_pos(), _j(targets=[{"price": 110, "pct": 100}]))["planned_rr"] is None
    assert compute_risk(_pos(), _j(stop=95.0))["planned_rr"] is None


def test_handles_missing_journal():
    r = compute_risk(_pos(), None)
    assert r == {"planned_rr": None, "actual_r": None, "risk_source": None}


def test_wrong_side_stop_falls_back_to_mae():
    # SHORT with stop BELOW entry (user error): the stop distance is invalid,
    # risk falls back to MAE; without MAE it stays unknown.
    short = _pos(direction=Direction.SHORT, entry=100.0, exit_=90.0, mae=5.0)
    r = compute_risk(short, _j(stop=95.0))
    assert r["risk_source"] == "mae"
    assert r["actual_r"] == pytest.approx(2.0)        # 10 favorable / 5 mae
    r2 = compute_risk(_pos(direction=Direction.SHORT, entry=100.0, exit_=90.0), _j(stop=95.0))
    assert r2["actual_r"] is None and r2["risk_source"] is None


def test_malformed_target_rows_degrade_to_none():
    j = _j(stop=95.0, targets=[{"price": 110.0}])      # pct missing
    assert compute_risk(_pos(), j)["planned_rr"] is None
