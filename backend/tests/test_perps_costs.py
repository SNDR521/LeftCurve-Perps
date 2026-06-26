"""Tests for funding/fees/leverage cost analytics (service + endpoints).

Service tests use the standard tmp-engine fixture pattern (s, u, acc) from
test_perps_mfe.py so each test runs against a fresh in-memory SQLite DB.

Endpoint tests follow test_perps_positions.py style: init_db / SessionLocal /
dependency-override via _as().
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import Base, make_engine, init_db, SessionLocal
from app.core.models import User
from app.core.security import hash_password
from app.core.deps import get_current_user
from app.main import app
from app.perps.models import (
    ExchangeAccount, Fill, Position, BalanceSnapshot,
    Venue, AssetClass, Side, Direction, PositionStatus, OpenedAtSource,
)
from app.perps.services.costs import (
    compute_funding, compute_fees, compute_leverage, compute_equity, TAKER_BPS, MAKER_BPS,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

T_JAN = datetime(2026, 1, 15, 12, 0, 0)
T_FEB = datetime(2026, 2, 15, 12, 0, 0)


# ---------------------------------------------------------------------------
# tmp-engine fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="cost@test.com", password_hash=hash_password("x"))
    s.add(u); s.commit()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="main")
    s.add(acc); s.commit()
    yield s, u, acc
    s.close()


def _funding_fill(s, u, acc, symbol, amount, executed_at):
    """Seed a funding fill: qty=0, funding_amount=amount."""
    f = Fill(
        user_id=u.id,
        exchange_account_id=acc.id,
        venue=Venue.BYBIT,
        symbol=symbol,
        asset_class=AssetClass.PERP,
        side=Side.BUY,
        price=0.0,
        quantity=0.0,
        fee=0.0,
        funding_amount=amount,
        executed_at=executed_at,
    )
    s.add(f); s.commit()
    return f


def _trade_fill(s, u, acc, symbol, fee, is_maker, executed_at=None, raw_override=None):
    """Seed a trade fill: qty=1, with fee and raw isMaker flag."""
    if raw_override is not None:
        raw = raw_override
    else:
        raw = {"isMaker": is_maker}
    f = Fill(
        user_id=u.id,
        exchange_account_id=acc.id,
        venue=Venue.BYBIT,
        symbol=symbol,
        asset_class=AssetClass.PERP,
        side=Side.BUY,
        price=100.0,
        quantity=1.0,
        fee=fee,
        executed_at=executed_at or T_JAN,
        raw=raw,
    )
    s.add(f); s.commit()
    return f


def _closed_position(s, u, acc, symbol, realized_pnl, leverage=None, position_key=None):
    """Seed a CLOSED position."""
    p = Position(
        user_id=u.id,
        exchange_account_id=acc.id,
        symbol=symbol,
        asset_class=AssetClass.PERP,
        direction=Direction.LONG,
        status=PositionStatus.CLOSED,
        opened_at=T_JAN,
        closed_at=T_FEB,
        avg_entry=100.0,
        avg_exit=110.0,
        quantity=1.0,
        realized_pnl=realized_pnl,
        total_fees=0.0,
        total_funding=0.0,
        opened_at_source=OpenedAtSource.EXACT,
        leverage=leverage,
        position_key=position_key or f"key:{symbol}:{realized_pnl}",
    )
    s.add(p); s.commit()
    return p


# ===========================================================================
# test_compute_funding
# ===========================================================================

def test_compute_funding(db):
    s, u, acc = db
    # funding fills: ETH -10 (Jan), ETH +2 (Feb), OM -50 (Feb)
    _funding_fill(s, u, acc, "ETHUSDT", -10.0, T_JAN)
    _funding_fill(s, u, acc, "ETHUSDT", +2.0, T_FEB)
    _funding_fill(s, u, acc, "OMUSDT", -50.0, T_FEB)
    # one winner: gross profit 200
    _closed_position(s, u, acc, "ETHUSDT", realized_pnl=200.0, position_key="eth:1")
    # one loser — should NOT count toward gross
    _closed_position(s, u, acc, "OMUSDT", realized_pnl=-50.0, position_key="om:1")

    out = compute_funding(s, acc.id, u.id)

    assert out["total_paid"] == pytest.approx(-60.0)
    assert out["total_received"] == pytest.approx(2.0)
    assert out["net"] == pytest.approx(-58.0)
    assert out["pct_of_gross"] == pytest.approx(29.0)   # 58 / 200 * 100

    # by_symbol sorted net ascending (worst first)
    assert out["by_symbol"][0]["symbol"] == "OMUSDT"
    assert out["by_symbol"][0]["net"] == pytest.approx(-50.0)

    months = {m["month"]: m["net"] for m in out["by_month"]}
    assert months["2026-01"] == pytest.approx(-10.0)
    assert months["2026-02"] == pytest.approx(-48.0)


def test_compute_funding_no_gross(db):
    """pct_of_gross is None when there are no winning positions."""
    s, u, acc = db
    _funding_fill(s, u, acc, "BTCUSDT", -5.0, T_JAN)
    _closed_position(s, u, acc, "BTCUSDT", realized_pnl=-100.0, position_key="btc:loss")

    out = compute_funding(s, acc.id, u.id)
    assert out["pct_of_gross"] is None


def test_compute_funding_empty(db):
    """No funding fills → zeroes, empty lists."""
    s, u, acc = db
    out = compute_funding(s, acc.id, u.id)
    assert out["total_paid"] == pytest.approx(0.0)
    assert out["total_received"] == pytest.approx(0.0)
    assert out["net"] == pytest.approx(0.0)
    assert out["pct_of_gross"] is None
    assert out["by_symbol"] == []
    assert out["by_month"] == []


# ===========================================================================
# test_compute_fees
# ===========================================================================

def test_compute_fees(db):
    s, u, acc = db
    # 3 taker fills fee 1.0 each, 1 maker fill fee 0.2
    for _ in range(3):
        _trade_fill(s, u, acc, "BTCUSDT", fee=1.0, is_maker=False)
    _trade_fill(s, u, acc, "BTCUSDT", fee=0.2, is_maker=True)
    # gross profit 200 from one closed BTC position; 2 closed positions total
    _closed_position(s, u, acc, "BTCUSDT", realized_pnl=200.0, position_key="btc:w1")
    _closed_position(s, u, acc, "BTCUSDT", realized_pnl=-10.0, position_key="btc:l1")

    out = compute_fees(s, acc.id, u.id)

    assert out["total"] == pytest.approx(3.2)
    assert out["taker_fees"] == pytest.approx(3.0)
    assert out["maker_fees"] == pytest.approx(0.2)
    assert out["taker_share_pct"] == pytest.approx(75.0)   # 3 taker / 4 total fills
    assert out["pct_of_gross"] == pytest.approx(1.6)        # 3.2 / 200 * 100
    assert out["maker_savings_estimate"] == pytest.approx(
        3.0 * (TAKER_BPS - MAKER_BPS) / TAKER_BPS
    )
    sym = {r["symbol"]: r for r in out["by_symbol"]}
    assert sym["BTCUSDT"]["round_trip_cost"] == pytest.approx(3.2 / 2)


def test_compute_fees_missing_raw_counts_as_taker(db):
    """Fill with raw=None is treated as taker (conservative)."""
    s, u, acc = db
    _trade_fill(s, u, acc, "ETHUSDT", fee=1.0, is_maker=False, raw_override=None)

    out = compute_fees(s, acc.id, u.id)
    assert out["taker_fees"] == pytest.approx(1.0)
    assert out["maker_fees"] == pytest.approx(0.0)
    assert out["taker_share_pct"] == pytest.approx(100.0)


def test_compute_fees_isMaker_false_key_missing_counts_as_taker(db):
    """raw={} (no isMaker key) → taker."""
    s, u, acc = db
    _trade_fill(s, u, acc, "SOLUSDT", fee=0.5, is_maker=False, raw_override={})

    out = compute_fees(s, acc.id, u.id)
    assert out["taker_fees"] == pytest.approx(0.5)
    assert out["maker_fees"] == pytest.approx(0.0)


def test_compute_fees_empty(db):
    """No trade fills → all zeroes."""
    s, u, acc = db
    out = compute_fees(s, acc.id, u.id)
    assert out["total"] == pytest.approx(0.0)
    assert out["taker_share_pct"] == pytest.approx(0.0)
    assert out["maker_savings_estimate"] == pytest.approx(0.0)
    assert out["by_symbol"] == []


# ===========================================================================
# test_compute_leverage
# ===========================================================================

def test_compute_leverage(db):
    s, u, acc = db
    # lev 2 (+10), lev 12 (-5), lev None (+1)
    _closed_position(s, u, acc, "BTCUSDT", realized_pnl=10.0, leverage=2.0, position_key="btc:lev2")
    _closed_position(s, u, acc, "ETHUSDT", realized_pnl=-5.0, leverage=12.0, position_key="eth:lev12")
    _closed_position(s, u, acc, "SOLUSDT", realized_pnl=1.0, leverage=None, position_key="sol:nolev")

    out = compute_leverage(s, acc.id, u.id)
    b = {r["bucket"]: r for r in out["buckets"]}

    assert b["≤3x"]["trade_count"] == 1
    assert b["≤3x"]["win_rate"] == pytest.approx(100.0)
    assert b["≤3x"]["total_pnl"] == pytest.approx(10.0)

    assert b["10–20x"]["trade_count"] == 1
    assert b["10–20x"]["win_rate"] == pytest.approx(0.0)

    assert b["unknown"]["trade_count"] == 1

    # all non-empty buckets must have avg_pnl
    assert all(r["trade_count"] == 0 or "avg_pnl" in r for r in out["buckets"])


def test_compute_leverage_all_buckets_present(db):
    """All six buckets (5 named + unknown) are always returned, even when empty."""
    s, u, acc = db
    out = compute_leverage(s, acc.id, u.id)
    labels = {r["bucket"] for r in out["buckets"]}
    assert labels == {"≤3x", "3–5x", "5–10x", "10–20x", ">20x", "unknown"}
    assert len(out["buckets"]) == 6


def test_compute_leverage_empty_bucket_no_avg_pnl(db):
    """Empty buckets must not have avg_pnl key."""
    s, u, acc = db
    out = compute_leverage(s, acc.id, u.id)
    for r in out["buckets"]:
        if r["trade_count"] == 0:
            assert "avg_pnl" not in r


def test_compute_leverage_bucket_order(db):
    """Buckets come back in declaration order with unknown last."""
    s, u, acc = db
    out = compute_leverage(s, acc.id, u.id)
    labels = [r["bucket"] for r in out["buckets"]]
    assert labels == ["≤3x", "3–5x", "5–10x", "10–20x", ">20x", "unknown"]


# ===========================================================================
# Endpoint tests
# ===========================================================================

def _user_ep(email):
    db = SessionLocal()
    u = User(email=email, password_hash="x")
    db.add(u); db.commit(); db.refresh(u); db.expunge(u); db.close()
    return u


@pytest.fixture()
def ep_setup():
    init_db()
    db = SessionLocal()
    for M in (BalanceSnapshot, Position, Fill, ExchangeAccount, User):
        db.query(M).delete()
    db.commit(); db.close()
    a = _user_ep("cost_a@x.com")
    b = _user_ep("cost_b@x.com")
    db = SessionLocal()
    acc_a = ExchangeAccount(user_id=a.id, venue=Venue.BYBIT, label="main_a")
    acc_b = ExchangeAccount(user_id=b.id, venue=Venue.BYBIT, label="main_b")
    db.add(acc_a); db.add(acc_b); db.commit()
    db.refresh(acc_a); db.refresh(acc_b)
    db.expunge(acc_a); db.expunge(acc_b)
    db.close()
    return a, b, acc_a, acc_b


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


def test_cost_endpoints_shape_and_auth(ep_setup):
    """GET /funding, /fees, /leverage return 200 when authed, 401 when not."""
    a, b, acc_a, acc_b = ep_setup
    c = TestClient(app)
    _as(a)
    for path in ("/api/perps/analytics/funding",
                 "/api/perps/analytics/fees",
                 "/api/perps/analytics/leverage"):
        resp = c.get(path)
        assert resp.status_code == 200, f"{path} returned {resp.status_code}"

    app.dependency_overrides.clear()
    for path in ("/api/perps/analytics/funding",
                 "/api/perps/analytics/fees",
                 "/api/perps/analytics/leverage"):
        assert c.get(path).status_code == 401


def test_cost_endpoints_funding_shape(ep_setup):
    a, b, acc_a, acc_b = ep_setup
    c = TestClient(app); _as(a)
    body = c.get("/api/perps/analytics/funding").json()
    assert set(body) >= {"total_paid", "total_received", "net", "pct_of_gross",
                         "by_symbol", "by_month"}


def test_cost_endpoints_fees_shape(ep_setup):
    a, b, acc_a, acc_b = ep_setup
    c = TestClient(app); _as(a)
    body = c.get("/api/perps/analytics/fees").json()
    assert set(body) >= {"total", "taker_fees", "maker_fees", "taker_share_pct",
                         "pct_of_gross", "maker_savings_estimate", "by_symbol"}


def test_cost_endpoints_leverage_shape(ep_setup):
    a, b, acc_a, acc_b = ep_setup
    c = TestClient(app); _as(a)
    body = c.get("/api/perps/analytics/leverage").json()
    assert "buckets" in body
    assert len(body["buckets"]) == 6


def test_cost_endpoints_account_id_filter(ep_setup):
    """account_id query param filters to only that account's data."""
    a, b, acc_a, acc_b = ep_setup
    db = SessionLocal()
    # seed funding fill for acc_a
    db.add(Fill(
        user_id=a.id, exchange_account_id=acc_a.id,
        venue=Venue.BYBIT, symbol="BTCUSDT", asset_class=AssetClass.PERP,
        side=Side.BUY, price=0.0, quantity=0.0, fee=0.0,
        funding_amount=-20.0, executed_at=T_JAN,
    ))
    # seed a second account for user a (no fills on it)
    acc_a2 = ExchangeAccount(user_id=a.id, venue=Venue.BYBIT, label="alt_a")
    db.add(acc_a2); db.commit(); db.refresh(acc_a2)
    db.close()

    c = TestClient(app); _as(a)
    # filtered to acc_a → should see -20
    resp = c.get(f"/api/perps/analytics/funding?account_id={acc_a.id}")
    body = resp.json()
    assert body["total_paid"] == pytest.approx(-20.0)
    # filtered to acc_a2 → no fills → net 0
    resp2 = c.get(f"/api/perps/analytics/funding?account_id={acc_a2.id}")
    assert resp2.json()["net"] == pytest.approx(0.0)


