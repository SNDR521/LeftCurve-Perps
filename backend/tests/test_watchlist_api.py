"""Watchlist CRUD + alerts list/seen endpoint tests.

Covers:
- Watchlist CRUD happy paths
- Symbol uppercased in response
- Invalid market → 422
- Level price 0 → 422, level label 41 chars → 422
- Duplicate symbol → 400
- PUT partial keeps fields
- Alerts list ordering + unseen_count
- Alerts seen by ids and by all
- User isolation (other user sees nothing / 404)
- 401s for all protected routes
"""
import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.workflow.models import WatchlistItem, Alert


# ── helpers ───────────────────────────────────────────────────────────────────

def _user(email: str) -> User:
    db = SessionLocal()
    u = User(email=email, password_hash="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.expunge(u)
    db.close()
    return u


@pytest.fixture()
def setup():
    init_db()
    db = SessionLocal()
    for M in (Alert, WatchlistItem, User):
        db.query(M).delete()
    db.commit()
    db.close()
    return _user("wl@x.com")


def _as(u: User):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


# ── 401 guards ────────────────────────────────────────────────────────────────

def test_watchlist_401(setup):
    app.dependency_overrides.clear()
    c = TestClient(app)
    assert c.get("/api/workflow/watchlist").status_code == 401
    assert c.post("/api/workflow/watchlist", json={}).status_code == 401
    assert c.put("/api/workflow/watchlist/1", json={}).status_code == 401
    assert c.delete("/api/workflow/watchlist/1").status_code == 401


def test_alerts_401(setup):
    app.dependency_overrides.clear()
    c = TestClient(app)
    assert c.get("/api/workflow/alerts").status_code == 401
    assert c.post("/api/workflow/alerts/seen", json={"all": True}).status_code == 401


# ── Watchlist CRUD happy path ─────────────────────────────────────────────────

def test_create_watchlist_item(setup):
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={
        "symbol": "btcusdt",
        "market": "CRYPTO",
        "note": "main watch",
        "levels": [{"price": 50000.0, "label": "support"}],
    })
    assert r.status_code == 201
    out = r.json()
    assert out["symbol"] == "BTCUSDT"   # uppercased
    assert out["market"] == "CRYPTO"
    assert out["note"] == "main watch"
    assert out["levels"] == [{"price": 50000.0, "label": "support"}]
    assert "id" in out


def test_symbol_uppercased_in_response(setup):
    """Lowercase symbol in request body → uppercase in response."""
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={"symbol": "ethusdt", "market": "CRYPTO"})
    assert r.status_code == 201
    assert r.json()["symbol"] == "ETHUSDT"


def test_list_watchlist_items_empty(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/watchlist")
    assert r.status_code == 200
    assert r.json() == []


def test_list_watchlist_items_newest_first(setup):
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/watchlist", json={"symbol": "BTCUSDT", "market": "CRYPTO"})
    c.post("/api/workflow/watchlist", json={"symbol": "ETHUSDT", "market": "CRYPTO"})
    items = c.get("/api/workflow/watchlist").json()
    assert len(items) == 2
    # Newest first: ETHUSDT was created after BTCUSDT
    assert items[0]["symbol"] == "ETHUSDT"
    assert items[1]["symbol"] == "BTCUSDT"


def test_put_watchlist_item_partial_update(setup):
    """PUT with only 'note' should not clear other fields."""
    _as(setup)
    c = TestClient(app)
    item_id = c.post("/api/workflow/watchlist", json={
        "symbol": "SOLUSDT",
        "market": "CRYPTO",
        "note": "original note",
        "levels": [{"price": 100.0, "label": "key level"}],
    }).json()["id"]

    r = c.put(f"/api/workflow/watchlist/{item_id}", json={"note": "updated note"})
    assert r.status_code == 200
    out = r.json()
    assert out["note"] == "updated note"
    assert out["symbol"] == "SOLUSDT"          # unchanged
    assert out["market"] == "CRYPTO"            # unchanged
    assert out["levels"] == [{"price": 100.0, "label": "key level"}]  # unchanged


def test_put_partial_update_levels(setup):
    """PUT with only 'levels' keeps note intact."""
    _as(setup)
    c = TestClient(app)
    item_id = c.post("/api/workflow/watchlist", json={
        "symbol": "AVAXUSDT",
        "market": "CRYPTO",
        "note": "keep me",
    }).json()["id"]

    r = c.put(f"/api/workflow/watchlist/{item_id}", json={
        "levels": [{"price": 20.0, "label": "new level"}]
    })
    assert r.status_code == 200
    out = r.json()
    assert out["note"] == "keep me"
    assert out["levels"] == [{"price": 20.0, "label": "new level"}]


def test_delete_watchlist_item(setup):
    _as(setup)
    c = TestClient(app)
    item_id = c.post("/api/workflow/watchlist", json={
        "symbol": "NVDA", "market": "EQUITY"
    }).json()["id"]

    r = c.delete(f"/api/workflow/watchlist/{item_id}")
    assert r.status_code == 204

    assert c.get("/api/workflow/watchlist").json() == []


def test_delete_watchlist_404_other_user(setup):
    _as(setup)
    c = TestClient(app)
    item_id = c.post("/api/workflow/watchlist", json={
        "symbol": "BTCUSDT", "market": "CRYPTO"
    }).json()["id"]

    other = _user("other_del_wl@x.com")
    _as(other)
    r = c.delete(f"/api/workflow/watchlist/{item_id}")
    assert r.status_code == 404


def test_put_watchlist_404_other_user(setup):
    _as(setup)
    c = TestClient(app)
    item_id = c.post("/api/workflow/watchlist", json={
        "symbol": "BTCUSDT", "market": "CRYPTO"
    }).json()["id"]

    other = _user("other_put_wl@x.com")
    _as(other)
    r = c.put(f"/api/workflow/watchlist/{item_id}", json={"note": "hack"})
    assert r.status_code == 404


# ── Validation errors ─────────────────────────────────────────────────────────

def test_invalid_market_422(setup):
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={"symbol": "BTCUSDT", "market": "FUTURES"})
    assert r.status_code == 422


