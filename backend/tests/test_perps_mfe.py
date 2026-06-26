from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.perps.models import (
    ExchangeAccount, Position, Venue, AssetClass, Direction, PositionStatus,
    OpenedAtSource,
)
from app.perps.services.mfe import compute_mfe_mae

T0 = datetime(2026, 1, 1, 10, 0, 0)


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u); s.commit()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="Bybit")
    s.add(acc); s.commit()
    yield s, u, acc
    s.close()


def _pos(s, u, acc, direction, source=OpenedAtSource.EXACT, qty=2.0):
    p = Position(user_id=u.id, exchange_account_id=acc.id, symbol="BTCUSDT",
                 asset_class=AssetClass.PERP, direction=direction,
                 status=PositionStatus.CLOSED, opened_at=T0,
                 closed_at=T0 + timedelta(hours=2), avg_entry=100.0, avg_exit=105.0,
                 quantity=qty, realized_pnl=10.0, total_fees=0.0, total_funding=0.0,
                 opened_at_source=source, position_key="1:BTCUSDT:cpnl:o1")
    s.add(p); s.commit()
    return p


CANDLES = [
    {"time": 0, "open": 100, "high": 112, "low": 95, "close": 105, "volume": 1},
    {"time": 60, "open": 105, "high": 108, "low": 99, "close": 105, "volume": 1},
]


def test_mfe_mae_long(db):
    s, u, acc = db
    p = _pos(s, u, acc, Direction.LONG)
    n = compute_mfe_mae(s, acc, fetch=lambda *a, **k: CANDLES)
    assert n == 1
    s.refresh(p)
    assert p.mfe_price == pytest.approx(12.0)   # high 112 - entry 100
    assert p.mae_price == pytest.approx(5.0)    # entry 100 - low 95
    assert p.mfe_usd == pytest.approx(24.0)     # * qty 2
    assert p.mae_usd == pytest.approx(10.0)


def test_mfe_mae_short(db):
    s, u, acc = db
    p = _pos(s, u, acc, Direction.SHORT)
    compute_mfe_mae(s, acc, fetch=lambda *a, **k: CANDLES)
    s.refresh(p)
    assert p.mfe_price == pytest.approx(5.0)    # entry 100 - low 95
    assert p.mae_price == pytest.approx(12.0)   # high 112 - entry 100


def test_mfe_skips_estimated_and_already_computed(db):
    s, u, acc = db
    _pos(s, u, acc, Direction.LONG, source=OpenedAtSource.ESTIMATED)
    done = _pos(s, u, acc, Direction.LONG)
    done.mfe_usd = 1.0; s.commit()
    n = compute_mfe_mae(s, acc, fetch=lambda *a, **k: CANDLES)
    assert n == 0


def test_mfe_survives_fetch_failure(db):
    s, u, acc = db
    p = _pos(s, u, acc, Direction.LONG)
    def boom(*a, **k): raise RuntimeError("bybit down")
    n = compute_mfe_mae(s, acc, fetch=boom)
    assert n == 0
    s.refresh(p)
    assert p.mfe_usd is None  # left null, no crash


def test_mfe_skips_zero_entry_or_quantity(db):
    # zero/null avg_entry or quantity must be skipped, not stored as garbage
    s, u, acc = db
    p = _pos(s, u, acc, Direction.LONG)
    p.avg_entry = 0.0; s.commit()
    n = compute_mfe_mae(s, acc, fetch=lambda *a, **k: CANDLES)
    assert n == 0
    s.refresh(p)
    assert p.mfe_usd is None
