from datetime import datetime, timedelta, timezone
import pytest

from app.database import init_db, SessionLocal
from app.core.models import User
from app.perps.models import ExchangeAccount, Fill, Position, Venue, AssetClass, Side
from app.perps.services.recompute import recompute_positions

T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def ctx():
    init_db()
    db = SessionLocal()
    db.query(Position).delete(); db.query(Fill).delete()
    db.query(ExchangeAccount).delete(); db.query(User).delete(); db.commit()
    u = User(email="p@x.com", password_hash="x"); db.add(u); db.commit(); db.refresh(u)
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="main"); db.add(acc); db.commit(); db.refresh(acc)
    ids = (u.id, acc.id); db.close(); return ids


def _add_fill(db, uid, aid, side, price, qty, mins, symbol="BTCUSDT"):
    db.add(Fill(user_id=uid, exchange_account_id=aid, venue=Venue.BYBIT, symbol=symbol,
                asset_class=AssetClass.PERP, side=side, price=price, quantity=qty,
                executed_at=T0 + timedelta(minutes=mins)))


def test_recompute_creates_positions(ctx):
    uid, aid = ctx
    db = SessionLocal()
    _add_fill(db, uid, aid, Side.BUY, 100, 1, 0); _add_fill(db, uid, aid, Side.SELL, 110, 1, 5)
    db.commit()
    recompute_positions(db, uid, aid, "BTCUSDT")
    rows = db.query(Position).all()
    assert len(rows) == 1 and rows[0].status.value == "CLOSED"
    assert rows[0].realized_pnl == pytest.approx(10)
    assert rows[0].user_id == uid and rows[0].symbol == "BTCUSDT"
    db.close()


def test_recompute_is_idempotent(ctx):
    uid, aid = ctx
    db = SessionLocal()
    _add_fill(db, uid, aid, Side.BUY, 100, 1, 0); _add_fill(db, uid, aid, Side.SELL, 110, 1, 5)
    db.commit()
    recompute_positions(db, uid, aid, "BTCUSDT")
    recompute_positions(db, uid, aid, "BTCUSDT")
    assert db.query(Position).count() == 1
    db.close()


def test_recompute_scope_isolation(ctx):
    uid, aid = ctx
    db = SessionLocal()
    _add_fill(db, uid, aid, Side.BUY, 100, 1, 0, symbol="BTCUSDT")
    _add_fill(db, uid, aid, Side.BUY, 50, 2, 0, symbol="ETHUSDT")
    db.commit()
    recompute_positions(db, uid, aid, "BTCUSDT")
    recompute_positions(db, uid, aid, "ETHUSDT")
    assert db.query(Position).filter(Position.symbol == "BTCUSDT").count() == 1
    assert db.query(Position).filter(Position.symbol == "ETHUSDT").count() == 1
    recompute_positions(db, uid, aid, "BTCUSDT")   # must not touch ETH rows
    assert db.query(Position).filter(Position.symbol == "ETHUSDT").count() == 1
    db.close()
