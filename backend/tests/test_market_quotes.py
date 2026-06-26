import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.deps import get_current_user
from app.core.models import User
from app.market import routers as market_router


def _as():
    app.dependency_overrides[get_current_user] = lambda: User(email="m@x.com", password_hash="x")


def teardown_function():
    app.dependency_overrides.clear()


def test_quotes_routes_all_symbols_through_yahoo(monkeypatch):
    calls = []

    async def fake_yahoo(client, symbol):
        calls.append(symbol)
        return {"symbol": symbol, "price": 1.0, "change": 0.1, "change_pct": 1.0,
                "high": 2.0, "low": 0.5, "open": None, "prev_close": 0.9}

    monkeypatch.setattr(market_router, "_yahoo_quote", fake_yahoo)
    _as()
    c = TestClient(app)
    r = c.get("/api/market/quotes?symbols=SPY,^VIX,ES=F")
    assert r.status_code == 200, r.text
    assert [x["symbol"] for x in r.json()] == ["SPY", "^VIX", "ES=F"]
    assert calls == ["SPY", "^VIX", "ES=F"]   # equities now route through Yahoo too


def test_quotes_per_symbol_failure_is_null_row(monkeypatch):
    async def boom(client, symbol):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(market_router, "_yahoo_quote", boom)
    _as()
    c = TestClient(app)
    r = c.get("/api/market/quotes?symbols=SPY")
    assert r.status_code == 200, r.text
    assert r.json()[0] == {"symbol": "SPY", "price": None, "change": None,
                           "change_pct": None, "high": None, "low": None,
                           "open": None, "prev_close": None}


def test_dashboard_quotes_endpoint_removed():
    _as()
    c = TestClient(app)
    assert c.get("/api/market/quotes/dashboard").status_code == 404


def test_news_and_squawk_routes_still_registered():
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/market/news/equity" in paths
    assert "/api/market/news/crypto" in paths
    assert "/api/market/squawk" in paths
