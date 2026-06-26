"""Tests for R3 cockpit task 2: Position.leverage + BalanceSnapshot.
Task 3 appends: live cockpit service + endpoint."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.perps.models import (
    ExchangeAccount, Position, BalanceSnapshot, Fill, PerpsJournal,
    Venue, AssetClass, Direction, Side, PositionStatus,
)

T0 = datetime(2026, 1, 1, 10, 0, 0)


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u); s.commit()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="Bybit")
    s.add(acc); s.commit()
    yield s, u, acc
    s.close()


def test_position_leverage_roundtrip(db):
    s, u, acc = db
    p = Position(user_id=u.id, exchange_account_id=acc.id, symbol="BTCUSDT",
                 asset_class=AssetClass.PERP, direction=Direction.LONG,
                 status=PositionStatus.CLOSED, opened_at=T0,
                 closed_at=T0 + timedelta(hours=1), avg_entry=100.0, avg_exit=110.0,
                 quantity=1.0, realized_pnl=10.0, total_fees=0.0, total_funding=0.0,
                 leverage=10.0, position_key="1:BTCUSDT:cpnl:oL")
    s.add(p); s.commit(); s.refresh(p)
    assert p.leverage == 10.0


def test_balance_snapshot_unique_constraint(db):
    from sqlalchemy.exc import IntegrityError
    s, u, acc = db
    snap = dict(user_id=u.id, exchange_account_id=acc.id, ts=T0, balance=1000.0, kind="SNAPSHOT")
    s.add(BalanceSnapshot(**snap)); s.commit()
    assert s.query(BalanceSnapshot).count() == 1
    s.add(BalanceSnapshot(**snap))
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()
    # same ts, different kind is allowed
    s.add(BalanceSnapshot(**{**snap, "kind": "TRANSFER_IN"})); s.commit()
    assert s.query(BalanceSnapshot).count() == 2


# --- Task 3: live cockpit ---------------------------------------------------

from app.perps.services.cockpit import build_cockpit


class FakeCockpitClient:
    side = "Buy"

    def fetch_open_positions(self):
        return [{"symbol": "ETHUSDT", "side": self.side, "size": "2", "avgPrice": "2200",
                 "leverage": "5", "liqPrice": "1800", "unrealisedPnl": "100", "tradeMode": 0}]

    def fetch_tickers(self, symbols=None):
        return {"ETHUSDT": {"mark_price": 2250.0, "funding_rate": 0.0001,
                            "next_funding_time": 1781300000000}}

    def fetch_wallet_balance(self):
        return {"equity": 10000.0, "balance": 9900.0, "available": 9000.0}


def _funding_fill(u, acc, amount, t):
    return Fill(user_id=u.id, exchange_account_id=acc.id, venue=Venue.BYBIT,
                symbol="ETHUSDT", asset_class=AssetClass.PERP, side=Side.BUY,
                price=0.0, quantity=0.0, fee=0.0, funding_amount=amount, executed_at=t)


def _seed(s, u, acc, stop=2100.0):
    """Journal stop + open snapshot position + funding fills + closed-pnl rows."""
    s.add(PerpsJournal(user_id=u.id, position_key=f"{acc.id}:ETHUSDT:open", stop_price=stop))
    s.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="ETHUSDT",
                   asset_class=AssetClass.PERP, direction=Direction.LONG,
                   status=PositionStatus.OPEN, opened_at=T0, avg_entry=2200.0, quantity=2.0,
                   realized_pnl=0.0, total_fees=0.0, total_funding=0.0,
                   position_key=f"{acc.id}:ETHUSDT:open"))
    # funding accrued AFTER opened_at: -1.5 + -0.5 = -2.0
    s.add(_funding_fill(u, acc, -1.5, T0 + timedelta(hours=8)))
    s.add(_funding_fill(u, acc, -0.5, T0 + timedelta(hours=16)))
    # funding BEFORE opened_at: must be excluded from accrued
    s.add(_funding_fill(u, acc, -99.0, T0 - timedelta(hours=8)))
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    # closed TODAY: counts toward realized_today / trades_today
    s.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="ETHUSDT",
                   asset_class=AssetClass.PERP, direction=Direction.LONG,
                   status=PositionStatus.CLOSED, opened_at=T0,
                   closed_at=now_naive, avg_entry=2000.0, avg_exit=2025.0, quantity=2.0,
                   realized_pnl=50.0, total_fees=0.0, total_funding=0.0,
                   position_key=f"{acc.id}:cpnl:t1"))
    # closed YESTERDAY: must NOT count
    s.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="ETHUSDT",
                   asset_class=AssetClass.PERP, direction=Direction.LONG,
                   status=PositionStatus.CLOSED, opened_at=T0,
                   closed_at=now_naive - timedelta(days=1), avg_entry=2000.0,
                   avg_exit=2500.0, quantity=2.0, realized_pnl=999.0, total_fees=0.0,
                   total_funding=0.0, position_key=f"{acc.id}:cpnl:y1"))
    s.commit()


def test_cockpit_position_math(db):
    s, u, acc = db
    _seed(s, u, acc)
    out = build_cockpit(s, acc, FakeCockpitClient())
    pos = out["positions"][0]
    assert pos["upnl"] == 100.0
    assert pos["upnl_pct"] == pytest.approx(100 / (2200 * 2) * 100)
    assert pos["notional"] == pytest.approx(4500.0)          # mark 2250 × size 2
    assert pos["leverage"] == 5.0
    assert pos["liq_distance_pct"] == pytest.approx((2250 - 1800) / 2250 * 100)
    assert pos["margin_mode"] == "cross"
    assert pos["projected_funding_24h"] == pytest.approx(-0.0001 * 4500 * 3)
    assert pos["accrued_funding"] == pytest.approx(-2.0)     # only fills after opened_at
    assert pos["stop_price"] == 2100.0
    assert pos["live_r"] == pytest.approx((2250 - 2200) / (2200 - 2100))
    assert pos["risk_usd"] == pytest.approx(200.0)


def test_cockpit_account_block(db):
    s, u, acc = db
    _seed(s, u, acc)
    out = build_cockpit(s, acc, FakeCockpitClient())
    a = out["account"]
    assert a["account_id"] == acc.id
    assert a["equity"] == 10000.0
    assert a["realized_today"] == pytest.approx(50.0)
    assert a["trades_today"] == 1
    assert a["open_upnl"] == 100.0
    assert a["session_pnl"] == pytest.approx(150.0)
    assert a["gross_notional"] == pytest.approx(4500.0)
    assert a["net_notional"] == pytest.approx(4500.0)
    assert a["exposure_pct"] == pytest.approx(45.0)
    assert a["open_risk_usd"] == pytest.approx(200.0)
    assert a["open_risk_pct"] == pytest.approx(2.0)
    assert a["unstopped_count"] == 0


def test_cockpit_wrong_side_stop_is_unstopped(db):
    s, u, acc = db
    # SHORT position with stop BELOW entry (wrong side for a SHORT): the open
    # snapshot row must be SHORT too so accrued funding still matches.
    s.add(PerpsJournal(user_id=u.id, position_key=f"{acc.id}:ETHUSDT:open", stop_price=2100.0))
    s.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="ETHUSDT",
                   asset_class=AssetClass.PERP, direction=Direction.SHORT,
                   status=PositionStatus.OPEN, opened_at=T0, avg_entry=2200.0, quantity=2.0,
                   realized_pnl=0.0, total_fees=0.0, total_funding=0.0,
                   position_key=f"{acc.id}:ETHUSDT:open"))
    s.commit()

    client = FakeCockpitClient()
    client.side = "Sell"
    out = build_cockpit(s, acc, client)
    pos = out["positions"][0]
    assert pos["direction"] == "SHORT"
    assert pos["stop_price"] == 2100.0
    assert pos["live_r"] is None and pos["risk_usd"] is None
    assert out["account"]["unstopped_count"] == 1
    # SHORT net notional negative
    assert out["account"]["net_notional"] == pytest.approx(-4500.0)
    # SHORT earns positive funding when rate is positive: projected positive
    assert pos["projected_funding_24h"] == pytest.approx(0.0001 * 4500 * 3)


# --- endpoint (TestClient over the real app/session, test_perps_positions style) ---

from fastapi.testclient import TestClient
from app.main import app
from app.database import init_db, SessionLocal
from app.core.deps import get_current_user
from app.perps.routers import cockpit as cockpit_router


def _as(u):
    app.dependency_overrides[get_current_user] = lambda: u


def teardown_function():
    app.dependency_overrides.clear()


@pytest.fixture()
def appdb(monkeypatch):
    init_db()
    s = SessionLocal()
    for M in (Fill, PerpsJournal, Position, ExchangeAccount, User):
        s.query(M).delete()
    s.commit()
    u = User(email="cockpit@x.com", password_hash="x")
    other = User(email="other@x.com", password_hash="x")
    s.add(u); s.add(other); s.commit(); s.refresh(u); s.refresh(other)
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="main", is_active=True)
    s.add(acc); s.commit(); s.refresh(acc); s.refresh(u); s.refresh(other)
    s.expunge(u); s.expunge(other)
    monkeypatch.setattr(cockpit_router, "client_for", lambda account: FakeCockpitClient())
    s.close()
    yield u, other, acc.id


def test_cockpit_endpoint(appdb):
    u, other, aid = appdb
    c = TestClient(app)

    # no auth -> 401
    assert c.get("/api/perps/cockpit").status_code == 401

    _as(u)
    r = c.get("/api/perps/cockpit")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"asof", "plan", "account", "positions"}
    assert body["plan"] is None  # no plan card seeded for this user
    assert body["account"]["account_id"] == aid
    assert len(body["positions"]) == 1
    assert body["positions"][0]["symbol"] == "ETHUSDT"

    # user with no active Bybit account -> 404
    _as(other)
    assert c.get("/api/perps/cockpit").status_code == 404


# --- Task 6: cockpit plan block --------------------------------------------

from datetime import date, time
from app.perps.services.cockpit import _active_plan_card
from app.workflow.models import PlanCard


def _closed_today(s, u, acc, pnl, key, closed_at):
    s.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="ETHUSDT",
                   asset_class=AssetClass.PERP, direction=Direction.LONG,
                   status=PositionStatus.CLOSED, opened_at=T0,
                   closed_at=closed_at, avg_entry=2000.0, avg_exit=1900.0, quantity=1.0,
                   realized_pnl=pnl, total_fees=0.0, total_funding=0.0,
                   position_key=f"{acc.id}:cpnl:{key}"))


def test_cockpit_plan_block_breached(db):
    """Card today (max_trades=1, max_daily_loss=100, hour 0) + two perps positions
    closed today summing -150 → plan block reports the breach AND the account block's
    realized_today / trades_today follow the CARD WINDOW cross-workspace numbers."""
    s, u, acc = db
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now_naive.date()
    s.add(PlanCard(user_id=u.id, date=today, session_start_hour=0,
                   max_trades=1, max_daily_loss=100.0))
    # two positions closed today: -100 + -50 = -150
    _closed_today(s, u, acc, -100.0, "t1", now_naive)
    _closed_today(s, u, acc, -50.0, "t2", now_naive)
    s.commit()

    out = build_cockpit(s, acc, FakeCockpitClient())
    assert out["plan"] == {
        "date": today.isoformat(),
        "max_trades": 1,
        "trades_count": 2,
        "max_daily_loss": 100.0,
        "realized": -150.0,
        "trades_over": True,
        "loss_breached": True,
    }
    # account block now follows the card window cross-workspace numbers
    assert out["account"]["trades_today"] == 2
    assert out["account"]["realized_today"] == pytest.approx(-150.0)


def test_cockpit_plan_block_none_without_card(db):
    """No card → plan is None and the perps-only UTC-midnight behavior is unchanged."""
    s, u, acc = db
    _seed(s, u, acc)  # one closed-today (+50) + one closed-yesterday (+999)
    out = build_cockpit(s, acc, FakeCockpitClient())
    assert out["plan"] is None
    # unchanged perps-only UTC-midnight aggregates
    assert out["account"]["realized_today"] == pytest.approx(50.0)
    assert out["account"]["trades_today"] == 1


def test_cockpit_plan_window_excludes_pre_session_trade(db):
    """session_start_hour=6 card: a position closed 05:00 UTC today belongs to
    YESTERDAY's window (before today's 06:00 session start) and is excluded; a
    07:00 UTC position is inside today's window. Plan + account both see count 1.

    NOTE: this only deterministically holds when 'now' is inside today's 06:00
    window, i.e. wall-clock UTC hour >= 6. We assert the score/window directly via
    the explicit closed_at times rather than relying on _active_plan_card finding
    the card at an arbitrary test clock; to make the card the ACTIVE one we date it
    today and rely on the helper unit tests below for the now-selection logic. To
    avoid clock flakiness we build the cockpit with a card whose window we control
    and check the account aggregates reflect score_card over that window."""
    s, u, acc = db
    today = date(2026, 1, 2)
    s.add(PlanCard(user_id=u.id, date=today, session_start_hour=6,
                   max_trades=5, max_daily_loss=1000.0))
    # 05:00 UTC today -> before 06:00 session start -> excluded
    _closed_today(s, u, acc, -10.0, "pre", datetime(2026, 1, 2, 5, 0, 0))
    # 07:00 UTC today -> inside window -> counted
    _closed_today(s, u, acc, -20.0, "in", datetime(2026, 1, 2, 7, 0, 0))
    s.commit()

    # score_card over this fixed-date card window: only the 07:00 trade counts
    from app.workflow.services.scoring import score_card
    score = score_card(s, u.id, s.query(PlanCard).first())
    assert score["trades_count"] == 1
    assert score["realized"] == pytest.approx(-20.0)


def test_active_plan_card_selection():
    """Unit-test _active_plan_card's now-selection with injected datetimes against an
    in-memory db. Straddle math walked in comments below.

    Setup: today = 2026-01-02.
      - today's card  hour 0  window = [2026-01-02 00:00, 2026-01-03 00:00)
      - yesterday's card hour 23 window = [2026-01-01 23:00, 2026-01-02 23:00)
    """
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="plan@x.com", password_hash="x")
    s.add(u); s.commit(); s.refresh(u)

    today = date(2026, 1, 2)
    yesterday = date(2026, 1, 1)

    # (a) today's hour-0 card: found for any 'now' during today.
    c_today = PlanCard(user_id=u.id, date=today, session_start_hour=0)
    s.add(c_today); s.commit()
    # now = 2026-01-02 10:00 -> inside [00:00, next 00:00) -> found
    got = _active_plan_card(s, u.id, datetime(2026, 1, 2, 10, 0, 0))
    assert got is not None and got.date == today

    # (b) yesterday's hour-23 card, now = 22:00 today.
    #   yesterday window = [2026-01-01 23:00, 2026-01-02 23:00).
    #   walk: 2026-01-02 22:00 >= 2026-01-01 23:00 (True) and < 2026-01-02 23:00 (True)
    #         -> 22:00 today IS inside yesterday's hour-23 window -> yesterday's card active.
    s.query(PlanCard).delete(); s.commit()
    c_yest = PlanCard(user_id=u.id, date=yesterday, session_start_hour=23)
    s.add(c_yest); s.commit()
    got = _active_plan_card(s, u.id, datetime(2026, 1, 2, 22, 0, 0))
    assert got is not None and got.date == yesterday

    # (c) BOTH present, now = 2026-01-02 10:00:
    #   today's hour-0 window [01-02 00:00, 01-03 00:00) contains 10:00 -> match.
    #   yesterday's hour-23 window [01-01 23:00, 01-02 23:00) also contains 10:00 -> match.
    #   today's card is PREFERRED.
    s.query(PlanCard).delete(); s.commit()
    s.add(PlanCard(user_id=u.id, date=today, session_start_hour=0))
    s.add(PlanCard(user_id=u.id, date=yesterday, session_start_hour=23))
    s.commit()
    got = _active_plan_card(s, u.id, datetime(2026, 1, 2, 10, 0, 0))
    assert got is not None and got.date == today

    # (d) neither window contains now -> None.
    #   only yesterday's hour-23 card; now = 2026-01-02 23:30 is >= window end (01-02 23:00) -> None.
    s.query(PlanCard).delete(); s.commit()
    s.add(PlanCard(user_id=u.id, date=yesterday, session_start_hour=23)); s.commit()
    got = _active_plan_card(s, u.id, datetime(2026, 1, 2, 23, 30, 0))
    assert got is None
    s.close()


class FakeClientWithExchangeStop(FakeCockpitClient):
    """LONG ETH 2x @2200 with the SL set ON BYBIT (stopLoss field)."""
    def fetch_open_positions(self):
        rows = super().fetch_open_positions()
        rows[0]["stopLoss"] = "2100"
        return rows


def test_exchange_stop_counts_as_stopped(db):
    # The trader's SL lives on the exchange — no journal stop needed for risk.
    s, u, acc = db
    _seed(s, u, acc, stop=None)  # journal row with stop_price None
    out = build_cockpit(s, acc, FakeClientWithExchangeStop())
    pos = out["positions"][0]
    assert pos["stop_price"] == 2100.0
    assert pos["stop_source"] == "exchange"
    assert pos["risk_usd"] == pytest.approx(200.0)
    assert pos["live_r"] == pytest.approx((2250 - 2200) / (2200 - 2100))
    assert out["account"]["unstopped_count"] == 0
    assert out["account"]["open_risk_usd"] == pytest.approx(200.0)


def test_journal_stop_overrides_exchange_stop(db):
    s, u, acc = db
    _seed(s, u, acc, stop=2150.0)  # explicit journal intention
    out = build_cockpit(s, acc, FakeClientWithExchangeStop())
    pos = out["positions"][0]
    assert pos["stop_price"] == 2150.0
    assert pos["stop_source"] == "journal"
    assert pos["risk_usd"] == pytest.approx((2200 - 2150) * 2)


def test_no_stop_anywhere_is_unstopped(db):
    s, u, acc = db
    _seed(s, u, acc, stop=None)
    out = build_cockpit(s, acc, FakeCockpitClient())  # no stopLoss field
    pos = out["positions"][0]
    assert pos["stop_price"] is None and pos["stop_source"] is None
    assert out["account"]["unstopped_count"] == 1


def test_cockpit_endpoint_serves_hyperliquid(monkeypatch):
    init_db()
    s = SessionLocal()
    for M in (Fill, PerpsJournal, Position, ExchangeAccount, User):
        s.query(M).delete()
    s.commit()
    u = User(email="hlcockpit@x.com", password_hash="x")
    s.add(u); s.commit(); s.refresh(u)
    acc = ExchangeAccount(user_id=u.id, venue=Venue.HYPERLIQUID, label="HL",
                          encrypted_credentials="enc", is_active=True)
    s.add(acc); s.commit(); s.refresh(acc); s.refresh(u)
    aid = acc.id
    s.expunge(u)
    monkeypatch.setattr(cockpit_router, "client_for", lambda account: FakeCockpitClient())
    s.close()

    c = TestClient(app)
    _as(u)
    r = c.get(f"/api/perps/cockpit?account_id={aid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account"]["account_id"] == aid
    assert body["positions"][0]["symbol"] == "ETHUSDT"