def test_level_price_zero_422(setup):
    """Level price must be > 0."""
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={
        "symbol": "BTCUSDT",
        "market": "CRYPTO",
        "levels": [{"price": 0.0, "label": "bad"}],
    })
    assert r.status_code == 422


def test_level_price_negative_422(setup):
    """Negative level price → 422."""
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={
        "symbol": "BTCUSDT",
        "market": "CRYPTO",
        "levels": [{"price": -100.0, "label": "bad"}],
    })
    assert r.status_code == 422


def test_level_label_41_chars_422(setup):
    """Label > 40 characters → 422."""
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={
        "symbol": "BTCUSDT",
        "market": "CRYPTO",
        "levels": [{"price": 50000.0, "label": "a" * 41}],
    })
    assert r.status_code == 422


def test_level_label_40_chars_ok(setup):
    """Label exactly 40 characters → 201."""
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={
        "symbol": "BTCUSDT",
        "market": "CRYPTO",
        "levels": [{"price": 50000.0, "label": "a" * 40}],
    })
    assert r.status_code == 201


def test_missing_symbol_422(setup):
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={"market": "CRYPTO"})
    assert r.status_code == 422


def test_empty_symbol_422(setup):
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/watchlist", json={"symbol": "  ", "market": "CRYPTO"})
    assert r.status_code == 422


# ── Duplicate symbol → 400 ────────────────────────────────────────────────────

def test_duplicate_symbol_returns_400(setup):
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/watchlist", json={"symbol": "BTCUSDT", "market": "CRYPTO"})
    r = c.post("/api/workflow/watchlist", json={"symbol": "BTCUSDT", "market": "CRYPTO"})
    assert r.status_code == 400


def test_duplicate_symbol_case_insensitive_400(setup):
    """btcusdt and BTCUSDT are the same after normalization → 400."""
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/watchlist", json={"symbol": "BTCUSDT", "market": "CRYPTO"})
    r = c.post("/api/workflow/watchlist", json={"symbol": "btcusdt", "market": "CRYPTO"})
    assert r.status_code == 400


def test_same_symbol_different_user_ok(setup):
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/watchlist", json={"symbol": "BTCUSDT", "market": "CRYPTO"})

    other = _user("other_dup_wl@x.com")
    _as(other)
    r = c.post("/api/workflow/watchlist", json={"symbol": "BTCUSDT", "market": "CRYPTO"})
    assert r.status_code == 201


# ── User isolation ────────────────────────────────────────────────────────────

def test_watchlist_user_isolation(setup):
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/watchlist", json={"symbol": "BTCUSDT", "market": "CRYPTO"})

    other = _user("iso_wl@x.com")
    _as(other)
    assert c.get("/api/workflow/watchlist").json() == []


# ── Alerts list + unseen_count ────────────────────────────────────────────────

def _seed_alert(user_id: int, symbol: str, seen: bool = False,
                kind: str = "LEVEL_CROSS",
                triggered_at: datetime.datetime | None = None) -> int:
    db = SessionLocal()
    t = triggered_at or datetime.datetime(2026, 6, 11, 10, 0, 0)
    a = Alert(user_id=user_id, kind=kind, symbol=symbol,
              payload={"symbol": symbol}, triggered_at=t, seen=seen)
    db.add(a)
    db.commit()
    alert_id = a.id
    db.close()
    return alert_id


