import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.perps.models import Position, PerpsJournal, PerpsTag, Direction, PositionStatus, AssetClass


def _user(email):
    db = SessionLocal(); u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close(); return u


KEY = "1:BTCUSDT:2024-01-01T00:00:00+00:00"


@pytest.fixture()
def ctx():
    init_db()
    db = SessionLocal()
    for M in (PerpsJournal, PerpsTag, Position, User): db.query(M).delete()
    db.commit()
    a, b = _user("a@x.com"), _user("b@x.com")
    db = SessionLocal()
    db.add(Position(user_id=a.id, exchange_account_id=1, symbol="BTCUSDT", asset_class=AssetClass.PERP,
                    direction=Direction.LONG, status=PositionStatus.CLOSED, avg_entry=100, avg_exit=110,
                    quantity=1, realized_pnl=10, total_fees=0, total_funding=0,
                    opened_at=datetime(2024,1,1,tzinfo=timezone.utc), closed_at=datetime(2024,1,1,1,tzinfo=timezone.utc),
                    position_key=KEY))
    db.commit(); db.close()
    return a, b


def _as(u): app.dependency_overrides[get_current_user] = lambda: u
def teardown_function(): app.dependency_overrides.clear()


def test_journal_upsert_and_get(ctx):
    a, b = ctx
    c = TestClient(app); _as(a)
    r = c.put("/api/perps/journal", json={"position_key": KEY, "setup_name": "Breakout", "grade": "A",
                                          "mistake_tags": ["fomo"], "notes": "clean"})
    assert r.status_code == 200 and r.json()["setup_name"] == "Breakout"
    got = c.get("/api/perps/journal", params={"position_key": KEY}).json()
    assert got["grade"] == "A" and got["mistake_tags"] == ["fomo"]
    c.put("/api/perps/journal", json={"position_key": KEY, "grade": "B"})
    assert c.get("/api/perps/journal", params={"position_key": KEY}).json()["grade"] == "B"
    db = SessionLocal(); assert db.query(PerpsJournal).count() == 1; db.close()


def test_journal_rejects_unknown_position_key(ctx):
    a, b = ctx
    c = TestClient(app); _as(a)
    assert c.put("/api/perps/journal", json={"position_key": "9:NOPE:x", "grade": "A"}).status_code == 404


def test_journal_isolation(ctx):
    a, b = ctx
    c = TestClient(app); _as(a)
    c.put("/api/perps/journal", json={"position_key": KEY, "grade": "A"})
    _as(b)
    assert c.put("/api/perps/journal", json={"position_key": KEY, "grade": "Z"}).status_code == 404
    assert c.get("/api/perps/journal", params={"position_key": KEY}).json() in (None, {})


def test_tags_create_attach_detach(ctx):
    a, b = ctx
    c = TestClient(app); _as(a)
    tag = c.post("/api/perps/journal/tags", json={"name": "scalp", "color": "#38bdf8"}).json()
    assert c.get("/api/perps/journal/tags").json()[0]["name"] == "scalp"
    assert c.post("/api/perps/journal/tag-link", json={"position_key": KEY, "tag_id": tag["id"]}).status_code == 200
    assert tag["id"] in c.get("/api/perps/journal", params={"position_key": KEY}).json()["tag_ids"]
    assert c.post("/api/perps/journal/tag-unlink", json={"position_key": KEY, "tag_id": tag["id"]}).status_code == 200
