"""Workspace-agnostic workflow layer: playbooks, daily plan cards, reviews."""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, Text, Date, DateTime, ForeignKey, JSON,
    UniqueConstraint, Boolean, Index,
)

from app.database import Base


def _now():
    return datetime.now(timezone.utc)


class Playbook(Base):
    __tablename__ = "playbooks"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_playbook_user_name"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    context_requirements = Column(Text, nullable=True)
    entry_triggers = Column(Text, nullable=True)
    invalidation = Column(Text, nullable=True)
    management = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class PlanCard(Base):
    __tablename__ = "plan_cards"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_plan_card_user_date"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    session_start_hour = Column(Integer, nullable=False, default=0)  # UTC hour the day starts
    regime_snapshot = Column(JSON, nullable=True)                    # frozen at creation
    playbook_id = Column(Integer, ForeignKey("playbooks.id"), nullable=True)
    a_setup_note = Column(Text, nullable=True)
    shortlist = Column(JSON, nullable=True)                          # ["BTCUSDT", ...] uppercased
    not_today = Column(Text, nullable=True)
    mental_state = Column(String, nullable=True)
    max_trades = Column(Integer, nullable=True)
    max_daily_loss = Column(Float, nullable=True)                    # positive magnitude
    r_per_trade = Column(Float, nullable=True)
    circuit_rules = Column(Text, nullable=True)
    key_lesson = Column(Text, nullable=True)
    tomorrow_focus = Column(Text, nullable=True)
    # Pre-market read
    htf_bias = Column(String, nullable=True)          # Long | Short | Neutral
    ltf_bias = Column(String, nullable=True)          # Long | Short | Neutral
    expectations = Column(Text, nullable=True)
    key_levels_buy = Column(Text, nullable=True)
    key_levels_sell = Column(Text, nullable=True)
    # End-of-day reflection
    did_well = Column(Text, nullable=True)
    did_poorly = Column(Text, nullable=True)
    eod_why = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("user_id", "period_type", "period_start",
                                       "workspace", name="uq_review_user_period_ws"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    period_type = Column(String, nullable=False)     # WEEK | MONTH
    period_start = Column(Date, nullable=False)
    workspace = Column(String, nullable=False, server_default="prop")  # prop | perps
    what_worked = Column(Text, nullable=True)
    what_didnt = Column(Text, nullable=True)
    next_focus = Column(Text, nullable=True)
    probe_flags = Column(JSON, nullable=True)   # ticked weekly-review probe items
    problem = Column(Text, nullable=True)       # the recurring problem
    why = Column(Text, nullable=True)           # why it recurs
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
    )
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False)                      # stored UPPER; normalisation in schemas
    market = Column(String, nullable=False)                      # 'CRYPTO' | 'EQUITY'
    note = Column(Text, nullable=True)
    levels = Column(JSON, nullable=True)                         # [{price: float, label: str|null}]
    last_price = Column(Float, nullable=True)
    last_checked = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_user_seen", "user_id", "seen"),
    )
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)                        # 'LEVEL_CROSS' | 'THEME_STATUS'
    symbol = Column(String, nullable=True)
    payload = Column(JSON, nullable=True)
    triggered_at = Column(DateTime, nullable=False)
    seen = Column(Boolean, nullable=False, default=False)
