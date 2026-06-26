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
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="m"); db.add(acc); db.commit(); db.refresh(acc)
    ids = (u.id, acc.id); db.close(); return ids


def _fill(db, uid, aid, side, price, qty, mins):
    db.add(Fill(user_id=uid, exchange_account_id=aid, venue=Venue.BYBIT, symbol="BTCUSDT",
                asset_class=AssetClass.PERP, side=side, price=price, quantity=qty,
                executed_at=T0 + timedelta(minutes=mins)))


def test_position_key_deterministic_and_survives_recompute(ctx):
    uid, aid = ctx
    db = SessionLocal()
    _fill(db, uid, aid, Side.BUY, 100, 1, 0); _fill(db, uid, aid, Side.SELL, 110, 1, 5); db.commit()
    recompute_positions(db, uid, aid, "BTCUSDT")
    key1 = db.query(Position).first().position_key
    assert key1 and key1.startswith(f"{aid}:BTCUSDT:")
    recompute_positions(db, uid, aid, "BTCUSDT")
    key2 = db.query(Position).first().position_key
    assert key2 == key1
    db.close()
