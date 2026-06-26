"""Single source of truth for the shared Telegram bot config. Reads the
TelegramBotConfig singleton (admin-set via Settings); falls back to the
TELEGRAM_* env vars for backward compatibility."""
import logging
from app.config import get_settings
from app.core.security import decrypt_credentials

log = logging.getLogger(__name__)


def get_config(db):
    from app.alarms.models import TelegramBotConfig
    return db.query(TelegramBotConfig).first()


def shared_token(db) -> str:
    cfg = get_config(db)
    if cfg and cfg.bot_token_enc:
        try:
            return decrypt_credentials(cfg.bot_token_enc).get("token") or ""
        except Exception:  # noqa: BLE001
            log.exception("telegram shared-bot token decrypt failed")
    return get_settings().telegram_bot_token or ""


def bot_username(db):
    cfg = get_config(db)
    if cfg and cfg.bot_username:
        return cfg.bot_username
    return get_settings().telegram_bot_username or None


def webhook_secret(db) -> str:
    cfg = get_config(db)
    if cfg and cfg.webhook_secret:
        return cfg.webhook_secret
    return get_settings().telegram_webhook_secret or ""
