import io

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.perps.models import (
    ExchangeAccount, Position, PerpsJournal, Venue, AssetClass, Direction, PositionStatus,
)
from datetime import datetime

KEY = "1:BTCUSDT:cpnl:o1"


def _user(email):
    db = SessionLocal(); u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close(); return u


@pytest.fixture()
def setup():
    init_db()
    db = SessionLocal()
    for M in (PerpsJournal, Position, ExchangeAccount, User):
        db.query(M).delete()
    db.commit()
    u = _user("r2@x.com")
    db = SessionLocal()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="b")
    db.add(acc); db.commit()
    db.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="BTCUSDT",
                    asset_class=AssetClass.PERP, direction=Direction.LONG,
                    status=PositionStatus.CLOSED, opened_at=datetime(2026, 1, 1, 9),
                    closed_at=datetime(2026, 1, 1, 11), avg_entry=100.0, avg_exit=110.0,
                    quantity=1.0, realized_pnl=10.0, total_fees=0.0, total_funding=0.0,
                    position_key=KEY))
    db.commit(); db.close()
    return u


def _as(u): app.dependency_overrides[get_current_user] = lambda: u
def teardown_function(): app.dependency_overrides.clear()


def test_journal_stores_stop_and_targets(setup):
    c = TestClient(app); _as(setup)
    body = {"position_key": KEY, "stop_price": 95.0, "stop_triggered": False,
            "targets": [{"price": 110.0, "pct": 50.0, "triggered": True},
                        {"price": 120.0, "pct": 50.0, "triggered": False}]}
    r = c.put("/api/perps/journal", json=body)
    assert r.status_code == 200
    out = r.json()
    assert out["stop_price"] == 95.0
    assert out["targets"][1]["price"] == 120.0
    assert out["screenshot_path"] is None


def test_journal_rejects_targets_over_100pct(setup):
    c = TestClient(app); _as(setup)
    body = {"position_key": KEY,
            "targets": [{"price": 110.0, "pct": 60.0, "triggered": False},
                        {"price": 120.0, "pct": 50.0, "triggered": False}]}
    r = c.put("/api/perps/journal", json=body)
    assert r.status_code == 422


def test_screenshot_upload_and_bulk(setup):
    c = TestClient(app); _as(setup)
    r = c.post("/api/perps/journal/screenshot", params={"position_key": KEY},
               files={"file": ("chart.png", io.BytesIO(b"fakepng"), "image/png")})
    assert r.status_code == 200
    assert r.json()["path"].endswith(".png")
    # journal row was auto-created and carries the path
    j = c.get("/api/perps/journal", params={"position_key": KEY}).json()
    assert j["screenshot_path"] == r.json()["path"]

    c.put("/api/perps/journal", json={"position_key": KEY, "setup_name": "Breakout", "grade": "A"})
    bulk = c.get("/api/perps/journal/bulk").json()
    assert bulk[KEY] == {"setup_name": "Breakout", "grade": "A"}


def test_screenshot_404_for_foreign_position(setup):
    other = _user("other@x.com")
    c = TestClient(app); _as(other)
    r = c.post("/api/perps/journal/screenshot", params={"position_key": KEY},
               files={"file": ("c.png", io.BytesIO(b"x"), "image/png")})
    assert r.status_code == 404


def test_open_key_journal_allowed_before_snapshot_row(setup):
    # A freshly opened position appears in the cockpit before the next sync
    # writes its Position row — saving a stop on the :open key must work when
    # the account belongs to the user, and 404 for anyone else.
    db = SessionLocal()
    acc_id = db.query(ExchangeAccount).first().id
    db.close()
    c = TestClient(app); _as(setup)
    key = f"{acc_id}:SOLUSDT:open"
    r = c.put("/api/perps/journal", json={"position_key": key, "stop_price": 120.0})
    assert r.status_code == 200
    assert r.json()["stop_price"] == 120.0

    other = _user("intruder@x.com")
    _as(other)
    r2 = c.put("/api/perps/journal", json={"position_key": key, "stop_price": 1.0})
    assert r2.status_code == 404
