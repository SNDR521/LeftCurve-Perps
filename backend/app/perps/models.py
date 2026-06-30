import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum as SAEnum, JSON,
    Table, UniqueConstraint, Text,
)

from app.database import Base


class Venue(str, enum.Enum):
    BYBIT = "BYBIT"
    HYPERLIQUID = "HYPERLIQUID"
    LIGHTER = "LIGHTER"
    RISEX = "RISEX"


class AssetClass(str, enum.Enum):
    PERP = "PERP"
    SPOT = "SPOT"


class Side(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class Direction(str, enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OpenedAtSource(str, enum.Enum):
    EXACT = "EXACT"          # entry time verified from a complete fill chain
    ESTIMATED = "ESTIMATED"  # entry time unknown (≈ close time); excluded from time analytics


class ExchangeAccount(Base):
    __tablename__ = "exchange_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    venue = Column(SAEnum(Venue), nullable=False)
    label = Column(String, nullable=False)
    encrypted_credentials = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    sync_cursor = Column(String, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_sync_error = Column(String, nullable=True)
    sync_progress = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Fill(Base):
    __tablename__ = "fills"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    exchange_account_id = Column(Integer, ForeignKey("exchange_accounts.id"), nullable=False, index=True)
    venue = Column(SAEnum(Venue), nullable=False)
    external_fill_id = Column(String, nullable=True, index=True)
    order_id = Column(String, nullable=True)
    symbol = Column(String, nullable=False, index=True)
    asset_class = Column(SAEnum(AssetClass), nullable=False)
    side = Column(SAEnum(Side), nullable=False)
    price = Column(Float, nullable=False)
    quantity = Column(Float, nullable=False)
    fee = Column(Float, nullable=False, default=0.0)
    fee_currency = Column(String, nullable=True)
    funding_amount = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    risk_amount = Column(Float, nullable=True)
    executed_at = Column(DateTime, nullable=False)
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    exchange_account_id = Column(Integer, ForeignKey("exchange_accounts.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    asset_class = Column(SAEnum(AssetClass), nullable=False)
    direction = Column(SAEnum(Direction), nullable=False)
    status = Column(SAEnum(PositionStatus), nullable=False)
    opened_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime, nullable=True)
    avg_entry = Column(Float, nullable=False)
    avg_exit = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=False)
    total_fees = Column(Float, nullable=False)
    total_funding = Column(Float, nullable=False)
    r_multiple = Column(Float, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    position_key = Column(String, nullable=True, index=True)
    opened_at_source = Column(SAEnum(OpenedAtSource), nullable=False,
                              server_default="ESTIMATED")
    mfe_price = Column(Float, nullable=True)
    mae_price = Column(Float, nullable=True)
    mfe_usd = Column(Float, nullable=True)
    mae_usd = Column(Float, nullable=True)
    leverage = Column(Float, nullable=True)


class BalanceSnapshot(Base):
    """Daily wallet balance (kind=SNAPSHOT, ts=UTC midnight of the day) and
    individual transfer events (kind=TRANSFER_IN/TRANSFER_OUT, ts=event time)
    from Bybit's transaction log — the true equity curve's raw material."""
    __tablename__ = "balance_snapshots"
    __table_args__ = (UniqueConstraint("exchange_account_id", "ts", "kind",
                                       name="uq_balance_snapshot"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    exchange_account_id = Column(Integer, ForeignKey("exchange_accounts.id"),
                                 nullable=False, index=True)
    ts = Column(DateTime, nullable=False)
    balance = Column(Float, nullable=False)
    kind = Column(String, nullable=False)   # SNAPSHOT | TRANSFER_IN | TRANSFER_OUT


class PositionFill(Base):
    """Attribution link: which fills constitute a position's story (entry,
    exits, funding). Rebuilt by the linker after every sync — never authoritative
    for P&L."""
    __tablename__ = "position_fills"
    __table_args__ = (UniqueConstraint("position_id", "fill_id", name="uq_position_fill"),)
    id = Column(Integer, primary_key=True, index=True)
    position_id = Column(Integer, ForeignKey("positions.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    fill_id = Column(Integer, ForeignKey("fills.id", ondelete="CASCADE"),
                     nullable=False, index=True)


perps_position_tags = Table(
    "perps_position_tags", Base.metadata,
    Column("id", Integer, primary_key=True, index=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("position_key", String, nullable=False, index=True),
    Column("tag_id", Integer, ForeignKey("perps_tags.id", ondelete="CASCADE"), nullable=False),
)


class PerpsTag(Base):
    __tablename__ = "perps_tags"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    color = Column(String, nullable=True)


class PerpsJournal(Base):
    __tablename__ = "perps_journal"
    __table_args__ = (UniqueConstraint("user_id", "position_key", name="uq_perps_journal_user_poskey"),)
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    position_key = Column(String, nullable=False, index=True)
    setup_name = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    emotion_before = Column(String, nullable=True)
    emotion_after = Column(String, nullable=True)
    rating = Column(Integer, nullable=True)
    mistakes = Column(Text, nullable=True)
    lessons = Column(Text, nullable=True)
    grade = Column(String, nullable=True)
    mistake_tags = Column(JSON, nullable=True)
    followed_plan = Column(Boolean, nullable=True)
    was_overtrading = Column(Boolean, default=False)
    stop_price = Column(Float, nullable=True)
    stop_triggered = Column(Boolean, default=False)
    targets = Column(JSON, nullable=True)          # [{price, pct, triggered}]
    screenshot_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
