"""Cockpit API tests — aggregate (no account_id) and single-account paths.

Harness mirrors test_perps_account_sync_api.py: TestClient + dependency
overrides for get_db / get_current_user, in-memory SQLite DB.

Monkeypatching targets names on the *router* module so imports are decoupled
from the service implementation (standard pytest-monkeypatch pattern).
"""
import pytest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.database import get_db, Base, make_engine
from app.core.deps import get_current_user
from app.core.models import User
from app.core.security import hash_password
from app.perps.models import ExchangeAccount, Venue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_live(equity: float, positions=None) -> dict:
    """Minimal _account_live return value."""
    return {
        "equity": equity,
        "balance": equity,
        "available": equity * 0.9,
        "open_upnl": 0.0,
        "gross_notional": 0.0,
        "net_notional": 0.0,
        "open_risk_usd": 0.0,
        "unstopped_count": 0,
        "positions": positions or [],
    }


def _fake_client() -> MagicMock:
    """Fake exchange client whose ._client.close() is a no-op."""
    m = MagicMock()
    m._client.close.return_value = None
    return m


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def ctx(tmp_path):
    """Yields (TestClient, Session, User) with get_db / get_current_user overridden."""
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u)
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    app.dependency_overrides[get_current_user] = lambda: u
    yield TestClient(app), s, u
    app.dependency_overrides.clear()
    s.close()


def _seed_two_accounts(s: Session, u: User):
    """Seed one Bybit + one Hyperliquid active perps account; return them."""
    acc1 = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT,
                           label="Bybit Main", is_active=True)
    acc2 = ExchangeAccount(user_id=u.id, venue=Venue.HYPERLIQUID,
                           label="HL Main", is_active=True)
    s.add(acc1)
    s.add(acc2)
    s.commit()
    return acc1, acc2


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cockpit_all_accounts_aggregates(ctx, monkeypatch):
    """No account_id → account_id is None, positions from both accounts, equity summed."""
    tc, s, u = ctx
    acc1, acc2 = _seed_two_accounts(s, u)

    live1 = _make_live(1000.0, [{"symbol": "BTCUSDT", "venue": "BYBIT",
                                  "account_id": acc1.id, "account_label": "Bybit Main"}])
    live2 = _make_live(2000.0, [{"symbol": "ETHUSDT", "venue": "HYPERLIQUID",
                                  "account_id": acc2.id, "account_label": "HL Main"}])

    def fake_account_live(db, account, cli):
        return live1 if account.id == acc1.id else live2

    monkeypatch.setattr("app.perps.routers.cockpit.client_for", lambda a: _fake_client())
    monkeypatch.setattr("app.perps.routers.cockpit._account_live", fake_account_live)

    r = tc.get("/api/perps/cockpit")
    assert r.status_code == 200
    body = r.json()
    assert body["account"]["account_id"] is None
    assert abs(body["account"]["equity"] - 3000.0) < 0.01
    symbols = {p["symbol"] for p in body["positions"]}
    assert "BTCUSDT" in symbols
    assert "ETHUSDT" in symbols


def test_cockpit_partial_on_one_venue_error(ctx, monkeypatch):
    """One account raises → 200 with the other account's data + unavailable == [that venue]."""
    tc, s, u = ctx
    acc1, acc2 = _seed_two_accounts(s, u)

    live2 = _make_live(2000.0, [{"symbol": "ETHUSDT", "venue": "HYPERLIQUID",
                                  "account_id": acc2.id, "account_label": "HL Main"}])

    def fake_account_live(db, account, cli):
        if account.id == acc1.id:
            raise RuntimeError("Bybit API down")
        return live2

    monkeypatch.setattr("app.perps.routers.cockpit.client_for", lambda a: _fake_client())
    monkeypatch.setattr("app.perps.routers.cockpit._account_live", fake_account_live)

    r = tc.get("/api/perps/cockpit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unavailable"] == ["BYBIT"]
    assert abs(body["account"]["equity"] - 2000.0) < 0.01
    symbols = {p["symbol"] for p in body["positions"]}
    assert "ETHUSDT" in symbols
    assert "BTCUSDT" not in symbols


def test_cockpit_all_fail_502(ctx, monkeypatch):
    """Every account raises → 502."""
    tc, s, u = ctx
    _seed_two_accounts(s, u)

    def fake_account_live(db, account, cli):
        raise RuntimeError("all venues down")

    monkeypatch.setattr("app.perps.routers.cockpit.client_for", lambda a: _fake_client())
    monkeypatch.setattr("app.perps.routers.cockpit._account_live", fake_account_live)

    r = tc.get("/api/perps/cockpit")
    assert r.status_code == 502


def test_cockpit_single_account_unchanged(ctx, monkeypatch):
    """?account_id=<id> → single-account path, build_cockpit called, account_id == id."""
    tc, s, u = ctx
    acc1, _ = _seed_two_accounts(s, u)

    canned = {
        "asof": "2026-01-01T00:00:00+00:00",
        "plan": None,
        "account": {
            "account_id": acc1.id,
            "equity": 999.0,
            "balance": 999.0,
            "available": 900.0,
            "realized_today": 0.0,
            "trades_today": 0,
            "open_upnl": 0.0,
            "session_pnl": 0.0,
            "gross_notional": 0.0,
            "net_notional": 0.0,
            "exposure_pct": None,
            "open_risk_usd": 0.0,
            "open_risk_pct": None,
            "unstopped_count": 0,
        },
        "positions": [],
    }

    def fake_build_cockpit(db, account, cli):
        return canned

    monkeypatch.setattr("app.perps.routers.cockpit.client_for", lambda a: _fake_client())
    monkeypatch.setattr("app.perps.routers.cockpit.build_cockpit", fake_build_cockpit)

    r = tc.get(f"/api/perps/cockpit?account_id={acc1.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["account"]["account_id"] == acc1.id
