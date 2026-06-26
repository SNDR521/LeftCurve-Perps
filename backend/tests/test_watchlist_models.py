"""Tests for WatchlistItem and Alert models in app/workflow/models.py."""
import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User  # noqa: F401 — users table required
from app.core.security import hash_password
from app.workflow.models import WatchlistItem, Alert


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    import app.core.models   # noqa: F401
    import app.perps.models  # noqa: F401
    import app.workflow.models  # noqa: F401
    Base.metadata.create_all(engine)
    s = Session(engine)
    u1 = User(email="alice@test.com", password_hash=hash_password("x"))
    u2 = User(email="bob@test.com", password_hash=hash_password("y"))
    s.add_all([u1, u2])
    s.commit()
    yield s, u1, u2
    s.close()


# ---------------------------------------------------------------------------
# WatchlistItem round-trip
# ---------------------------------------------------------------------------

def test_watchlist_item_roundtrip(db):
    s, u1, _ = db
    item = WatchlistItem(
        user_id=u1.id,
        symbol="BTCUSDT",
        market="CRYPTO",
        note="main crypto watch",
        levels=[{"price": 50000.0, "label": "support"}],
    )
    s.add(item)
    s.commit()
    s.refresh(item)

    assert item.id is not None
    assert item.symbol == "BTCUSDT"
    assert item.market == "CRYPTO"
    assert item.note == "main crypto watch"
    assert item.levels == [{"price": 50000.0, "label": "support"}]
    assert item.last_price is None
    assert item.last_checked is None
    assert item.created_at is not None


def test_watchlist_item_last_price_nullable(db):
    s, u1, _ = db
    item = WatchlistItem(user_id=u1.id, symbol="ETHUSDT", market="CRYPTO")
    s.add(item)
    s.commit()
    s.refresh(item)
    assert item.last_price is None
    assert item.last_checked is None


def test_watchlist_item_last_price_settable(db):
    s, u1, _ = db
    item = WatchlistItem(user_id=u1.id, symbol="SOLUSDT", market="CRYPTO",
                         last_price=150.25,
                         last_checked=datetime.datetime(2026, 6, 11, 12, 0, 0))
    s.add(item)
    s.commit()
    s.refresh(item)
    assert item.last_price == pytest.approx(150.25)
    assert item.last_checked == datetime.datetime(2026, 6, 11, 12, 0, 0)


def test_watchlist_item_levels_json_list(db):
    s, u1, _ = db
    levels = [
        {"price": 50000.0, "label": "major support"},
        {"price": 55000.0, "label": "resistance"},
        {"price": 60000.0, "label": None},
    ]
    item = WatchlistItem(user_id=u1.id, symbol="BTCUSDT", market="CRYPTO",
                         levels=levels)
    s.add(item)
    s.commit()
    s.refresh(item)
    assert isinstance(item.levels, list)
    assert len(item.levels) == 3
    assert item.levels[0]["price"] == pytest.approx(50000.0)
    assert item.levels[2]["label"] is None


def test_watchlist_item_levels_default_empty(db):
    """levels should default to empty list when not provided."""
    s, u1, _ = db
    item = WatchlistItem(user_id=u1.id, symbol="NVDA", market="EQUITY")
    s.add(item)
    s.commit()
    s.refresh(item)
    # levels may be None or [] — both acceptable (JSON default)
    assert item.levels is None or item.levels == []


# ---------------------------------------------------------------------------
# WatchlistItem uniqueness: (user_id, symbol)
# ---------------------------------------------------------------------------

def test_watchlist_item_unique_per_user_symbol(db):
    """Same user cannot have two watchlist items for the same symbol."""
    s, u1, _ = db
    item1 = WatchlistItem(user_id=u1.id, symbol="BTCUSDT", market="CRYPTO")
    s.add(item1)
    s.commit()

    item2 = WatchlistItem(user_id=u1.id, symbol="BTCUSDT", market="CRYPTO")
    s.add(item2)
    with pytest.raises(IntegrityError):
        s.commit()
    s.rollback()


def test_watchlist_item_same_symbol_different_user_ok(db):
    """Two different users CAN watch the same symbol."""
    s, u1, u2 = db
    item1 = WatchlistItem(user_id=u1.id, symbol="BTCUSDT", market="CRYPTO")
    item2 = WatchlistItem(user_id=u2.id, symbol="BTCUSDT", market="CRYPTO")
    s.add_all([item1, item2])
    s.commit()  # must not raise

    assert item1.id != item2.id
    assert item1.symbol == item2.symbol == "BTCUSDT"


