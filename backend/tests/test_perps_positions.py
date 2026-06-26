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
    db.add(acc); db.commit(); db.refresh(acc); db.refresh(a); db.refresh(b)
    db.expunge(a); db.expunge(b)
    ids = (a, b, acc.id); db.close(); return ids


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


def _f(aid, side, price, qty, t):
    return {"exchange_account_id": aid, "symbol": "BTCUSDT", "asset_class": "PERP",
            "side": side, "price": price, "quantity": qty, "executed_at": t}


def test_positions_listed_and_isolated(setup):
    a, b, aid = setup
    c = TestClient(app); _as(a)
    c.post("/api/perps/fills", json=_f(aid, "BUY", 100, 1, "2024-01-01T00:00:00Z"))
    c.post("/api/perps/fills", json=_f(aid, "SELL", 110, 1, "2024-01-01T00:05:00Z"))
    rows = c.get("/api/perps/positions").json()
    assert len(rows) == 1 and rows[0]["status"] == "CLOSED"
    assert rows[0]["realized_pnl"] == pytest.approx(10)
    _as(b)
    assert c.get("/api/perps/positions").json() == []


def test_positions_filter_status(setup):
    a, b, aid = setup
    c = TestClient(app); _as(a)
    c.post("/api/perps/fills", json=_f(aid, "BUY", 100, 2, "2024-01-01T00:00:00Z"))
    c.post("/api/perps/fills", json=_f(aid, "SELL", 110, 1, "2024-01-01T00:05:00Z"))  # partial -> OPEN
    assert len(c.get("/api/perps/positions?status=OPEN").json()) == 1
    assert c.get("/api/perps/positions?status=CLOSED").json() == []


def test_force_recompute(setup):
    a, b, aid = setup
    c = TestClient(app); _as(a)
    c.post("/api/perps/fills", json=_f(aid, "BUY", 100, 1, "2024-01-01T00:00:00Z"))
    db = SessionLocal(); db.query(Position).delete(); db.commit(); db.close()  # simulate drift
    assert c.post("/api/perps/positions/recompute").status_code in (200, 201)
    assert len(c.get("/api/perps/positions").json()) == 1


def test_positions_get_by_id_isolation(setup):
    a, b, aid = setup
    c = TestClient(app); _as(a)
    c.post("/api/perps/fills", json=_f(aid, "BUY", 100, 1, "2024-01-01T00:00:00Z"))
    c.post("/api/perps/fills", json=_f(aid, "SELL", 110, 1, "2024-01-01T00:05:00Z"))
    pid = c.get("/api/perps/positions").json()[0]["id"]
    _as(b)
    assert c.get(f"/api/perps/positions/{pid}").status_code == 404


def test_relink_endpoint_returns_counts(setup):
    # POST /api/perps/positions/relink runs the linker for each of the user's
    # accounts and reports totals; with no fills it's a harmless no-op.
    a, b, aid = setup
    c = TestClient(app); _as(a)
    resp = c.post("/api/perps/positions/relink")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"accounts", "exact", "estimated", "mfe_computed", "skipped_syncing"}
    assert body["accounts"] == 1
