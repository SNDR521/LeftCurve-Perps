from types import SimpleNamespace
from app.alarms.conditions import should_fire


def A(condition, value, params=None):
    return SimpleNamespace(condition=condition, value=value, params=params or {})


def test_first_observation_never_fires():
    assert should_fire(A("CROSS", 100), prev_price=None, price=101) is False

def test_cross_either_direction():
    assert should_fire(A("CROSS", 100), prev_price=99, price=101) is True
    assert should_fire(A("CROSS", 100), prev_price=101, price=99) is True
    assert should_fire(A("CROSS", 100), prev_price=101, price=102) is False

def test_cross_up_only_upward():
    assert should_fire(A("CROSS_UP", 100), prev_price=99, price=101) is True
    assert should_fire(A("CROSS_UP", 100), prev_price=101, price=99) is False

def test_cross_down_only_downward():
    assert should_fire(A("CROSS_DOWN", 100), prev_price=101, price=99) is True
    assert should_fire(A("CROSS_DOWN", 100), prev_price=99, price=101) is False

def test_gte_edge_into_zone():
    assert should_fire(A("GTE", 100), prev_price=99, price=100) is True
    assert should_fire(A("GTE", 100), prev_price=100, price=101) is False
    assert should_fire(A("GTE", 100), prev_price=101, price=99) is False

def test_lte_edge_into_zone():
    assert should_fire(A("LTE", 100), prev_price=101, price=100) is True
    assert should_fire(A("LTE", 100), prev_price=100, price=99) is False

def test_pct_move_threshold_edge():
    a = A("PCT_MOVE", 5, {"ref_price": 100})
    assert should_fire(a, prev_price=104, price=105) is True
    assert should_fire(a, prev_price=105, price=106) is False
    assert should_fire(a, prev_price=96,  price=95)  is True

def test_unknown_condition_is_safe():
    assert should_fire(A("WAT", 1), prev_price=1, price=2) is False


def Pctx(**kw):
    base = dict(direction="LONG", entry=100.0, qty=2.0, stop=90.0, liq=80.0, risk_usd=20.0)
    base.update(kw); return base

def test_near_stop_pct_edge():
    a = A("NEAR_STOP", 2, {"unit": "PCT"})
    assert should_fire(a, prev_price=95, price=91.5, ctx=Pctx()) is True
    assert should_fire(a, prev_price=91, price=90.5, ctx=Pctx()) is False
    assert should_fire(a, prev_price=95, price=91.5, ctx=None) is False

def test_upnl_usd_threshold_long_loss():
    a = A("UPNL", -150, {"unit": "USD"})
    assert should_fire(a, prev_price=30, price=24, ctx=Pctx()) is True
    assert should_fire(a, prev_price=24, price=23, ctx=Pctx()) is False

def test_upnl_r_threshold():
    a = A("UPNL", 2, {"unit": "R"})
    assert should_fire(a, prev_price=119, price=121, ctx=Pctx()) is True
    assert should_fire(a, prev_price=121, price=122, ctx=Pctx()) is False

def test_liq_dist_edge():
    a = A("LIQ_DIST", 5, {})
    assert should_fire(a, prev_price=90, price=84, ctx=Pctx()) is True
    assert should_fire(a, prev_price=84, price=83, ctx=Pctx()) is False
    assert should_fire(a, prev_price=90, price=84, ctx=Pctx(liq=0)) is False
