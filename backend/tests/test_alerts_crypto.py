"""Tests for crypto level-crossing alert service and /check route.

Service tests use the tmp-engine fixture pattern (isolated SQLite, no HTTP —
prices are injected via the prices= kwarg).

Route tests use the TestClient / _as override pattern from test_watchlist_api.py
and patch fetch_crypto_prices to return a fixed dict so the real state machine
runs end-to-end.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch
from datetime import datetime

from sqlalchemy.orm import Session

from fastapi.testclient import TestClient

from app.database import Base, make_engine, init_db, SessionLocal
from app.core.models import User
from app.core.security import hash_password
from app.core.deps import get_current_user
from app.main import app
from app.workflow.models import Alert, WatchlistItem


# ── Service-layer fixture (isolated SQLite engine) ────────────────────────────

@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="crypto@test.com", password_hash=hash_password("x"))
    s.add(u)
    s.commit()
    yield s, u
    s.close()


def _item(s, user_id, symbol="BTCUSDT", market="CRYPTO", levels=None):
    """Helper: create a WatchlistItem and return it."""
    item = WatchlistItem(
        user_id=user_id,
        symbol=symbol,
        market=market,
        levels=levels or [],
    )
    s.add(item)
    s.commit()
    return item


# ── 1. First observation → no alert, state stored ────────────────────────────

def test_first_observation_no_alert_stores_state(db):
    """On the first call (last_price None), no alert is created but last_price
    and last_checked are persisted."""
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    _item(s, u.id, levels=[{"price": 50000.0, "label": "resistance"}])

    created = check_crypto_levels(s, u.id, prices={"BTCUSDT": 49000.0})

    assert created == []
    item = s.query(WatchlistItem).filter_by(user_id=u.id).first()
    assert item.last_price == pytest.approx(49000.0)
    assert item.last_checked is not None


# ── 2. Cross UP → alert with correct payload ──────────────────────────────────

def test_cross_up_creates_alert(db):
    """prev below level, now above → direction 'up', all payload fields correct."""
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    item = _item(s, u.id, levels=[{"price": 50000.0, "label": "breakout"}])
    item.last_price = 49000.0  # below level
    s.commit()

    created = check_crypto_levels(s, u.id, prices={"BTCUSDT": 51000.0})

    assert len(created) == 1
    a = created[0]
    assert a.kind == "LEVEL_CROSS"
    assert a.symbol == "BTCUSDT"
    p = a.payload
    assert p["symbol"] == "BTCUSDT"
    assert p["market"] == "CRYPTO"
    assert p["level"] == pytest.approx(50000.0)
    assert p["label"] == "breakout"
    assert p["price"] == pytest.approx(51000.0)
    assert p["direction"] == "up"
    assert p["source"] == "live"


# ── 3. Cross DOWN → direction 'down' ─────────────────────────────────────────

def test_cross_down_creates_alert(db):
    """prev above level, now below → direction 'down'."""
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    item = _item(s, u.id, levels=[{"price": 50000.0, "label": "support"}])
    item.last_price = 51000.0  # above level
    s.commit()

    created = check_crypto_levels(s, u.id, prices={"BTCUSDT": 49000.0})

    assert len(created) == 1
    assert created[0].payload["direction"] == "down"


# ── 4a. Same side (no sign change) → nothing ─────────────────────────────────

def test_same_side_no_alert(db):
    """Both prev and current on the same side → no cross."""
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    item = _item(s, u.id, levels=[{"price": 50000.0, "label": "level"}])
    item.last_price = 48000.0  # both below
    s.commit()

    created = check_crypto_levels(s, u.id, prices={"BTCUSDT": 49000.0})

    assert created == []


# ── 4b. Exact touch (price == level → after == 0) → nothing ──────────────────

def test_exact_touch_no_alert(db):
    """Price landing exactly on the level produces after == 0 → no alert."""
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    item = _item(s, u.id, levels=[{"price": 50000.0, "label": "level"}])
    item.last_price = 49000.0  # below level
    s.commit()

    created = check_crypto_levels(s, u.id, prices={"BTCUSDT": 50000.0})

    assert created == []


def test_exact_prev_touch_no_alert(db):
    """prev price == level (before == 0) → no cross, per the guard."""
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    item = _item(s, u.id, levels=[{"price": 50000.0, "label": "level"}])
    item.last_price = 50000.0  # exactly on level
    s.commit()

    created = check_crypto_levels(s, u.id, prices={"BTCUSDT": 51000.0})

    assert created == []


# ── 5. Unseen-dedupe state machine ────────────────────────────────────────────

def test_unseen_dedupe_blocks_repeat_then_resets_after_seen(db):
    """
    Step A: cross UP → alert created (unseen).
    Step B: reset last_price to other side; cross again while UNSEEN → nothing.
    Step C: mark alert seen; cross again → new alert.
    """
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    item = _item(s, u.id, levels=[{"price": 50000.0, "label": "L"}])

    # Prime with a price below the level
    item.last_price = 49000.0
    s.commit()

    # Step A: cross UP → alert
    created_a = check_crypto_levels(s, u.id, prices={"BTCUSDT": 51000.0})
    assert len(created_a) == 1
    alert = created_a[0]

    # Step B: force last_price back below, cross again while UNSEEN
    s.refresh(item)
    item.last_price = 49000.0
    s.commit()
    created_b = check_crypto_levels(s, u.id, prices={"BTCUSDT": 51000.0})
    assert created_b == []  # dedupe: unseen alert exists

    # Step C: mark seen, then cross again → new alert
    alert.seen = True
    s.commit()
    s.refresh(item)
    item.last_price = 49000.0
    s.commit()
    created_c = check_crypto_levels(s, u.id, prices={"BTCUSDT": 51000.0})
    assert len(created_c) == 1


# ── 6. Multi-level item: price jumps across two levels → two alerts ───────────

def test_multi_level_two_crosses(db):
    """A price that jumps across two levels in one check produces two alerts."""
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    item = _item(s, u.id, levels=[
        {"price": 50000.0, "label": "L1"},
        {"price": 52000.0, "label": "L2"},
    ])
    item.last_price = 49000.0  # below both levels
    s.commit()

    created = check_crypto_levels(s, u.id, prices={"BTCUSDT": 53000.0})

    assert len(created) == 2
    levels_hit = {a.payload["level"] for a in created}
    assert levels_hit == {50000.0, 52000.0}


# ── 7. EQUITY items ignored by the crypto check ───────────────────────────────

def test_equity_items_ignored(db):
    """WatchlistItems with market == 'EQUITY' are not evaluated."""
    from app.workflow.services.alerts import check_crypto_levels
    s, u = db
    # One EQUITY item with a level that would be crossed
    item = _item(s, u.id, symbol="AAPL", market="EQUITY",
                 levels=[{"price": 200.0, "label": "support"}])
    item.last_price = 195.0
    s.commit()

    created = check_crypto_levels(s, u.id, prices={"AAPL": 210.0})

    assert created == []
    # last_price should NOT be updated for EQUITY items
    s.refresh(item)
    assert item.last_price == pytest.approx(195.0)


# ── Route tests (TestClient + _as pattern) ───────────────────────────────────

def _route_user(email: str) -> User:
    db = SessionLocal()
    u = User(email=email, password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.expunge(u)
    db.close()
    return u


@pytest.fixture()
def route_setup():
    init_db()
    db = SessionLocal()
    for M in (Alert, WatchlistItem, User):
        db.query(M).delete()
    db.commit()
    db.close()
    return _route_user("check@route.com")


def _as(u: User):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


# ── 8a. Route 200 shape ───────────────────────────────────────────────────────

def test_check_route_shape_with_cross(route_setup):
    """Patch fetch_crypto_prices so the state machine runs end-to-end through
    the route. Response must have unseen_count and new keys."""
    u = route_setup
    _as(u)

    # Seed a CRYPTO item with last_price below the level
    db = SessionLocal()
    item = WatchlistItem(
        user_id=u.id, symbol="BTCUSDT", market="CRYPTO",
        levels=[{"price": 50000.0, "label": "zone"}],
        last_price=49000.0,
    )
    db.add(item)
    db.commit()
    db.close()

    with patch("app.workflow.services.alerts.fetch_crypto_prices",
               return_value={"BTCUSDT": 51000.0}):
        c = TestClient(app)
        r = c.get("/api/workflow/alerts/check")

    assert r.status_code == 200
    out = r.json()
    assert "unseen_count" in out
    assert "new" in out
    assert isinstance(out["new"], list)
    assert len(out["new"]) == 1
    alert_out = out["new"][0]
    assert alert_out["payload"]["direction"] == "up"
    assert out["unseen_count"] == 1


# ── 8b. fetch raising → still 200 with new: [] ───────────────────────────────

def test_check_route_fetch_raises_returns_200(route_setup):
    """If the fetch/service throws, the route must NOT 5xx — it returns 200
    with new: []."""
    u = route_setup
    _as(u)

    with patch("app.workflow.services.alerts.fetch_crypto_prices",
               side_effect=RuntimeError("exchange down")):
        c = TestClient(app)
        r = c.get("/api/workflow/alerts/check")

    assert r.status_code == 200
    out = r.json()
    assert out["new"] == []
    assert "unseen_count" in out


# ── 8c. 401 unauthenticated ───────────────────────────────────────────────────

def test_check_route_401(route_setup):
    app.dependency_overrides.clear()
    c = TestClient(app)
    assert c.get("/api/workflow/alerts/check").status_code == 401