def test_alerts_list_empty(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/alerts")
    assert r.status_code == 200
    out = r.json()
    assert out["alerts"] == []
    assert out["unseen_count"] == 0


def test_alerts_list_newest_first(setup):
    _as(setup)
    t1 = datetime.datetime(2026, 6, 11, 9, 0, 0)
    t2 = datetime.datetime(2026, 6, 11, 10, 0, 0)
    _seed_alert(setup.id, "BTCUSDT", triggered_at=t1)
    _seed_alert(setup.id, "ETHUSDT", triggered_at=t2)

    c = TestClient(app)
    r = c.get("/api/workflow/alerts")
    assert r.status_code == 200
    out = r.json()
    assert len(out["alerts"]) == 2
    # Newest first: ETHUSDT (t2 > t1)
    assert out["alerts"][0]["symbol"] == "ETHUSDT"
    assert out["alerts"][1]["symbol"] == "BTCUSDT"


def test_alerts_unseen_count(setup):
    _as(setup)
    _seed_alert(setup.id, "BTCUSDT", seen=False)
    _seed_alert(setup.id, "ETHUSDT", seen=False)
    _seed_alert(setup.id, "SOLUSDT", seen=True)

    c = TestClient(app)
    r = c.get("/api/workflow/alerts")
    assert r.json()["unseen_count"] == 2


def test_alerts_limit_param(setup):
    _as(setup)
    for i in range(25):
        _seed_alert(setup.id, f"SYM{i:02d}")

    c = TestClient(app)
    r = c.get("/api/workflow/alerts?limit=10")
    assert r.status_code == 200
    assert len(r.json()["alerts"]) == 10


def test_alerts_default_limit_20(setup):
    _as(setup)
    for i in range(25):
        _seed_alert(setup.id, f"SYM{i:02d}")

    c = TestClient(app)
    r = c.get("/api/workflow/alerts")
    assert r.status_code == 200
    assert len(r.json()["alerts"]) == 20


# ── Alerts seen by ids ────────────────────────────────────────────────────────

def test_mark_alerts_seen_by_ids(setup):
    _as(setup)
    id1 = _seed_alert(setup.id, "BTCUSDT", seen=False)
    id2 = _seed_alert(setup.id, "ETHUSDT", seen=False)
    _seed_alert(setup.id, "SOLUSDT", seen=False)

    c = TestClient(app)
    r = c.post("/api/workflow/alerts/seen", json={"ids": [id1, id2]})
    assert r.status_code == 200
    assert r.json()["unseen_count"] == 1  # SOLUSDT still unseen


def test_mark_alerts_seen_all(setup):
    _as(setup)
    _seed_alert(setup.id, "BTCUSDT", seen=False)
    _seed_alert(setup.id, "ETHUSDT", seen=False)

    c = TestClient(app)
    r = c.post("/api/workflow/alerts/seen", json={"all": True})
    assert r.status_code == 200
    assert r.json()["unseen_count"] == 0


def test_mark_alerts_seen_does_not_affect_other_user(setup):
    """Marking alerts seen for user A should not affect user B's unseen_count."""
    _as(setup)
    other = _user("other_seen@x.com")
    _seed_alert(other.id, "BTCUSDT", seen=False)

    c = TestClient(app)
    # mark all for setup user (has no alerts)
    c.post("/api/workflow/alerts/seen", json={"all": True})

    # other user still has unseen alerts
    _as(other)
    r = c.get("/api/workflow/alerts")
    assert r.json()["unseen_count"] == 1


def test_mark_seen_by_ids_ignores_other_user_ids(setup):
    """Passing another user's alert id in ids should not mark it seen."""
    _as(setup)
    other = _user("other_ids@x.com")
    other_alert_id = _seed_alert(other.id, "BTCUSDT", seen=False)

    c = TestClient(app)
    # setup user tries to mark other's alert seen by id
    r = c.post("/api/workflow/alerts/seen", json={"ids": [other_alert_id]})
    assert r.status_code == 200

    # other user's alert should still be unseen
    _as(other)
    r2 = c.get("/api/workflow/alerts")
    assert r2.json()["unseen_count"] == 1


# ── Alerts response shape ─────────────────────────────────────────────────────

def test_alert_out_shape(setup):
    _as(setup)
    t = datetime.datetime(2026, 6, 11, 10, 30, 0)
    _seed_alert(setup.id, "BTCUSDT", triggered_at=t)

    c = TestClient(app)
    alerts = c.get("/api/workflow/alerts").json()["alerts"]
    assert len(alerts) == 1
    a = alerts[0]
    assert "id" in a
    assert "kind" in a
    assert "symbol" in a
    assert "payload" in a
    assert "triggered_at" in a
    assert "seen" in a


# ── Alerts user isolation ─────────────────────────────────────────────────────

def test_alerts_user_isolation(setup):
    _as(setup)
    other = _user("iso_alerts@x.com")
    _seed_alert(other.id, "BTCUSDT")

    c = TestClient(app)
    r = c.get("/api/workflow/alerts")
    assert r.json()["alerts"] == []
    assert r.json()["unseen_count"] == 0
