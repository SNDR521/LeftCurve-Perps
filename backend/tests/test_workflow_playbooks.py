"""Playbook endpoint tests.

Covers:
- CRUD round-trip (create, read via list, update, delete)
- Duplicate name → 400; same name different user → OK
- GET /playbooks — stats from perps workspace only (Task 1.3: prop coupling removed)
  - Seed a perps CLOSED position (+10 realized) with PerpsJournal.setup_name="Breakout"
    → playbook "Breakout" stats {trade_count: 1, total_pnl: 10.0, win_rate: 100.0}
  - Playbook with no trades → zeros
- GET /playbooks/names
- DELETE leaves perps journals in place
- User isolation + 401

Note: prop-workspace stats merge removed in Task 1.3 (perps-only extraction).
Tests that previously tested prop or cross-workspace aggregation have been
updated to verify perps-only behaviour.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user

from app.workflow.models import Playbook
from app.perps.models import (
    ExchangeAccount, Position, Venue, AssetClass, Direction, PositionStatus,
    OpenedAtSource, PerpsJournal,
)


# ── fixtures / helpers ────────────────────────────────────────────────────────

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
    # Wipe state in dependency order (FK children first).
    for M in (
        PerpsJournal, Position, ExchangeAccount,
        Playbook, User,
    ):
        db.query(M).delete()
    db.commit()
    db.close()
    return _user("pb@x.com")


def _as(u: User):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


# ── perps seeding helpers ─────────────────────────────────────────────────────

def _perps_account(user_id: int) -> int:
    db = SessionLocal()
    acc = ExchangeAccount(user_id=user_id, venue=Venue.BYBIT, label="b")
    db.add(acc)
    db.commit()
    aid = acc.id
    db.close()
    return aid


def _seed_perps_position(user_id: int, acc_id: int, pnl: float,
                         setup_name: str, position_key: str) -> int:
    """Create a closed perps Position and a PerpsJournal row for it."""
    db = SessionLocal()
    now = datetime(2026, 6, 11, 10, 0, 0)
    pos = Position(
        user_id=user_id,
        exchange_account_id=acc_id,
        symbol="BTCUSDT",
        asset_class=AssetClass.PERP,
        direction=Direction.LONG,
        status=PositionStatus.CLOSED,
        opened_at=now - timedelta(hours=1),
        closed_at=now,
        avg_entry=100.0,
        avg_exit=105.0,
        quantity=1.0,
        realized_pnl=pnl,
        total_fees=0.0,
        total_funding=0.0,
        opened_at_source=OpenedAtSource.EXACT,
        position_key=position_key,
    )
    db.add(pos)
    db.commit()
    pos_id = pos.id

    journal = PerpsJournal(
        user_id=user_id,
        position_key=position_key,
        setup_name=setup_name,
    )
    db.add(journal)
    db.commit()
    db.close()
    return pos_id


# ── CRUD round-trip ───────────────────────────────────────────────────────────

def test_create_playbook(setup):
    _as(setup)
    c = TestClient(app)
    r = c.post("/api/workflow/playbooks", json={
        "name": "Breakout",
        "context_requirements": "Above 20MA",
        "entry_triggers": "Break of highs",
        "invalidation": "Close below entry",
        "management": "Trail stop",
        "notes": "Only A+ setups",
    })
    assert r.status_code == 201
    out = r.json()
    assert out["name"] == "Breakout"
    assert out["context_requirements"] == "Above 20MA"
    assert out["stats"] == {"trade_count": 0, "win_rate": 0.0, "total_pnl": 0.0}
    assert "id" in out


def test_list_playbooks_empty(setup):
    _as(setup)
    c = TestClient(app)
    r = c.get("/api/workflow/playbooks")
    assert r.status_code == 200
    assert r.json() == []


def test_update_playbook(setup):
    _as(setup)
    c = TestClient(app)
    pb_id = c.post("/api/workflow/playbooks", json={"name": "VWAP"}).json()["id"]

    r = c.put(f"/api/workflow/playbooks/{pb_id}", json={"notes": "only morning"})
    assert r.status_code == 200
    assert r.json()["notes"] == "only morning"
    assert r.json()["name"] == "VWAP"  # unchanged


def test_delete_playbook(setup):
    _as(setup)
    c = TestClient(app)
    pb_id = c.post("/api/workflow/playbooks", json={"name": "TempSetup"}).json()["id"]

    r = c.delete(f"/api/workflow/playbooks/{pb_id}")
    assert r.status_code == 204

    # Should be gone from the list.
    names = c.get("/api/workflow/playbooks/names").json()
    assert "TempSetup" not in names


def test_delete_404_for_other_user(setup):
    _as(setup)
    c = TestClient(app)
    # Create as user A.
    pb_id = c.post("/api/workflow/playbooks", json={"name": "A-Setup"}).json()["id"]

    # Switch to user B.
    other = _user("other_del@x.com")
    _as(other)
    r = c.delete(f"/api/workflow/playbooks/{pb_id}")
    assert r.status_code == 404


def test_update_404_for_other_user(setup):
    _as(setup)
    c = TestClient(app)
    pb_id = c.post("/api/workflow/playbooks", json={"name": "X"}).json()["id"]

    other = _user("other_upd@x.com")
    _as(other)
    r = c.put(f"/api/workflow/playbooks/{pb_id}", json={"notes": "hack"})
    assert r.status_code == 404


# ── duplicate name → 400 ──────────────────────────────────────────────────────

def test_duplicate_name_returns_400(setup):
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/playbooks", json={"name": "Dup"})
    r = c.post("/api/workflow/playbooks", json={"name": "Dup"})
    assert r.status_code == 400


def test_same_name_different_user_ok(setup):
    """Another user can have a playbook with the same name."""
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/playbooks", json={"name": "SharedName"})

    other = _user("other_dup@x.com")
    _as(other)
    r = c.post("/api/workflow/playbooks", json={"name": "SharedName"})
    assert r.status_code == 201


# ── rename duplicate guard ────────────────────────────────────────────────────

def test_rename_to_existing_name_returns_400(setup):
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/playbooks", json={"name": "Alpha"})
    pb_id = c.post("/api/workflow/playbooks", json={"name": "Beta"}).json()["id"]
    r = c.put(f"/api/workflow/playbooks/{pb_id}", json={"name": "Alpha"})
    assert r.status_code == 400


# ── GET /playbooks/names ──────────────────────────────────────────────────────

def test_names_endpoint_sorted(setup):
    _as(setup)
    c = TestClient(app)
    for name in ("Zebra", "Apple", "Mango"):
        c.post("/api/workflow/playbooks", json={"name": name})

    r = c.get("/api/workflow/playbooks/names")
    assert r.status_code == 200
    assert r.json() == ["Apple", "Mango", "Zebra"]


# ── perps-only stats ──────────────────────────────────────────────────────────

def test_stats_perps_workspace(setup):
    """Seed one perps position (+10) with setup_name='Breakout'.
    Playbook 'Breakout' stats should show trade_count=1, total_pnl=10.0, win_rate=100.0.
    """
    _as(setup)
    c = TestClient(app)

    acc_id = _perps_account(setup.id)
    _seed_perps_position(
        user_id=setup.id, acc_id=acc_id, pnl=10.0,
        setup_name="Breakout", position_key="k:BTCUSDT:2026-06-11"
    )

    # Create the playbook.
    c.post("/api/workflow/playbooks", json={"name": "Breakout"})

    r = c.get("/api/workflow/playbooks")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    stats = rows[0]["stats"]
    assert stats["trade_count"] == 1
    assert abs(stats["total_pnl"] - 10.0) < 0.01
    assert abs(stats["win_rate"] - 100.0) < 0.01


def test_stats_no_trades_returns_zeros(setup):
    """A playbook with no matching trades should return zero stats."""
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/playbooks", json={"name": "EmptySetup"})

    r = c.get("/api/workflow/playbooks")
    assert r.status_code == 200
    stats = r.json()[0]["stats"]
    assert stats["trade_count"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["total_pnl"] == 0.0


def test_stats_multiple_perps_positions(setup):
    """Multiple perps positions with same setup_name are aggregated."""
    _as(setup)
    c = TestClient(app)
    acc_id = _perps_account(setup.id)
    _seed_perps_position(
        user_id=setup.id, acc_id=acc_id, pnl=15.0,
        setup_name="BreakoutMulti", position_key="k:ETHUSDT:2026-06-11a"
    )
    _seed_perps_position(
        user_id=setup.id, acc_id=acc_id, pnl=-5.0,
        setup_name="BreakoutMulti", position_key="k:ETHUSDT:2026-06-11b"
    )
    c.post("/api/workflow/playbooks", json={"name": "BreakoutMulti"})

    r = c.get("/api/workflow/playbooks")
    stats = r.json()[0]["stats"]
    assert stats["trade_count"] == 2
    assert abs(stats["total_pnl"] - 10.0) < 0.01
    assert abs(stats["win_rate"] - 50.0) < 0.01


# ── DELETE leaves journals intact ─────────────────────────────────────────────

def test_delete_leaves_perps_journal_intact(setup):
    """Deleting a playbook does NOT remove PerpsJournal entries."""
    _as(setup)
    c = TestClient(app)
    acc_id = _perps_account(setup.id)
    _seed_perps_position(
        user_id=setup.id, acc_id=acc_id, pnl=10.0,
        setup_name="Breakout", position_key="k:BTC:del-test"
    )
    pb_id = c.post("/api/workflow/playbooks", json={"name": "Breakout"}).json()["id"]
    c.delete(f"/api/workflow/playbooks/{pb_id}")

    # Journal row should still be in the DB.
    db = SessionLocal()
    j = db.query(PerpsJournal).filter(
        PerpsJournal.user_id == setup.id, PerpsJournal.position_key == "k:BTC:del-test"
    ).first()
    db.close()
    assert j is not None
    assert j.setup_name == "Breakout"


# ── auth ──────────────────────────────────────────────────────────────────────

def test_unauthenticated_401(setup):
    app.dependency_overrides.clear()
    c = TestClient(app)
    assert c.get("/api/workflow/playbooks").status_code == 401
    assert c.get("/api/workflow/playbooks/names").status_code == 401
    assert c.post("/api/workflow/playbooks", json={"name": "X"}).status_code == 401
    assert c.put("/api/workflow/playbooks/1", json={}).status_code == 401
    assert c.delete("/api/workflow/playbooks/1").status_code == 401


# ── user isolation ────────────────────────────────────────────────────────────

def test_user_isolation(setup):
    """Each user only sees their own playbooks."""
    _as(setup)
    c = TestClient(app)
    c.post("/api/workflow/playbooks", json={"name": "MySetup"})

    other = _user("iso@x.com")
    _as(other)
    assert c.get("/api/workflow/playbooks").json() == []
    assert c.get("/api/workflow/playbooks/names").json() == []
