"""Perps-only day-scoring tests: closed positions inside a card's session window,
plus the flag matrix."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.perps.models import (
    ExchangeAccount, Position, Venue, AssetClass, Direction, PositionStatus,
    OpenedAtSource,
)
from app.workflow.models import PlanCard
from app.workflow.services.scoring import (
    window_for_card, score_window, score_card,
)

CARD_DATE = date(2026, 6, 11)
# Default window (session_start_hour=0) is [2026-06-11 00:00, 2026-06-12 00:00).
IN = datetime(2026, 6, 11, 12, 0, 0)        # inside the window
OUT = datetime(2026, 6, 12, 1, 0, 0)        # next day — outside


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u); s.commit()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="Bybit")
    s.add(acc); s.commit()
    yield s, u, acc
    s.close()


def _perps(s, u, acc, symbol, pnl, closed_at, status=PositionStatus.CLOSED):
    p = Position(
        user_id=u.id, exchange_account_id=acc.id, symbol=symbol,
        asset_class=AssetClass.PERP, direction=Direction.LONG, status=status,
        opened_at=closed_at - timedelta(hours=1), closed_at=closed_at,
        avg_entry=100.0, avg_exit=105.0, quantity=1.0, realized_pnl=pnl,
        total_fees=0.0, total_funding=0.0, opened_at_source=OpenedAtSource.EXACT,
        position_key=f"k:{symbol}:{closed_at.isoformat()}",
    )
    s.add(p); s.commit()
    return p


def _card(s, u, **kw):
    c = PlanCard(user_id=u.id, date=kw.pop("date", CARD_DATE), **kw)
    s.add(c); s.commit()
    return c


# ── window_for_card ──────────────────────────────────────────────────

def test_window_default_hour():
    c = PlanCard(user_id=1, date=CARD_DATE, session_start_hour=0)
    start, end = window_for_card(c)
    assert start == datetime(2026, 6, 11, 0, 0, 0)
    assert end == datetime(2026, 6, 12, 0, 0, 0)


def test_window_session_start_hour_6():
    c = PlanCard(user_id=1, date=CARD_DATE, session_start_hour=6)
    start, end = window_for_card(c)
    assert start == datetime(2026, 6, 11, 6, 0, 0)
    assert end == datetime(2026, 6, 12, 6, 0, 0)


# ── score_window: perps counts / realized / symbols ─────────────────

def test_score_window_perps_only(db):
    s, u, acc = db
    start, end = datetime(2026, 6, 11, 0, 0, 0), datetime(2026, 6, 12, 0, 0, 0)

    # 2 in-window, 1 out-of-window.
    _perps(s, u, acc, "BTCUSDT", 50.0, IN)
    _perps(s, u, acc, "ethusdt", -20.0, IN + timedelta(hours=2))
    _perps(s, u, acc, "SOLUSDT", 999.0, OUT)   # excluded

    out = score_window(s, u.id, start, end)
    assert out["trades_count"] == 2
    assert out["realized"] == pytest.approx(30.0)
    assert out["traded_symbols"] == ["BTCUSDT", "ETHUSDT"]


# ── score_card flag matrix ───────────────────────────────────────────

def test_card_no_commitments_is_adherent(db):
    s, u, acc = db
    _perps(s, u, acc, "BTCUSDT", -300.0, IN)  # a loss, but no limits set
    c = _card(s, u, session_start_hour=0)
    out = score_card(s, u.id, c)
    assert out["adherent"] is True
    assert out["flags"] == {"trades_over": False, "loss_breached": False, "offlist": False}
    assert out["offlist_symbols"] == []


def test_card_trades_over(db):
    s, u, acc = db
    _perps(s, u, acc, "BTCUSDT", 10.0, IN)
    _perps(s, u, acc, "ETHUSDT", 10.0, IN)
    _perps(s, u, acc, "SOLUSDT", 10.0, IN)  # count = 3
    c = _card(s, u, session_start_hour=0, max_trades=2)
    out = score_card(s, u.id, c)
    assert out["trades_count"] == 3
    assert out["flags"]["trades_over"] is True
    assert out["adherent"] is False


def test_card_loss_breached_at_exact_boundary(db):
    s, u, acc = db
    _perps(s, u, acc, "BTCUSDT", -150.0, IN)
    # max_daily_loss is a positive magnitude; breach is realized <= -max (<=).
    c = _card(s, u, session_start_hour=0, max_daily_loss=150.0)
    out = score_card(s, u.id, c)
    assert out["realized"] == pytest.approx(-150.0)
    assert out["flags"]["loss_breached"] is True   # exactly at -max counts
    assert out["adherent"] is False


def test_card_loss_not_breached_above_threshold(db):
    s, u, acc = db
    _perps(s, u, acc, "BTCUSDT", -149.0, IN)
    c = _card(s, u, session_start_hour=0, max_daily_loss=150.0)
    out = score_card(s, u.id, c)
    assert out["flags"]["loss_breached"] is False
    assert out["adherent"] is True


def test_card_offlist(db):
    s, u, acc = db
    _perps(s, u, acc, "BTCUSDT", 10.0, IN)
    _perps(s, u, acc, "ETHUSDT", -5.0, IN)   # off the shortlist
    c = _card(s, u, session_start_hour=0, shortlist=["BTCUSDT"])
    out = score_card(s, u.id, c)
    assert out["offlist_symbols"] == ["ETHUSDT"]
    assert out["flags"]["offlist"] is True
    assert out["adherent"] is False


def test_card_shortlist_normalized_before_compare(db):
    s, u, acc = db
    _perps(s, u, acc, "BTCUSDT", 10.0, IN)
    # lowercase shortlist must still match an uppercase traded symbol.
    c = _card(s, u, session_start_hour=0, shortlist=["btcusdt"])
    out = score_card(s, u.id, c)
    assert out["offlist_symbols"] == []
    assert out["flags"]["offlist"] is False


# ── session_start_hour=6 boundary ────────────────────────────────────

def test_session_start_hour_6_excludes_early_trade(db):
    s, u, acc = db
    # A trade closing at 05:00 UTC on the card's date belongs to the PREVIOUS
    # day's window (which started 2026-06-10 06:00). With session_start_hour=6
    # the card's window is [2026-06-11 06:00, 2026-06-12 06:00).
    early = datetime(2026, 6, 11, 5, 0, 0)
    _perps(s, u, acc, "BTCUSDT", 50.0, early)
    c = _card(s, u, session_start_hour=6)
    out = score_card(s, u.id, c)
    assert out["trades_count"] == 0
    assert out["realized"] == pytest.approx(0.0)
    assert out["traded_symbols"] == []


def test_session_start_hour_6_includes_in_window_trade(db):
    s, u, acc = db
    inwin = datetime(2026, 6, 11, 7, 0, 0)   # 07:00 >= 06:00 start
    _perps(s, u, acc, "BTCUSDT", 50.0, inwin)
    c = _card(s, u, session_start_hour=6)
    out = score_card(s, u.id, c)
    assert out["trades_count"] == 1
    assert out["realized"] == pytest.approx(50.0)


def test_card_window_in_payload(db):
    s, u, acc = db
    c = _card(s, u, session_start_hour=6)
    out = score_card(s, u.id, c)
    assert out["window"]["start"] == "2026-06-11T06:00:00"
    assert out["window"]["end"] == "2026-06-12T06:00:00"


def test_score_window_workspace_param_ignored(db):
    # workspace param is accepted but only perps data is scored.
    s, u, acc = db
    start = datetime(CARD_DATE.year, CARD_DATE.month, CARD_DATE.day)
    end = start + timedelta(days=1)
    _perps(s, u, acc, "ETHUSDT", 30.0, start + timedelta(hours=2))

    # All workspace variants return the same perps-only result.
    for ws in ("perps", "all", "prop"):
        out = score_window(s, u.id, start, end, workspace=ws)
        assert out["trades_count"] == 1
        assert out["realized"] == pytest.approx(30.0)
        assert out["traded_symbols"] == ["ETHUSDT"]
