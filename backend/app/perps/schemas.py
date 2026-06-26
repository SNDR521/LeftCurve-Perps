import re
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator

from app.perps.models import Venue, AssetClass, Side, Direction, PositionStatus, OpenedAtSource


class ExchangeAccountCreate(BaseModel):
    venue: Venue
    label: str
    api_key: str | None = None
    api_secret: str | None = None
    address: str | None = None  # Hyperliquid wallet address (0x + 40 hex)

    @field_validator("address")
    @classmethod
    def address_is_hex(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", v):
            raise ValueError("address must be 0x followed by 40 hex characters")
        return v.lower()


class ExchangeAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    venue: Venue
    label: str
    is_active: bool
    created_at: datetime | None = None
    has_credentials: bool = False
    last_synced_at: datetime | None = None
    last_sync_error: str | None = None
    syncing: bool = False
    sync_progress: dict | None = None


class FillCreate(BaseModel):
    exchange_account_id: int
    symbol: str
    asset_class: AssetClass
    side: Side
    price: float
    quantity: float
    fee: float = 0.0
    fee_currency: str | None = None
    funding_amount: float | None = None
    stop_price: float | None = None
    risk_amount: float | None = None
    executed_at: datetime
    order_id: str | None = None
    external_fill_id: str | None = None


class FillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exchange_account_id: int
    symbol: str
    asset_class: AssetClass
    side: Side
    price: float
    quantity: float
    fee: float
    funding_amount: float | None
    stop_price: float | None
    risk_amount: float | None
    executed_at: datetime
    order_id: str | None = None


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    exchange_account_id: int
    symbol: str
    asset_class: AssetClass
    direction: Direction
    status: PositionStatus
    opened_at: datetime
    closed_at: datetime | None
    avg_entry: float
    avg_exit: float | None
    quantity: float
    realized_pnl: float
    total_fees: float
    total_funding: float
    r_multiple: float | None
    duration_seconds: int | None
    position_key: str | None = None
    opened_at_source: OpenedAtSource | None = None
    mfe_price: float | None = None
    mae_price: float | None = None
    mfe_usd: float | None = None
    mae_usd: float | None = None
    leverage: float | None = None


class TargetIn(BaseModel):
    price: float
    pct: float
    triggered: bool = False


class PerpsJournalIn(BaseModel):
    position_key: str
    setup_name: str | None = None
    notes: str | None = None
    emotion_before: str | None = None
    emotion_after: str | None = None
    rating: int | None = None
    mistakes: str | None = None
    lessons: str | None = None
    grade: str | None = None
    mistake_tags: list[str] | None = None
    followed_plan: bool | None = None
    was_overtrading: bool | None = None
    stop_price: float | None = None
    stop_triggered: bool | None = None
    targets: list[TargetIn] | None = None

    @field_validator("targets")
    @classmethod
    def targets_max_100pct(cls, v):
        if v and sum(t.pct for t in v) > 100.0 + 1e-9:
            raise ValueError("targets cover more than 100% of the position")
        return v


class PerpsTagIn(BaseModel):
    name: str
    color: str | None = None


class PerpsTagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    color: str | None = None


class TagLink(BaseModel):
    position_key: str
    tag_id: int
