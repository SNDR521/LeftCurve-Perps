"""Tests for GET /api/workflow/symbol-stats

Perps-only symbol stats: closed positions only. Prop workspace removed in
Task 1.3 (perps-only extraction). Tests that previously checked prop or
cross-workspace aggregation have been updated accordingly.
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.core.security import hash_password
from app.perps.models import (
    ExchangeAccount, Position, Venue, AssetClass, Direction, PositionStatus,
    OpenedAtSource,
)


# ── helpers ───────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 1, 12, 0, 0)


def _mk_user(db, email="stats@x.com"):
    u = User(email=email, password_hash=hash_password("x"))
    db.add(u)
    db.commit()
    db.refresh(u)
    db.expunge(u)
    return u


def _mk_exchange_acc(db, user):
    acc = ExchangeAccount(user_id=user.id, venue=Venue.BYBIT, label="Bybit")
    db.add(acc)
    db.commit()
    db.refresh(acc)
    db.expunge(acc)
    return acc


def _perps_pos(user, acc, symbol, pnl, closed_at=_NOW):
    db = SessionLocal()
    try:
        p = Position(
            user_id=user.id,
            exchange_account_id=acc.id,
            symbol=symbol,
            asset_class=AssetClass.PERP,
            direction=Direction.LONG,
            status=PositionStatus.CLOSED,
            opened_at=closed_at - timedelta(hours=1),
            closed_at=closed_at,
            avg_entry=100.0,
            avg_exit=105.0,
            quantity=1.0,
            realized_pnl=pnl,
            total_fees=0.0,
            total_funding=0.0,
            opened_at_source=OpenedAtSource.EXACT,
            position_key=f"k:{symbol}:{closed_at.isoformat()}:{pnl}",
        )
        db.add(p)
        db.commit()
    finally:
        db.close()


def _clean_db():
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM position_fills"))
        db.execute(text("DELETE FROM positions"))
        db.execute(text("DELETE FROM exchange_accounts"))
        db.execute(text("DELETE FROM users"))
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def setup():
    """Reset shared tables and return a detached user + exchange-account pair."""
    init_db()
    _clean_db()

    db = SessionLocal()
    u = _mk_user(db)
    acc = _mk_exchange_acc(db, u)
    db.close()

    app.dependency_overrides[get_current_user] = lambda: u
    yield u, acc
    app.dependency_overrides.clear()
    _clean_db()


def _client():
    return TestClient(app)


# ── auth ──────────────────────────────────────────────────────────────────────

def test_symbol_stats_requires_login():
    r = TestClient(app).get("/api/workflow/symbol-stats?symbols=BTCUSDT")
    assert r.status_code == 401


# ── 422 when >50 symbols ──────────────────────────────────────────────────────

def test_symbol_stats_rejects_over_50_symbols(setup):
    symbols = ",".join(f"SYM{i}" for i in range(51))
    r = _client().get(f"/api/workflow/symbol-stats?symbols={symbols}")
    assert r.status_code == 422


def test_symbol_stats_accepts_exactly_50_symbols(setup):
    symbols = ",".join(f"SYM{i}" for i in range(50))
    r = _client().get(f"/api/workflow/symbol-stats?symbols={symbols}")
    # No trades → empty map, but not an error
    assert r.status_code == 200
    assert r.json() == {}


# ── omit symbols with zero trades ────────────────────────────────────────────

def test_untraded_symbols_omitted(setup):
    u, acc = setup
    _perps_pos(u, acc, "BTCUSDT", 100.0)
    r = _client().get("/api/workflow/symbol-stats?symbols=BTCUSDT,ETHUSDT,SOLUSDT")
    assert r.status_code == 200
    body = r.json()
    assert "BTCUSDT" in body
    assert "ETHUSDT" not in body
    assert "SOLUSDT" not in body


# ── perps positions ───────────────────────────────────────────────────────────

def test_perps_symbol(setup):
    u, acc = setup
    _perps_pos(u, acc, "BTCUSDT", 50.0)
    _perps_pos(u, acc, "BTCUSDT", -20.0, _NOW + timedelta(hours=1))

    r = _client().get("/api/workflow/symbol-stats?symbols=BTCUSDT")
    assert r.status_code == 200
    body = r.json()
    stat = body["BTCUSDT"]
    assert stat["trade_count"] == 2
    assert stat["total_pnl"] == pytest.approx(30.0)
    assert stat["win_rate"] == pytest.approx(0.5)
    assert stat["workspace"] == "perps"
    assert stat["last_traded"] is not None


def test_no_trades_symbol_omitted(setup):
    """A symbol with no perps positions is omitted from the response."""
    u, acc = setup
    r = _client().get("/api/workflow/symbol-stats?symbols=XAUUSD")
    assert r.status_code == 200
    assert r.json() == {}


# ── symbol uppercasing ────────────────────────────────────────────────────────

def test_symbols_uppercased(setup):
    u, acc = setup
    _perps_pos(u, acc, "BTCUSDT", 50.0)

    r = _client().get("/api/workflow/symbol-stats?symbols=btcusdt")
    assert r.status_code == 200
    body = r.json()
    # Response key should be uppercase
    assert "BTCUSDT" in body


# ── deduplication of repeated symbols ────────────────────────────────────────

def test_duplicate_symbols_deduped(setup):
    u, acc = setup
    _perps_pos(u, acc, "BTCUSDT", 50.0)

    r = _client().get("/api/workflow/symbol-stats?symbols=BTCUSDT,btcusdt,BTCUSDT")
    assert r.status_code == 200
    body = r.json()
    # Only one key despite duplicates
    assert list(body.keys()).count("BTCUSDT") == 1


# ── win_rate=0 when all losses ────────────────────────────────────────────────

def test_win_rate_zero_all_losses(setup):
    u, acc = setup
    _perps_pos(u, acc, "BTCUSDT", -10.0)
    _perps_pos(u, acc, "BTCUSDT", -20.0, _NOW + timedelta(hours=1))

    r = _client().get("/api/workflow/symbol-stats?symbols=BTCUSDT")
    assert r.status_code == 200
    assert r.json()["BTCUSDT"]["win_rate"] == pytest.approx(0.0)


# ── user isolation ────────────────────────────────────────────────────────────

def test_user_isolation(setup):
    """Other users' trades must not appear in results."""
    u, acc = setup
    # Create a second user with their own positions
    db = SessionLocal()
    u2 = _mk_user(db, "other@x.com")
    acc2 = _mk_exchange_acc(db, u2)
    db.close()
    _perps_pos(u2, acc2, "BTCUSDT", 999.0)

    # Query as user u (who has no trades)
    r = _client().get("/api/workflow/symbol-stats?symbols=BTCUSDT")
    assert r.status_code == 200
    assert r.json() == {}


# ── last_traded is ISO string or null ─────────────────────────────────────────

def test_last_traded_iso_format(setup):
    u, acc = setup
    _perps_pos(u, acc, "BTCUSDT", 50.0)

    r = _client().get("/api/workflow/symbol-stats?symbols=BTCUSDT")
    body = r.json()
    lt = body["BTCUSDT"]["last_traded"]
    assert lt is not None
    # Should parse as an ISO datetime
    datetime.fromisoformat(lt.replace("Z", "+00:00"))