def test_cost_endpoints_user_isolation(ep_setup):
    """User b cannot see user a's data."""
    a, b, acc_a, acc_b = ep_setup
    db = SessionLocal()
    db.add(Fill(
        user_id=a.id, exchange_account_id=acc_a.id,
        venue=Venue.BYBIT, symbol="BTCUSDT", asset_class=AssetClass.PERP,
        side=Side.BUY, price=0.0, quantity=0.0, fee=0.0,
        funding_amount=-100.0, executed_at=T_JAN,
    ))
    db.commit(); db.close()

    c = TestClient(app); _as(b)
    body = c.get("/api/perps/analytics/funding").json()
    assert body["net"] == pytest.approx(0.0)   # b sees nothing


# ===========================================================================
# test_compute_equity  (service)
# ===========================================================================

def test_compute_equity(db):
    s, u, acc = db
    d1, d2, d3 = (datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 3))
    for ts, bal in ((d1, 1000.0), (d2, 1200.0), (d3, 1100.0)):
        s.add(BalanceSnapshot(user_id=u.id, exchange_account_id=acc.id,
                              ts=ts, balance=bal, kind="SNAPSHOT"))
    s.add(BalanceSnapshot(user_id=u.id, exchange_account_id=acc.id,
                          ts=datetime(2026, 1, 2, 14, 30), balance=1150.0, kind="TRANSFER_IN"))
    s.commit()
    out = compute_equity(s, acc.id, u.id)
    assert [p["balance"] for p in out["points"]] == [1000.0, 1200.0, 1100.0]
    assert [p["date"] for p in out["points"]] == ["2026-01-01", "2026-01-02", "2026-01-03"]
    assert len(out["transfers"]) == 1
    assert out["transfers"][0]["kind"] == "TRANSFER_IN"
    assert out["transfers"][0]["balance"] == 1150.0
    st = out["stats"]
    assert st["peak"] == 1200.0
    assert st["current"] == 1100.0
    assert st["drawdown_from_peak_pct"] == pytest.approx(100 * 100 / 1200)
    assert st["days_since_high"] == (datetime.now(timezone.utc).date() - d2.date()).days


