import logging
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import make_engine
from app.perps.models import ExchangeAccount
from app.perps.services import venue_sync

log = logging.getLogger(__name__)
_scheduler = BackgroundScheduler(daemon=True)


def sync_all_active_accounts() -> None:
    engine = make_engine(get_settings().database_url)
    db = Session(engine)
    try:
        accounts = db.query(ExchangeAccount).filter(
            ExchangeAccount.venue.in_(venue_sync.SUPPORTED_VENUES),
            ExchangeAccount.is_active == True,  # noqa: E712
            ExchangeAccount.encrypted_credentials.isnot(None),
        ).all()
        for acc in accounts:
            if venue_sync.is_syncing(acc.id):
                continue
            try:
                venue_sync.sync_account(db, acc)
            except Exception:  # noqa: BLE001
                log.exception("scheduled sync failed for account %s (%s)", acc.id, acc.venue)
    finally:
        db.close()


def start_scheduler() -> None:
    _scheduler.add_job(sync_all_active_accounts, "interval", minutes=5,
                       id="perps_sync", replace_existing=True)
    if not _scheduler.running:
        _scheduler.start()
    log.info("perps scheduler started (every 5 min, Bybit + Hyperliquid)")


def shutdown_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
