import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.models import User
from app.core.deps import get_current_user
from app.perps.models import (
    ExchangeAccount, Fill, Position, PositionFill, PositionStatus,
    PerpsJournal, PerpsTag, perps_position_tags,
    Venue, AssetClass, Side, Direction, OpenedAtSource,
)
from datetime import datetime, timezone


def _dt(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest.fixture()
def setup():
    init_db()
    db = SessionLocal()
    db.execute(perps_position_tags.delete())
    for M in (PerpsTag, PositionFill, PerpsJournal, Position, Fill, ExchangeAccount, User):
        db.query(M).delete()
    db.commit()

    a = User(email="detail_a@x.com", password_hash="x")
    b = User(email="detail_b@x.com", password_hash="x")
    db.add(a); db.add(b); db.commit()
    db.refresh(a); db.refresh(b)

    acc = ExchangeAccount(user_id=a.id, venue=Venue.BYBIT, label="main")
    db.add(acc); db.commit(); db.refresh(acc)

    # Main closed position
    pos = Position(
        user_id=a.id,
        exchange_account_id=acc.id,
        symbol="BTCUSDT",
        asset_class=AssetClass.PERP,
        direction=Direction.LONG,
        status=PositionStatus.CLOSED,
        opened_at=_dt("2026-01-01T09:00:00"),
        closed_at=_dt("2026-01-01T11:00:00"),
        avg_entry=100.0,
        avg_exit=110.0,
        quantity=1.0,
        realized_pnl=10.0,
        total_fees=0.0,
        total_funding=-0.5,
        r_multiple=None,
        duration_seconds=7200,
        position_key="1:BTCUSDT:cpnl:oc",
        opened_at_source=OpenedAtSource.EXACT,
    )
    db.add(pos); db.commit(); db.refresh(pos)
    position_id = pos.id

    # Bare position (no fills, no journal)
    bare = Position(
        user_id=a.id,
        exchange_account_id=acc.id,
        symbol="ETHUSDT",
        asset_class=AssetClass.PERP,
        direction=Direction.LONG,
        status=PositionStatus.CLOSED,
        opened_at=_dt("2026-01-02T09:00:00"),
        closed_at=_dt("2026-01-02T11:00:00"),
        avg_entry=200.0,
        avg_exit=220.0,
        quantity=1.0,
        realized_pnl=20.0,
        total_fees=0.0,
        total_funding=0.0,
        r_multiple=None,
        duration_seconds=7200,
        position_key="1:ETHUSDT:cpnl:ox",
        opened_at_source=OpenedAtSource.EXACT,
    )
    db.add(bare); db.commit(); db.refresh(bare)
    bare_id = bare.id

    # Three fills for user a
    fill_buy = Fill(
        user_id=a.id,
        exchange_account_id=acc.id,
        venue=Venue.BYBIT,
        symbol="BTCUSDT",
        asset_class=AssetClass.PERP,
        side=Side.BUY,
        price=100.0,
        quantity=1.0,
        fee=0.0,
        executed_at=_dt("2026-01-01T09:00:00"),
        order_id="o1",
        external_fill_id="e1",
    )
    fill_sell = Fill(
        user_id=a.id,
        exchange_account_id=acc.id,
        venue=Venue.BYBIT,
        symbol="BTCUSDT",
        asset_class=AssetClass.PERP,
        side=Side.SELL,
        price=110.0,
        quantity=1.0,
        fee=0.0,
        executed_at=_dt("2026-01-01T11:00:00"),
        order_id="oc",
        external_fill_id="e2",
    )
    fill_funding = Fill(
        user_id=a.id,
        exchange_account_id=acc.id,
        venue=Venue.BYBIT,
        symbol="BTCUSDT",
        asset_class=AssetClass.PERP,
        side=Side.BUY,
        price=0.0,
        quantity=0.0,
        fee=0.0,
        funding_amount=-0.5,
        executed_at=_dt("2026-01-01T10:00:00"),
        external_fill_id="funding:1",
    )
    db.add(fill_buy); db.add(fill_sell); db.add(fill_funding)
    db.commit()
    db.refresh(fill_buy); db.refresh(fill_sell); db.refresh(fill_funding)

    # Link fills to position
    for fid in (fill_buy.id, fill_sell.id, fill_funding.id):
        db.add(PositionFill(position_id=position_id, fill_id=fid))
    db.commit()

    # Journal for user a
    journal = PerpsJournal(
        user_id=a.id,
        position_key="1:BTCUSDT:cpnl:oc",
        stop_price=95.0,
    )
    db.add(journal); db.commit()

    db.refresh(a); db.refresh(b)
    db.expunge(a); db.expunge(b)
    db.close()
    return a, b, position_id, bare_id


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


def test_detail_returns_position_journal_fills_risk(setup):
    a, b, pid, bare_id = setup
    c = TestClient(app)
    _as(a)
    r = c.get(f"/api/perps/positions/{pid}/detail")
    assert r.status_code == 200
    body = r.json()
    assert body["position"]["id"] == pid
    assert body["journal"]["stop_price"] == 95.0
    times = [f["executed_at"] for f in body["fills"]]
    assert times == sorted(times)
    assert [f["is_funding"] for f in body["fills"]] == [False, True, False]
    assert body["fills"][0]["order_id"] == "o1"
    assert body["risk"]["actual_r"] == pytest.approx(2.0)
    assert body["risk"]["risk_source"] == "stop"


def test_detail_404_for_other_user(setup):
    a, b, pid, bare_id = setup
    c = TestClient(app)
    _as(b)
    assert c.get(f"/api/perps/positions/{pid}/detail").status_code == 404


def test_detail_works_without_journal_or_fills(setup):
    a, b, pid, bare_id = setup
    c = TestClient(app)
    _as(a)
    body = c.get(f"/api/perps/positions/{bare_id}/detail").json()
    assert body["journal"] is None
    assert body["fills"] == []
    assert body["risk"]["planned_rr"] is None


def test_detail_surfaces_tags_without_journal_row(setup):
    # Tags can be linked before any journal exists; the detail response must
    # still expose them (mirrors GET /journal fallback).
    a, b, pid, bare_id = setup
    db = SessionLocal()
    t = PerpsTag(user_id=a.id, name="momo")
    db.add(t); db.commit(); db.refresh(t)
    db.execute(perps_position_tags.insert().values(
        user_id=a.id, position_key="1:ETHUSDT:cpnl:ox", tag_id=t.id))
    db.commit(); tag_id = t.id; db.close()

    c = TestClient(app)
    _as(a)
    body = c.get(f"/api/perps/positions/{bare_id}/detail").json()
    assert body["journal"]["tag_ids"] == [tag_id]


# --- key-based /detail?key= endpoint tests ---

def test_detail_by_key_resolves_position(setup):
    """GET /positions/detail?key= returns the position for a valid position_key."""
    a, b, pid, bare_id = setup
    c = TestClient(app)
    _as(a)
    r = c.get("/api/perps/positions/detail?key=1:BTCUSDT:cpnl:oc")
    assert r.status_code == 200
    body = r.json()
    assert body["position"]["id"] == pid
    assert body["position"]["symbol"] == "BTCUSDT"
    assert body["journal"]["stop_price"] == 95.0


def test_detail_by_key_id_churn_survival(setup):
    """After a sync deletes and re-inserts a position (new numeric id), the
    old numeric id returns 404 but the stable position_key still resolves."""
    a, b, pid, bare_id = setup
    # Simulate id churn: delete and recreate with same position_key
    db = SessionLocal()
    old_pos = db.query(Position).filter(Position.id == pid).first()
    old_key = old_pos.position_key
    db.execute(perps_position_tags.delete())
    db.query(PositionFill).filter(PositionFill.position_id == pid).delete()
    db.query(Position).filter(Position.id == pid).delete()
    db.commit()
    # Re-insert with a new (auto-assigned) id
    new_pos = Position(
        user_id=a.id, exchange_account_id=old_pos.exchange_account_id,
        symbol="BTCUSDT", asset_class=AssetClass.PERP,
        direction=Direction.LONG, status=PositionStatus.CLOSED,
        opened_at=_dt("2026-01-01T09:00:00"), closed_at=_dt("2026-01-01T11:00:00"),
        avg_entry=100.0, avg_exit=110.0, quantity=1.0, realized_pnl=10.0,
        total_fees=0.0, total_funding=-0.5, duration_seconds=7200,
        position_key=old_key, opened_at_source=OpenedAtSource.EXACT,
    )
    db.add(new_pos); db.commit(); db.refresh(new_pos)
    new_id = new_pos.id
    db.close()

    c = TestClient(app)
    _as(a)
    # Old numeric id is gone -> 404
    assert c.get(f"/api/perps/positions/{pid}/detail").status_code == 404
    # Stable key still resolves with the new id
    r = c.get(f"/api/perps/positions/detail?key={old_key}")
    assert r.status_code == 200
    assert r.json()["position"]["id"] == new_id


def test_detail_by_key_unknown_key_404(setup):
    """An unknown position_key returns 404."""
    a, b, pid, bare_id = setup
    c = TestClient(app)
    _as(a)
    assert c.get("/api/perps/positions/detail?key=no:such:key").status_code == 404


def test_detail_by_key_user_scoping(setup):
    """User b cannot access user a's position by key."""
    a, b, pid, bare_id = setup
    c = TestClient(app)
    _as(b)
    assert c.get("/api/perps/positions/detail?key=1:BTCUSDT:cpnl:oc").status_code == 404
