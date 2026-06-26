import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.perps.models import (
    ExchangeAccount, Fill, Position,
    Venue, AssetClass, Side, Direction, PositionStatus,
)


def _user(email):
    db = SessionLocal(); u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close(); return u


@pytest.fixture()
def two_users():
    init_db()
    db = SessionLocal()
    db.query(Fill).delete()
    db.query(Position).delete()
    db.query(ExchangeAccount).delete()
    db.query(User).delete()
    db.commit(); db.close()
    return _user("a@x.com"), _user("b@x.com")


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


def test_accounts_crud_and_isolation(two_users):
    a, b = two_users
    c = TestClient(app)
    _as(a)
    created = c.post("/api/perps/accounts", json={"venue": "BYBIT", "label": "main"})
    assert created.status_code in (200, 201), created.text
    aid = created.json()["id"]
    assert [x["id"] for x in c.get("/api/perps/accounts").json()] == [aid]
    _as(b)
    assert c.get("/api/perps/accounts").json() == []
    assert c.delete(f"/api/perps/accounts/{aid}").status_code == 404


def test_accounts_require_auth(two_users):
    c = TestClient(app)
    assert c.get("/api/perps/accounts").status_code == 401


def test_delete_account_removes_its_fills_and_positions(two_users):
    from datetime import datetime, timezone
    a, b = two_users
    c = TestClient(app); _as(a)
    aid = c.post("/api/perps/accounts", json={"venue": "BYBIT", "label": "main"}).json()["id"]
    # seed a fill + position directly for that account
    db = SessionLocal()
    db.add(Fill(user_id=a.id, exchange_account_id=aid, venue=Venue.BYBIT, symbol="BTCUSDT",
                asset_class=AssetClass.PERP, side=Side.BUY, price=100, quantity=1,
                executed_at=datetime(2024, 1, 1, tzinfo=timezone.utc)))
    db.add(Position(user_id=a.id, exchange_account_id=aid, symbol="BTCUSDT", asset_class=AssetClass.PERP,
                    direction=Direction.LONG, status=PositionStatus.OPEN,
                    opened_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    avg_entry=100, quantity=1, realized_pnl=0, total_fees=0, total_funding=0))
    db.commit(); db.close()
    assert c.delete(f"/api/perps/accounts/{aid}").status_code == 200
    db = SessionLocal()
    assert db.query(Fill).filter(Fill.exchange_account_id == aid).count() == 0
    assert db.query(Position).filter(Position.exchange_account_id == aid).count() == 0
    db.close()


def test_create_hyperliquid_account_stores_address(two_users):
    a, _ = two_users
    c = TestClient(app); _as(a)
    addr = "0x" + "a" * 40
    r = c.post("/api/perps/accounts", json={
        "venue": "HYPERLIQUID", "label": "HL main", "address": addr})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["venue"] == "HYPERLIQUID"
    assert body["has_credentials"] is True


def test_create_hyperliquid_rejects_bad_address(two_users):
    a, _ = two_users
    c = TestClient(app); _as(a)
    r = c.post("/api/perps/accounts", json={
        "venue": "HYPERLIQUID", "label": "HL bad", "address": "not-an-address"})
    assert r.status_code == 422


def test_create_hyperliquid_rejects_missing_address(two_users):
    a, _ = two_users
    c = TestClient(app); _as(a)
    r = c.post("/api/perps/accounts", json={
        "venue": "HYPERLIQUID", "label": "HL no addr"})
    assert r.status_code == 422


def test_create_bybit_account_still_works(two_users):
    a, _ = two_users
    c = TestClient(app); _as(a)
    r = c.post("/api/perps/accounts", json={
        "venue": "BYBIT", "label": "BB", "api_key": "k", "api_secret": "s"})
    assert r.status_code == 200, r.text
    assert r.json()["has_credentials"] is True