def test_compute_equity_empty(db):
    s, u, acc = db
    out = compute_equity(s, acc.id, u.id)
    assert out == {"points": [], "transfers": [], "stats": None}


# ===========================================================================
# test_equity_endpoint  (HTTP)
# ===========================================================================

def test_equity_endpoint(ep_setup):
    """GET /api/perps/reports/equity:
    - 200 with correct shape when authenticated
    - 401 when unauthenticated
    - account_id filter: only the matching account's SNAPSHOT points are returned
    """
    a, b, acc_a, acc_b = ep_setup
    db = SessionLocal()
    d1 = datetime(2026, 3, 1)
    d2 = datetime(2026, 3, 2)
    # 2 snapshots for acc_a
    db.add(BalanceSnapshot(user_id=a.id, exchange_account_id=acc_a.id,
                           ts=d1, balance=5000.0, kind="SNAPSHOT"))
    db.add(BalanceSnapshot(user_id=a.id, exchange_account_id=acc_a.id,
                           ts=d2, balance=5500.0, kind="SNAPSHOT"))
    # 1 snapshot for acc_b (different user) — must NOT appear in a's results
    db.add(BalanceSnapshot(user_id=b.id, exchange_account_id=acc_b.id,
                           ts=d1, balance=9999.0, kind="SNAPSHOT"))
    db.commit(); db.close()

    c = TestClient(app)

    # unauthenticated → 401
    app.dependency_overrides.clear()
    assert c.get("/api/perps/reports/equity").status_code == 401

    # authenticated, no account_id filter → sees own two snapshots
    _as(a)
    resp = c.get("/api/perps/reports/equity")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"points", "transfers", "stats"}
    assert len(body["points"]) == 2
    assert body["stats"]["peak"] == pytest.approx(5500.0)
    assert body["stats"]["current"] == pytest.approx(5500.0)

    # account_id filter → only acc_a's data
    resp2 = c.get(f"/api/perps/reports/equity?account_id={acc_a.id}")
    assert resp2.status_code == 200
    pts2 = resp2.json()["points"]
    assert len(pts2) == 2
    assert [p["balance"] for p in pts2] == [5000.0, 5500.0]

    # account_id for acc_b while authenticated as a → a has no rows for acc_b → empty
    resp3 = c.get(f"/api/perps/reports/equity?account_id={acc_b.id}")
    assert resp3.status_code == 200
    assert resp3.json() == {"points": [], "transfers": [], "stats": None}


