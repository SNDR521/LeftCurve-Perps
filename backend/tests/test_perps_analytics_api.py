import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.perps.models import Position, Direction, PositionStatus, AssetClass


def _user(email):
    db = SessionLocal(); u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close(); return u


@pytest.fixture()
def two_users():
    init_db()
    db = SessionLocal(); db.query(Position).delete(); db.query(User).delete(); db.commit(); db.close()
    a, b = _user("a@x.com"), _user("b@x.com")
    db = SessionLocal()
    db.add(Position(user_id=a.id, exchange_account_id=1, symbol="BTCUSDT", asset_class=AssetClass.PERP,
                    direction=Direction.LONG, status=PositionStatus.CLOSED, avg_entry=100, avg_exit=110,
                    quantity=1, realized_pnl=10, total_fees=0, total_funding=0, duration_seconds=300,
                    opened_at=datetime(2024,1,1,9,tzinfo=timezone.utc), closed_at=datetime(2024,1,1,10,tzinfo=timezone.utc)))
    db.commit(); db.close()
    return a, b


def _as(u): app.dependency_overrides[get_current_user] = lambda: u
def teardown_function(): app.dependency_overrides.clear()


def test_overview_scoped(two_users):
    a, b = two_users
    c = TestClient(app)
    _as(a)
    assert c.get("/api/perps/analytics/overview").json()["total_trades"] == 1
    assert c.get("/api/perps/analytics/by-symbol").json()[0]["group"] == "BTCUSDT"
    assert c.get("/api/perps/analytics/daily-pnl").status_code == 200
    assert c.get("/api/perps/analytics/heatmap").status_code == 200
    assert c.get("/api/perps/analytics/r-distribution").status_code == 200
    assert c.get("/api/perps/reports/drawdown").status_code == 200
    _as(b)
    assert c.get("/api/perps/analytics/overview").json()["total_trades"] == 0
    assert c.get("/api/perps/analytics/by-symbol").json() == []


def test_requires_auth(two_users):
    c = TestClient(app)
    assert c.get("/api/perps/analytics/overview").status_code == 401


def test_coverage_endpoint(two_users):
    a, b = two_users
    c = TestClient(app)
    _as(a)
    resp = c.get("/api/perps/analytics/coverage")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"total", "exact"}
    assert body["total"] == 1


def test_cross_endpoints(two_users):
    a, b = two_users
    c = TestClient(app)
    _as(a)

    dims = c.get("/api/perps/analytics/dimensions")
    assert dims.status_code == 200
    keys = {d["key"] for d in dims.json()}
    assert {"symbol", "direction", "session", "grade", "leverage"} <= keys

    cross = c.get("/api/perps/analytics/cross?primary=symbol")
    assert cross.status_code == 200
    body = cross.json()
    assert body["primary_dim"] == "symbol"
    assert body["overall"]["trade_count"] == 1
    assert any(g["primary"] == "BTCUSDT" for g in body["groups"])

    crossed = c.get("/api/perps/analytics/cross?primary=symbol&secondary=direction")
    assert crossed.status_code == 200
    assert crossed.json()["secondary_dim"] == "direction"

    ins = c.get("/api/perps/analytics/insights")
    assert ins.status_code == 200
    assert isinstance(ins.json(), list)

    # scoping: user b sees nothing
    _as(b)
    assert c.get("/api/perps/analytics/cross?primary=symbol").json()["overall"]["trade_count"] == 0


def test_cross_requires_auth(two_users):
    c = TestClient(app)
    assert c.get("/api/perps/analytics/cross?primary=symbol").status_code == 401
    assert c.get("/api/perps/analytics/dimensions").status_code == 401
