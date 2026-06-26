import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.perps.models import ExchangeAccount, Fill, Position, Venue


def _user(email):
    db = SessionLocal(); u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close(); return u


@pytest.fixture()
def setup():
    init_db()
    db = SessionLocal()
    for M in (Position, Fill, ExchangeAccount, User): db.query(M).delete()
    db.commit()
    a = User(email="a@x.com", password_hash="x"); b = User(email="b@x.com", password_hash="x")
    db.add(a); db.add(b); db.commit(); db.refresh(a); db.refresh(b)
    acc = ExchangeAccount(user_id=a.id, venue=Venue.BYBIT, label="main")
    db.add(acc); db.commit(); db.refresh(acc)
    db.refresh(a); db.refresh(b)
    db.expunge(a); db.expunge(b)
    ids = (a, b, acc.id); db.close(); return ids


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


def _fill(acc_id, side, price, qty, t):
    return {"exchange_account_id": acc_id, "symbol": "BTCUSDT", "asset_class": "PERP",
            "side": side, "price": price, "quantity": qty, "executed_at": t}


def test_create_fill_triggers_position(setup):
    a, b, aid = setup
    c = TestClient(app); _as(a)
    assert c.post("/api/perps/fills", json=_fill(aid, "BUY", 100, 1, "2024-01-01T00:00:00Z")).status_code in (200, 201)
    c.post("/api/perps/fills", json=_fill(aid, "SELL", 110, 1, "2024-01-01T00:05:00Z"))
    db = SessionLocal()
    pos = db.query(Position).all()
    assert len(pos) == 1 and pos[0].realized_pnl == pytest.approx(10)
    db.close()


def test_bulk_fills(setup):
    a, b, aid = setup
    c = TestClient(app); _as(a)
    r = c.post("/api/perps/fills/bulk", json=[
        _fill(aid, "BUY", 100, 2, "2024-01-01T00:00:00Z"),
        _fill(aid, "SELL", 120, 2, "2024-01-01T00:10:00Z"),
    ])
    assert r.status_code in (200, 201)
    db = SessionLocal()
    assert db.query(Position).filter(Position.symbol == "BTCUSDT").count() == 1
    db.close()


def test_fill_isolation_and_account_ownership(setup):
    a, b, aid = setup
    c = TestClient(app)
    _as(b)
    assert c.post("/api/perps/fills", json=_fill(aid, "BUY", 100, 1, "2024-01-01T00:00:00Z")).status_code == 404
    assert c.get("/api/perps/fills").json() == []
    assert c.get("/api/perps/fills").status_code == 200


def test_delete_fill_recomputes(setup):
    a, b, aid = setup
    c = TestClient(app); _as(a)
    f1 = c.post("/api/perps/fills", json=_fill(aid, "BUY", 100, 1, "2024-01-01T00:00:00Z")).json()
    c.post("/api/perps/fills", json=_fill(aid, "SELL", 110, 1, "2024-01-01T00:05:00Z"))
    c.delete(f"/api/perps/fills/{f1['id']}")
    db = SessionLocal()
    pos = db.query(Position).all()
    assert len(pos) == 1 and pos[0].direction.value == "SHORT"
    db.close()