def test_leverage_boundaries(db):
    # lev exactly 3.0 lands in the <=3x bucket; lev 0.0 (sync sentinel) is unknown
    s, u, acc = db
    _closed_position(s, u, acc, "AUSDT", realized_pnl=5.0, leverage=3.0, position_key="a:b1")
    _closed_position(s, u, acc, "BUSDT", realized_pnl=5.0, leverage=0.0, position_key="b:b2")
    out = compute_leverage(s, acc.id, u.id)
    b = {r["bucket"]: r for r in out["buckets"]}
    assert b["≤3x"]["trade_count"] == 1
    assert b["unknown"]["trade_count"] == 1


# ===========================================================================
# Date-window tests  (Part A — these should FAIL before the fix)
# ===========================================================================

T_IN = datetime(2026, 3, 15, 12, 0, 0)   # inside  2026-03-01 → 2026-03-31
T_OUT = datetime(2026, 1, 5, 12, 0, 0)   # outside that window


def test_compute_funding_date_window(db):
    """compute_funding with from_date/to_date only counts fills inside the window."""
    s, u, acc = db
    _funding_fill(s, u, acc, "BTCUSDT", -30.0, T_IN)   # inside → should count
    _funding_fill(s, u, acc, "BTCUSDT", -10.0, T_OUT)  # outside → must be excluded

    out = compute_funding(s, acc.id, u.id, from_date="2026-03-01", to_date="2026-03-31")

    assert out["total_paid"] == pytest.approx(-30.0), (
        f"Expected only the in-window fill (-30), got {out['total_paid']}"
    )


