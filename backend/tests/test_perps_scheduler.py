from app.database import SessionLocal
from app.core.models import User
from app.perps.models import ExchangeAccount, Venue
from app.perps import scheduler


def test_scheduler_syncs_both_venues(monkeypatch):
    db = SessionLocal()
    try:
        user = db.query(User).first()
        if user is None:
            user = User(email="sch@test.dev", password_hash="x")
            db.add(user); db.commit(); db.refresh(user)
        for venue in (Venue.BYBIT, Venue.HYPERLIQUID):
            db.add(ExchangeAccount(user_id=user.id, venue=venue, label=venue.value,
                                   is_active=True, encrypted_credentials="enc"))
        db.commit()
    finally:
        db.close()

    synced = []
    monkeypatch.setattr(scheduler.venue_sync, "is_syncing", lambda i: False)
    monkeypatch.setattr(scheduler.venue_sync, "sync_account",
                        lambda db, acc: synced.append(acc.venue))
    scheduler.sync_all_active_accounts()
    assert Venue.BYBIT in synced
    assert Venue.HYPERLIQUID in synced
