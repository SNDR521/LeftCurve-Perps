"""Alarm rules: TradingView-style + LeftCurve conditions. Phase 1 uses the
price conditions only; POSITION/PLAN targets land in Phase 3 but the columns
exist now so the schema is stable."""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, Boolean, JSON, ForeignKey, Index,
    UniqueConstraint,
)
from app.database import Base


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Alarm(Base):
    __tablename__ = "alarms"
    __table_args__ = (
        Index("ix_alarms_user_status", "user_id", "status"),
        Index("ix_alarms_market_status", "market", "status"),
    )
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    target_type = Column(String, nullable=False, default="SYMBOL")   # SYMBOL | POSITION | PLAN
    symbol = Column(String, nullable=True)                            # stored UPPER
    market = Column(String, nullable=False, default="CRYPTO")         # CRYPTO | EQUITY
    condition = Column(String, nullable=False)                        # CROSS|CROSS_UP|CROSS_DOWN|GTE|LTE|PCT_MOVE
    value = Column(Float, nullable=True)
    params = Column(JSON, nullable=True)                              # {ref_price, window, unit, ...}
    trigger_mode = Column(String, nullable=False, default="ONCE")     # ONCE | EVERY
    cooldown_seconds = Column(Integer, nullable=False, default=0)     # EVERY: min gap between fires
    expires_at = Column(DateTime, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    message = Column(Text, nullable=True)
    deliver = Column(JSON, nullable=True)                             # {in_app: bool, telegram: bool}
    # state
    last_price = Column(Float, nullable=True)
    last_fired_at = Column(DateTime, nullable=True)
    fired_count = Column(Integer, nullable=False, default=0)
    snoozed_until = Column(DateTime, nullable=True)                    # muted until this UTC time (Telegram /snooze)
    status = Column(String, nullable=False, default="ACTIVE")         # ACTIVE | PAUSED | TRIGGERED | EXPIRED
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class TelegramLink(Base):
    __tablename__ = "telegram_links"
    __table_args__ = (UniqueConstraint("user_id", name="uq_telegram_link_user"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    chat_id = Column(String, nullable=True)            # set once /start <code> is received
    username = Column(String, nullable=True)           # telegram @username, for display
    bot_token_enc = Column(Text, nullable=True)        # DEPRECATED (unused): per-user bot tokens retired; shared bot only
    linked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)


class TelegramLinkCode(Base):
    __tablename__ = "telegram_link_codes"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=_now)


class TelegramBotConfig(Base):
    """Singleton (id=1) shared-bot config, set by an admin from Settings.
    Supersedes the TELEGRAM_* env vars (which remain a fallback)."""
    __tablename__ = "telegram_bot_config"
    id = Column(Integer, primary_key=True)
    bot_token_enc = Column(Text, nullable=True)      # Fernet-encrypted bot token
    bot_username = Column(String, nullable=True)      # from Telegram getMe
    webhook_secret = Column(String, nullable=True)    # generated once, stable
    public_base_url = Column(String, nullable=True)
    webhook_set_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