def test_compute_fees_date_window(db):
    """compute_fees with from_date/to_date only counts fills inside the window."""
    s, u, acc = db
    _trade_fill(s, u, acc, "BTCUSDT", fee=5.0, is_maker=False, executed_at=T_IN)   # inside
    _trade_fill(s, u, acc, "BTCUSDT", fee=2.0, is_maker=False, executed_at=T_OUT)  # outside

    out = compute_fees(s, acc.id, u.id, from_date="2026-03-01", to_date="2026-03-31")

    assert out["total"] == pytest.approx(5.0), (
        f"Expected only the in-window fill (fee=5), got {out['total']}"
    )


def test_compute_leverage_date_window(db):
    """compute_leverage with from_date/to_date only buckets positions closed inside the window."""
    s, u, acc = db

    # position closed inside window
    p_in = Position(
        user_id=u.id, exchange_account_id=acc.id,
        symbol="BTCUSDT", asset_class=AssetClass.PERP,
        direction=Direction.LONG, status=PositionStatus.CLOSED,
        opened_at=T_IN, closed_at=T_IN,
        avg_entry=100.0, avg_exit=110.0, quantity=1.0,
        realized_pnl=10.0, total_fees=0.0, total_funding=0.0,
        opened_at_source=OpenedAtSource.EXACT,
        leverage=5.0, position_key="btc:in",
    )
    # position closed outside window
    p_out = Position(
        user_id=u.id, exchange_account_id=acc.id,
        symbol="ETHUSDT", asset_class=AssetClass.PERP,
        direction=Direction.LONG, status=PositionStatus.CLOSED,
        opened_at=T_OUT, closed_at=T_OUT,
        avg_entry=50.0, avg_exit=55.0, quantity=1.0,
        realized_pnl=5.0, total_fees=0.0, total_funding=0.0,
        opened_at_source=OpenedAtSource.EXACT,
        leverage=15.0, position_key="eth:out",
    )
    s.add(p_in); s.add(p_out); s.commit()

    out = compute_leverage(s, acc.id, u.id, from_date="2026-03-01", to_date="2026-03-31")
    b = {r["bucket"]: r for r in out["buckets"]}

    # 5x lands in 3–5x bucket (3 < 5 ≤ 5)? Actually bucket is (3,5] so 5.0 ≤ 5 → yes
    # Just check total across all buckets == 1 (only in-window position)
    total_count = sum(r["trade_count"] for r in out["buckets"])
    assert total_count == 1, (
        f"Expected 1 position in window, got {total_count}. "
        f"Buckets: {[(r['bucket'], r['trade_count']) for r in out['buckets']]}"
    )
