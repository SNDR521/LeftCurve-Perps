from types import SimpleNamespace
from app.perps.models import Venue
from app.perps.services import venue_sync


def test_sync_account_routes_by_venue(monkeypatch):
    calls = []
    monkeypatch.setattr(venue_sync.bybit_sync, "sync_account",
                        lambda db, acc: calls.append(("bybit", acc.id)) or {"ok": 1})
    monkeypatch.setattr(venue_sync.hyperliquid_sync, "sync_account",
                        lambda db, acc: calls.append(("hl", acc.id)) or {"ok": 1})

    venue_sync.sync_account(None, SimpleNamespace(id=1, venue=Venue.BYBIT))
    venue_sync.sync_account(None, SimpleNamespace(id=2, venue=Venue.HYPERLIQUID))
    assert calls == [("bybit", 1), ("hl", 2)]


def test_is_syncing_checks_both_modules(monkeypatch):
    monkeypatch.setattr(venue_sync.bybit_sync, "is_syncing", lambda i: i == 10)
    monkeypatch.setattr(venue_sync.hyperliquid_sync, "is_syncing", lambda i: i == 20)
    assert venue_sync.is_syncing(10) is True
    assert venue_sync.is_syncing(20) is True
    assert venue_sync.is_syncing(99) is False


def test_unsupported_venue_raises():
    import pytest
    with pytest.raises(ValueError):
        venue_sync.sync_account(None, SimpleNamespace(id=3, venue=Venue.LIGHTER))
