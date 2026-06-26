"""Plan-card endpoint tests: upsert with normalization + frozen regime snapshot,
partial update, GET/404, list with from/to, score endpoint, regime-failure path,
auth, and per-user isolation."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.workflow.models import PlanCard
from app.workflow.routers import plan_cards as plan_cards_router
from app.perps.models import (
    ExchangeAccount, Position, Venue, AssetClass, Direction, PositionStatus,
    OpenedAtSource,
)

DATE = "2026-06-11"
FIXED_SNAPSHOT = {"CRYPTO": {"breadth": {"total": 100, "above_20": 60},
                             "top_themes": [{"theme": "AI", "score": 88.0,
                                             "status": "DOMINANT"}]}}
OTHER_SNAPSHOT = {"EQUITY": {"breadth": {"total": 5}, "top_themes": []}}


def _user(email):
    db = SessionLocal(); u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close(); return u


@pytest.fixture()
def setup():
    init_db()
    db = SessionLocal()
    for M in (PlanCard, Position, ExchangeAccount, User):
        db.query(M).delete()
    db.commit(); db.close()
    return _user("plan@x.com")


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


def _acc(u):
    db = SessionLocal()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="b")
    db.add(acc); db.commit(); aid = acc.id; db.close()
    return aid


def _closed_position(u, acc_id, symbol, pnl, closed_at):
    db = SessionLocal()
    db.add(Position(
        user_id=u.id, exchange_account_id=acc_id, symbol=symbol,
        asset_class=AssetClass.PERP, direction=Direction.LONG,
        status=PositionStatus.CLOSED, opened_at=closed_at - timedelta(hours=1),
        closed_at=closed_at, avg_entry=100.0, avg_exit=105.0, quantity=1.0,
        realized_pnl=pnl, total_fees=0.0, total_funding=0.0,
        opened_at_source=OpenedAtSource.EXACT,
        position_key=f"{acc_id}:{symbol}:{closed_at.isoformat()}"))
    db.commit(); db.close()


# ── create: normalization + snapshot frozen at creation ──────────────

def test_create_normalizes_shortlist_and_snapshots(setup, monkeypatch):
    monkeypatch.setattr(plan_cards_router, "snapshot_regime", lambda: FIXED_SNAPSHOT)
    c = TestClient(app); _as(setup)
    r = c.put(f"/api/workflow/plan-cards/{DATE}",
              json={"shortlist": ["btcusdt", " ethusdt ", "", "  "],
                    "max_trades": 3, "max_daily_loss": 300.0})
    assert r.status_code == 200
    out = r.json()
    assert out["date"] == DATE
    assert out["shortlist"] == ["BTCUSDT", "ETHUSDT"]   # upper + strip + drop empties
    assert out["max_trades"] == 3
    assert out["max_daily_loss"] == 300.0
    assert out["regime_snapshot"] == FIXED_SNAPSHOT


def test_update_does_not_resnapshot_and_keeps_unsent_fields(setup, monkeypatch):
    monkeypatch.setattr(plan_cards_router, "snapshot_regime", lambda: FIXED_SNAPSHOT)
    c = TestClient(app); _as(setup)
    c.put(f"/api/workflow/plan-cards/{DATE}",
          json={"shortlist": ["btcusdt"], "max_trades": 3})

    # A later update with a DIFFERENT live regime must NOT overwrite the frozen one,
    # and must preserve fields that weren't part of this request body.
    monkeypatch.setattr(plan_cards_router, "snapshot_regime", lambda: OTHER_SNAPSHOT)
    r = c.put(f"/api/workflow/plan-cards/{DATE}", json={"key_lesson": "size down"})
    assert r.status_code == 200
    out = r.json()
    assert out["key_lesson"] == "size down"
    assert out["regime_snapshot"] == FIXED_SNAPSHOT   # frozen, not OTHER_SNAPSHOT
    assert out["shortlist"] == ["BTCUSDT"]             # untouched
    assert out["max_trades"] == 3                      # untouched


# ── GET single ───────────────────────────────────────────────────────

def test_get_plan_card(setup, monkeypatch):
    monkeypatch.setattr(plan_cards_router, "snapshot_regime", lambda: FIXED_SNAPSHOT)
    c = TestClient(app); _as(setup)
    c.put(f"/api/workflow/plan-cards/{DATE}", json={"max_trades": 2})
    r = c.get(f"/api/workflow/plan-cards/{DATE}")
    assert r.status_code == 200
    assert r.json()["max_trades"] == 2


def test_get_plan_card_404(setup):
    c = TestClient(app); _as(setup)
    r = c.get("/api/workflow/plan-cards/2026-01-01")
    assert r.status_code == 404


def test_invalid_date_422(setup):
    c = TestClient(app); _as(setup)
    assert c.get("/api/workflow/plan-cards/not-a-date").status_code == 422
    assert c.put("/api/workflow/plan-cards/2026-13-99", json={}).status_code == 422


# ── list with from/to ────────────────────────────────────────────────

def test_list_plan_cards_with_range(setup, monkeypatch):
    monkeypatch.setattr(plan_cards_router, "snapshot_regime", lambda: None)
    c = TestClient(app); _as(setup)
    for d in ("2026-06-10", "2026-06-11", "2026-06-12"):
        c.put(f"/api/workflow/plan-cards/{d}", json={"max_trades": 1})

    r = c.get("/api/workflow/plan-cards", params={"from": "2026-06-11", "to": "2026-06-12"})
    assert r.status_code == 200
    rows = r.json()
    assert [row["date"] for row in rows] == ["2026-06-11", "2026-06-12"]
    for row in rows:
        assert set(row.keys()) == {"date", "adherent", "trades_count"}
        assert row["adherent"] is True       # no trades, no breach
        assert row["trades_count"] == 0

    # No filters → all three, ordered by date.
    allrows = c.get("/api/workflow/plan-cards").json()
    assert [row["date"] for row in allrows] == ["2026-06-10", "2026-06-11", "2026-06-12"]


# ── score endpoint ───────────────────────────────────────────────────

def test_score_endpoint_shape(setup, monkeypatch):
    monkeypatch.setattr(plan_cards_router, "snapshot_regime", lambda: None)
    acc_id = _acc(setup)
    # One in-window closed position (2026-06-11) that breaches a 1-trade cap.
    _closed_position(setup, acc_id, "ETHUSDT", -50.0, datetime(2026, 6, 11, 12, 0))
    c = TestClient(app); _as(setup)
    c.put(f"/api/workflow/plan-cards/{DATE}",
          json={"max_trades": 0, "shortlist": ["BTCUSDT"]})

    r = c.get(f"/api/workflow/plan-cards/{DATE}/score")
    assert r.status_code == 200
    out = r.json()
    assert out["trades_count"] == 1
    assert out["realized"] == pytest.approx(-50.0)
    assert out["traded_symbols"] == ["ETHUSDT"]
    assert out["offlist_symbols"] == ["ETHUSDT"]
    assert out["flags"]["trades_over"] is True
    assert out["flags"]["offlist"] is True
    assert out["adherent"] is False
    assert "window" in out


def test_score_endpoint_404_when_no_card(setup):
    c = TestClient(app); _as(setup)
    assert c.get(f"/api/workflow/plan-cards/{DATE}/score").status_code == 404


# ── regime snapshot is a no-op stub → snapshot always None ───────────

def test_snapshot_yields_none(setup):
    # The market-board regime snapshot was removed (Task 1.3); the stub returns
    # None and the column is left unpopulated.
    c = TestClient(app); _as(setup)
    r = c.put(f"/api/workflow/plan-cards/{DATE}", json={"max_trades": 2})
    assert r.status_code == 200
    assert r.json()["regime_snapshot"] is None


# ── auth ─────────────────────────────────────────────────────────────

def test_unauthenticated_401(setup):
    # No dependency override → real get_current_user rejects.
    app.dependency_overrides.clear()
    c = TestClient(app)
    assert c.get(f"/api/workflow/plan-cards/{DATE}").status_code == 401
    assert c.put(f"/api/workflow/plan-cards/{DATE}", json={}).status_code == 401


# ── user isolation ───────────────────────────────────────────────────

def test_user_isolation(setup, monkeypatch):
    monkeypatch.setattr(plan_cards_router, "snapshot_regime", lambda: None)
    c = TestClient(app); _as(setup)
    c.put(f"/api/workflow/plan-cards/{DATE}", json={"max_trades": 1})

    other = _user("other@x.com")
    _as(other)
    # Same date, different user → not visible.
    assert c.get(f"/api/workflow/plan-cards/{DATE}").status_code == 404
    assert c.get(f"/api/workflow/plan-cards/{DATE}/score").status_code == 404
    assert c.get("/api/workflow/plan-cards").json() == []


# ── pre-market read + EOD reflection fields ───────────────────────────────────

def test_plan_card_read_and_eod_roundtrip(setup):
    _as(setup)
    c = TestClient(app)
    payload = {
        "htf_bias": "Long", "ltf_bias": "Neutral",
        "expectations": "range until US open",
        "key_levels_buy": "98,200 / 97,400",
        "key_levels_sell": "101,500 / 102,800",
        "did_well": "waited for the level",
        "did_poorly": "sized up on tilt",
        "eod_why": "fomo after a missed move",
    }
    r = c.put(f"/api/workflow/plan-cards/{DATE}", json=payload)
    assert r.status_code == 200, r.text
    body = c.get(f"/api/workflow/plan-cards/{DATE}").json()
    for k, v in payload.items():
        assert body[k] == v


def test_plan_card_eod_partial_update_preserves_morning(setup):
    _as(setup)
    c = TestClient(app)
    c.put(f"/api/workflow/plan-cards/{DATE}",
          json={"htf_bias": "Short", "max_trades": 3, "a_setup_note": "breakout"})
    # later in the day, fill ONLY the EOD fields
    c.put(f"/api/workflow/plan-cards/{DATE}",
          json={"did_well": "patience", "eod_why": "stuck to plan"})
    body = c.get(f"/api/workflow/plan-cards/{DATE}").json()
    assert body["did_well"] == "patience"
    assert body["htf_bias"] == "Short"      # morning fields untouched
    assert body["max_trades"] == 3
    assert body["a_setup_note"] == "breakout"