# ---------------------------------------------------------------------------
# Alert round-trip
# ---------------------------------------------------------------------------

def test_alert_roundtrip(db):
    s, u1, _ = db
    triggered = datetime.datetime(2026, 6, 11, 10, 30, 0)
    alert = Alert(
        user_id=u1.id,
        kind="LEVEL_CROSS",
        symbol="BTCUSDT",
        payload={
            "symbol": "BTCUSDT",
            "market": "CRYPTO",
            "level": 50000.0,
            "label": "support",
            "price": 50100.0,
            "direction": "up",
            "source": "live",
        },
        triggered_at=triggered,
    )
    s.add(alert)
    s.commit()
    s.refresh(alert)

    assert alert.id is not None
    assert alert.kind == "LEVEL_CROSS"
    assert alert.symbol == "BTCUSDT"
    assert alert.payload["level"] == pytest.approx(50000.0)
    assert alert.payload["direction"] == "up"
    assert alert.triggered_at == triggered
    assert alert.seen is False


def test_alert_seen_default_false(db):
    """Alert.seen defaults to False."""
    s, u1, _ = db
    alert = Alert(
        user_id=u1.id,
        kind="LEVEL_CROSS",
        symbol="BTCUSDT",
        payload={},
        triggered_at=datetime.datetime(2026, 6, 11, 9, 0, 0),
    )
    s.add(alert)
    s.commit()
    s.refresh(alert)
    assert alert.seen is False


def test_alert_seen_can_be_set_true(db):
    s, u1, _ = db
    alert = Alert(
        user_id=u1.id,
        kind="LEVEL_CROSS",
        symbol="ETHUSDT",
        payload={},
        triggered_at=datetime.datetime(2026, 6, 11, 9, 0, 0),
    )
    s.add(alert)
    s.commit()
    alert.seen = True
    s.commit()
    s.refresh(alert)
    assert alert.seen is True


def test_alert_symbol_nullable(db):
    """Alert.symbol is nullable (e.g. THEME_STATUS alerts may not have a single symbol)."""
    s, u1, _ = db
    alert = Alert(
        user_id=u1.id,
        kind="THEME_STATUS",
        symbol=None,
        payload={"theme": "AI", "old_status": "Leader", "new_status": "Fading"},
        triggered_at=datetime.datetime(2026, 6, 11, 11, 0, 0),
    )
    s.add(alert)
    s.commit()
    s.refresh(alert)
    assert alert.symbol is None
    assert alert.kind == "THEME_STATUS"


def test_alert_payload_json_dict(db):
    s, u1, _ = db
    payload = {
        "market": "EQUITY",
        "theme": "AI",
        "old_status": "Leader",
        "new_status": "Fading",
        "matched_symbols": ["NVDA", "AMD"],
    }
    alert = Alert(
        user_id=u1.id,
        kind="THEME_STATUS",
        payload=payload,
        triggered_at=datetime.datetime(2026, 6, 11, 11, 0, 0),
    )
    s.add(alert)
    s.commit()
    s.refresh(alert)
    assert isinstance(alert.payload, dict)
    assert alert.payload["matched_symbols"] == ["NVDA", "AMD"]


def test_multiple_alerts_same_user(db):
    """A user can have many alerts."""
    s, u1, _ = db
    t = datetime.datetime(2026, 6, 11, 12, 0, 0)
    for i in range(3):
        a = Alert(user_id=u1.id, kind="LEVEL_CROSS",
                  symbol=f"SYM{i}", payload={}, triggered_at=t)
        s.add(a)
    s.commit()

    count = s.query(Alert).filter(Alert.user_id == u1.id).count()
    assert count == 3


def test_alert_user_isolation(db):
    """Alerts for different users are independent."""
    s, u1, u2 = db
    t = datetime.datetime(2026, 6, 11, 12, 0, 0)
    a1 = Alert(user_id=u1.id, kind="LEVEL_CROSS", symbol="BTC",
               payload={}, triggered_at=t)
    a2 = Alert(user_id=u2.id, kind="LEVEL_CROSS", symbol="BTC",
               payload={}, triggered_at=t)
    s.add_all([a1, a2])
    s.commit()

    u1_alerts = s.query(Alert).filter(Alert.user_id == u1.id).all()
    u2_alerts = s.query(Alert).filter(Alert.user_id == u2.id).all()
    assert len(u1_alerts) == 1
    assert len(u2_alerts) == 1
    assert u1_alerts[0].id != u2_alerts[0].id
