import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
import app.market.routers as market_routers


def _make_user(email: str) -> User:
    db = SessionLocal()
    u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close()
    return u


def teardown_function():
    app.dependency_overrides.clear()
    # Reset Bybit cache so tests don't bleed into each other
    market_routers._bybit_cache = []
    market_routers._bybit_cache_ts = 0.0


@pytest.fixture()
def auth_client():
    import uuid
    u = _make_user(f"search-{uuid.uuid4().hex}@test.com")
    app.dependency_overrides[get_current_user] = lambda: u
    return TestClient(app)


# ---- Fixtures / fakes ----

FAKE_YAHOO = {
    "quotes": [
        {"symbol": "BTC-USD", "shortname": "Bitcoin USD", "quoteType": "CRYPTOCURRENCY"},
        {"symbol": "BTC-GBP", "shortname": "Bitcoin GBP", "quoteType": "CRYPTOCURRENCY"},
        {"symbol": "BTC.X", "shortname": None, "longname": "Bitcoin Futures", "quoteType": "FUTURE"},
    ]
}

FAKE_BYBIT_RESP = {
    "result": {
        "list": [
            {"symbol": "BTCUSDT", "baseCoin": "BTC"},
            {"symbol": "ETHUSDT", "baseCoin": "ETH"},
            {"symbol": "BTCPERP", "baseCoin": "BTC"},
        ]
    }
}


class _FakeHTTPXResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def test_empty_q_returns_empty(auth_client):
    r = auth_client.get("/api/market/search?q=")
    assert r.status_code == 200
    assert r.json() == []


def test_merged_bybit_and_yahoo(monkeypatch, auth_client):
    """Both sources contribute; ETH excluded for q=btc."""
    monkeypatch.setattr(market_routers.httpx, "get", lambda *a, **kw: _FakeHTTPXResp(FAKE_BYBIT_RESP))

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return _FakeHTTPXResp(FAKE_YAHOO)

    monkeypatch.setattr(market_routers.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient())

    r = auth_client.get("/api/market/search?q=btc")
    assert r.status_code == 200
    body = r.json()
    symbols = [x["symbol"] for x in body]
    # Yahoo hits
    assert "BTC-USD" in symbols
    # Bybit hits
    assert "BTCUSDT" in symbols
    assert "BTCPERP" in symbols
    # ETH not matched for q=btc
    assert "ETHUSDT" not in symbols


def test_one_upstream_fail_still_returns_other(monkeypatch, auth_client):
    """If Yahoo raises, Bybit results are still returned."""
    market_routers._bybit_cache = [
        {"symbol": "BTCUSDT", "label": "BTC", "source": "bybit", "type": "PERP"},
    ]
    market_routers._bybit_cache_ts = 9999999999.0  # far future — won't refetch

    class _FailAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, *a, **kw):
            raise RuntimeError("yahoo down")

    monkeypatch.setattr(market_routers.httpx, "AsyncClient", lambda **kw: _FailAsyncClient())

    r = auth_client.get("/api/market/search?q=btc")
    assert r.status_code == 200
    body = r.json()
    assert any(x["symbol"] == "BTCUSDT" for x in body)


def test_search_requires_auth():
    c = TestClient(app)
    assert c.get("/api/market/search?q=btc").status_code == 401


def test_yahoo_type_filter(monkeypatch, auth_client):
    """Only allowed quoteTypes pass through from Yahoo."""
    yahoo_with_junk = {
        "quotes": [
            {"symbol": "AAPL", "shortname": "Apple", "quoteType": "EQUITY"},
            {"symbol": "JUNK", "shortname": "Junk Bond", "quoteType": "MUTUALFUND"},  # filtered
        ]
    }

    class _FakeAsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return _FakeHTTPXResp(yahoo_with_junk)

    monkeypatch.setattr(market_routers.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient())
    market_routers._bybit_cache = []
    market_routers._bybit_cache_ts = 9999999999.0

    r = auth_client.get("/api/market/search?q=apple")
    assert r.status_code == 200
    body = r.json()
    symbols = [x["symbol"] for x in body]
    assert "AAPL" in symbols
    assert "JUNK" not in symbols
