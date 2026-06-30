"""Venue dispatch for perps account sync. Routes by ExchangeAccount.venue so the
router, scheduler, and background worker stay venue-agnostic."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.perps.models import ExchangeAccount, Venue
from app.perps.services import bybit_sync, hyperliquid_sync, risex_sync

# Venues this app can sync today (Lighter is roadmap, not yet implemented).
SUPPORTED_VENUES = (Venue.BYBIT, Venue.HYPERLIQUID, Venue.RISEX)


def client_for(account: ExchangeAccount):
    if account.venue == Venue.BYBIT:
        return bybit_sync._client_for(account)
    if account.venue == Venue.HYPERLIQUID:
        return hyperliquid_sync._client_for(account)
    if account.venue == Venue.RISEX:
        return risex_sync._client_for(account)
    raise ValueError(f"unsupported venue: {account.venue}")


def sync_account(db: Session, account: ExchangeAccount) -> dict:
    if account.venue == Venue.BYBIT:
        return bybit_sync.sync_account(db, account)
    if account.venue == Venue.HYPERLIQUID:
        return hyperliquid_sync.sync_account(db, account)
    if account.venue == Venue.RISEX:
        return risex_sync.sync_account(db, account)
    raise ValueError(f"unsupported venue: {account.venue}")


def is_syncing(account_id: int) -> bool:
    return (bybit_sync.is_syncing(account_id) or hyperliquid_sync.is_syncing(account_id)
            or risex_sync.is_syncing(account_id))
