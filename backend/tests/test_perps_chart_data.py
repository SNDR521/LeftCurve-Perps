"""Tests for chart-data endpoint: auth, candle proxy, and venue dispatch
(Bybit default, Hyperliquid by account)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, SessionLocal
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.models import ExchangeAccount, Venue, Fill, Position
from app.perps.routers import chart_data as cd


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(email):
    db = SessionLocal()
    u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close()
    return u


@pytest.fixture()
def auth_user():
    init_db()
    db = SessionLocal(); db.query(User).delete(); db.commit(); db.close()
    return _user("chart@x.com")


def _fresh_user_and_hl_account():
    init_db()
    s = SessionLocal()
    for M in (Fill, Position, ExchangeAccount, User):
        s.query(M).delete()
    s.commit()
    u = User(email="chart@x.com", password_hash="x")
    s.add(u); s.commit(); s.refresh(u)
    acc = ExchangeAccount(user_id=u.id, venue=Venue.HYPERLIQUID, label="HL",
                          encrypted_credentials="enc", is_active=True)
    s.add(acc); s.commit(); s.refresh(acc); s.refresh(u)
    aid = acc.id
    s.expunge(u)
    s.close()
    return u, aid


# ---------------------------------------------------------------------------
# Existing tests (auth / proxy / error handling)
# ---------------------------------------------------------------------------

def test_chart_data_requires_auth(auth_user):
    c = TestClient(app)
    resp = c.get("/api/perps/chart-data", params={"symbol": "BTCUSDT", "from_ts": 0, "to_ts": 60})
    assert resp.status_code == 401


def test_chart_data_returns_candles(auth_user, monkeypatch):
    fake = [{"time": 0, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3}]
    monkeypatch.setattr(cd, "fetch_klines", lambda *a, **k: list(fake))
    c = TestClient(app); _as(auth_user)
    resp = c.get("/api/perps/chart-data", params={"symbol": "BTCUSDT", "from_ts": 0, "to_ts": 7200})
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "BTCUSDT"
    assert body["interval"] == "1"          # 2h span → 1m bars
    assert body["candles"] == fake


def test_chart_data_rejects_bad_range_and_interval(auth_user):
    c = TestClient(app); _as(auth_user)
    r1 = c.get("/api/perps/chart-data", params={"symbol": "BTCUSDT", "from_ts": 100, "to_ts": 50})
    assert r1.status_code == 422
    r2 = c.get("/api/perps/chart-data", params={"symbol": "BTCUSDT", "from_ts": 0, "to_ts": 60, "interval": "7"})
    assert r2.status_code == 422


def test_chart_data_502_on_upstream_failure(auth_user, monkeypatch):
    def boom(*a, **k): raise RuntimeError("bybit down")
    monkeypatch.setattr(cd, "fetch_klines", boom)
    c = TestClient(app); _as(auth_user)
    # unique range so the TTL cache can't serve a previous test's result
    resp = c.get("/api/perps/chart-data", params={"symbol": "ETHUSDT", "from_ts": 1, "to_ts": 999999})
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# New tests: venue dispatch
# ---------------------------------------------------------------------------

def test_chart_data_defaults_to_bybit(monkeypatch):
    u, _aid = _fresh_user_and_hl_account()
    called = {}

    def _fake_bybit(symbol, iv, s, e):
        called["bybit"] = (symbol, iv)
        return [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}]

    monkeypatch.setattr(cd, "fetch_klines", _fake_bybit)
    _as(u)
    c = TestClient(app)
    r = c.get("/api/perps/chart-data?symbol=BTCUSDT&from_ts=1000&to_ts=5000&interval=60")
    assert r.status_code == 200, r.text
    assert called["bybit"] == ("BTCUSDT", "60")
    assert r.json()["candles"][0]["time"] == 1


def test_chart_data_dispatches_hyperliquid_by_account(monkeypatch):
    u, aid = _fresh_user_and_hl_account()
    called = {}

    def _fake_hl(coin, iv, s, e):
        called["hl"] = (coin, iv)
        return [{"time": 2, "open": 2, "high": 2, "low": 2, "close": 2, "volume": 2}]

    monkeypatch.setattr(cd, "fetch_hl_klines", _fake_hl)
    _as(u)
    c = TestClient(app)
    r = c.get(f"/api/perps/chart-data?symbol=BTC&from_ts=1000&to_ts=5000&interval=60&account_id={aid}")
    assert r.status_code == 200, r.text
    assert called["hl"] == ("BTC", "60")
    assert r.json()["candles"][0]["time"] == 2
