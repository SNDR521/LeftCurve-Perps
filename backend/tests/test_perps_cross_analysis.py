"""Unit tests for the perps cross-analysis engine (mirror of prop's)."""
from datetime import datetime, timezone

import pytest

from app.database import init_db, SessionLocal
from app.core.models import User
from app.perps.models import (
    Position, Direction, PositionStatus, AssetClass, PerpsJournal, OpenedAtSource,
)
from app.perps.services import cross_analysis as cx


def _pos(uid, **kw):
    d = dict(
        user_id=uid, exchange_account_id=1, symbol="BTCUSDT", asset_class=AssetClass.PERP,
        direction=Direction.LONG, status=PositionStatus.CLOSED, avg_entry=100.0, avg_exit=110.0,
        quantity=1.0, realized_pnl=0.0, total_fees=0.0, total_funding=0.0, r_multiple=None,
        duration_seconds=300,
        opened_at=datetime(2024, 1, 1, 9, tzinfo=timezone.utc),
        closed_at=datetime(2024, 1, 1, 10, tzinfo=timezone.utc),
        opened_at_source=OpenedAtSource.EXACT,
    )
    d.update(kw)
    return Position(**d)


@pytest.fixture()
def seeded():
    init_db()
    db = SessionLocal()
    db.query(PerpsJournal).delete(); db.query(Position).delete(); db.query(User).delete(); db.commit()
    u = User(email="cx@x.com", password_hash="x"); db.add(u); db.commit(); db.refresh(u)
    # 2 BTC longs (win), 1 ETH short (loss)
    db.add(_pos(u.id, symbol="BTCUSDT", realized_pnl=10, r_multiple=2.0, position_key="k1",
                closed_at=datetime(2024, 1, 1, 10, tzinfo=timezone.utc)))
    db.add(_pos(u.id, symbol="BTCUSDT", realized_pnl=20, r_multiple=4.0, position_key="k2",
                closed_at=datetime(2024, 1, 2, 10, tzinfo=timezone.utc)))
    db.add(_pos(u.id, symbol="ETHUSDT", realized_pnl=-5, direction=Direction.SHORT, position_key="k3",
                closed_at=datetime(2024, 1, 3, 10, tzinfo=timezone.utc)))
    # journal for k1: setup "Breakout"
    db.add(PerpsJournal(user_id=u.id, position_key="k1", setup_name="Breakout", grade="A"))
    db.commit()
    uid = u.id; db.close()
    return uid


def test_dimensions_include_perps_superset():
    assert {"symbol", "direction", "setup", "grade", "mistake", "tag", "session",
            "weekday", "hour", "leverage", "emotion_before", "emotion_after",
            "rating", "followed_plan", "was_overtrading"} <= set(cx.DIMENSIONS)


def test_empty_returns_zero_overall_shape():
    # Scope to a non-existent user so the result is deterministically empty
    # regardless of any other rows in the shared test DB.
    db = SessionLocal()
    res = cx.cross_analysis(db, "symbol", None, None, user_id=-1)
    db.close()
    assert res["groups"] == []
    assert res["overall"]["trade_count"] == 0
    # profit_factor is None (JSON-serializable) on the empty path, never inf/0.
    assert res["overall"]["profit_factor"] is None


def test_cross_single_dimension_symbol(seeded):
    db = SessionLocal()
    res = cx.cross_analysis(db, "symbol", None, None, user_id=seeded)
    db.close()
    assert res["overall"]["trade_count"] == 3
    assert res["overall"]["total_pnl"] == pytest.approx(25)
    btc = next(g for g in res["groups"] if g["primary"] == "BTCUSDT")
    assert btc["trade_count"] == 2 and btc["total_pnl"] == pytest.approx(30)
    assert btc["win_rate"] == pytest.approx(100.0)
    assert btc["avg_r"] == pytest.approx(3.0)
    eth = next(g for g in res["groups"] if g["primary"] == "ETHUSDT")
    assert eth["total_pnl"] == pytest.approx(-5)


def test_cross_two_dimensions_symbol_x_direction(seeded):
    db = SessionLocal()
    res = cx.cross_analysis(db, "symbol", "direction", None, user_id=seeded)
    db.close()
    assert res["primary_dim"] == "symbol" and res["secondary_dim"] == "direction"
    combo = next(g for g in res["groups"] if g["primary"] == "BTCUSDT" and g["secondary"] == "LONG")
    assert combo["trade_count"] == 2
    assert set(res["secondary_totals"]) == {"LONG", "SHORT"}


def test_journal_dimension_setup(seeded):
    db = SessionLocal()
    res = cx.cross_analysis(db, "setup", None, None, user_id=seeded)
    db.close()
    labels = {g["primary"] for g in res["groups"]}
    assert "Breakout" in labels        # k1 has a setup
    assert "Unspecified" in labels      # k2/k3 have no journal


def test_time_dimension_uses_exact_only(seeded):
    # Add a non-EXACT position; weekday grouping must ignore it.
    db = SessionLocal()
    u = db.query(User).filter(User.id == seeded).first()
    db.add(_pos(u.id, symbol="SOLUSDT", realized_pnl=99, position_key="k4",
                opened_at_source=OpenedAtSource.ESTIMATED,
                closed_at=datetime(2024, 1, 4, 10, tzinfo=timezone.utc)))
    db.commit(); db.close()
    db = SessionLocal()
    res = cx.cross_analysis(db, "weekday", None, None, user_id=seeded)
    db.close()
    assert res["overall"]["trade_count"] == 3   # the INFERRED SOL position is excluded


def test_date_window_filter(seeded):
    db = SessionLocal()
    res = cx.cross_analysis(db, "symbol", None,
                            {"from_date": "2024-01-02", "to_date": "2024-01-02"}, user_id=seeded)
    db.close()
    assert res["overall"]["trade_count"] == 1   # only the Jan-2 position


def test_insights_returns_combos(seeded):
    db = SessionLocal()
    out = cx.compute_insights(db, None, user_id=seeded)
    db.close()
    assert isinstance(out, list)
    for ins in out:
        assert ins["type"] in ("positive", "negative")
        assert "message" in ins and "primary_dim" in ins
