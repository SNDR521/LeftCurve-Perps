"""Pydantic schemas for the workflow layer."""
from __future__ import annotations

from datetime import date as _date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


# ── Playbook ──────────────────────────────────────────────────────────────────

class PlaybookIn(BaseModel):
    """Create/update fields for a Playbook. name is required; rule texts are optional."""
    name: str
    context_requirements: Optional[str] = None
    entry_triggers: Optional[str] = None
    invalidation: Optional[str] = None
    management: Optional[str] = None
    notes: Optional[str] = None


class PlaybookUpdate(BaseModel):
    """Partial-update fields — every field optional."""
    name: Optional[str] = None
    context_requirements: Optional[str] = None
    entry_triggers: Optional[str] = None
    invalidation: Optional[str] = None
    management: Optional[str] = None
    notes: Optional[str] = None


class PlaybookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    context_requirements: Optional[str] = None
    entry_triggers: Optional[str] = None
    invalidation: Optional[str] = None
    management: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Injected by the endpoint; not stored in DB.
    stats: dict = {}


# ── PlanCard ──────────────────────────────────────────────────────────────────

class PlanCardIn(BaseModel):
    """Editable plan-card fields. Every field is optional so a PUT can be a
    partial update — only the keys present in the request body are applied
    (the router uses ``model_dump(exclude_unset=True)``)."""
    session_start_hour: int | None = None
    playbook_id: int | None = None
    a_setup_note: str | None = None
    shortlist: list[str] | None = None
    not_today: str | None = None
    mental_state: str | None = None
    max_trades: int | None = None
    max_daily_loss: float | None = None
    r_per_trade: float | None = None
    circuit_rules: str | None = None
    key_lesson: str | None = None
    tomorrow_focus: str | None = None
    htf_bias: str | None = None
    ltf_bias: str | None = None
    expectations: str | None = None
    key_levels_buy: str | None = None
    key_levels_sell: str | None = None
    did_well: str | None = None
    did_poorly: str | None = None
    eod_why: str | None = None

    @field_validator("shortlist")
    @classmethod
    def normalize_shortlist(cls, v):
        if v is None:
            return v
        return [s.strip().upper() for s in v if s and s.strip()]


class PlanCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    date: _date
    session_start_hour: int
    regime_snapshot: dict | None = None
    playbook_id: int | None = None
    a_setup_note: str | None = None
    shortlist: list[str] | None = None
    not_today: str | None = None
    mental_state: str | None = None
    max_trades: int | None = None
    max_daily_loss: float | None = None
    r_per_trade: float | None = None
    circuit_rules: str | None = None
    key_lesson: str | None = None
    tomorrow_focus: str | None = None
    htf_bias: str | None = None
    ltf_bias: str | None = None
    expectations: str | None = None
    key_levels_buy: str | None = None
    key_levels_sell: str | None = None
    did_well: str | None = None
    did_poorly: str | None = None
    eod_why: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # ``date`` serializes to an ISO ``YYYY-MM-DD`` string via Pydantic's default
    # JSON encoding for ``datetime.date``.


# ── Review ────────────────────────────────────────────────────────────────────

class ReviewIn(BaseModel):
    """Upsert body for a saved review. ``period_type`` must be WEEK or MONTH;
    an invalid value fails validation → 422. ``period_start`` is accepted as-is
    (any date — not forced to a Monday/1st; callers conventionally pass the
    period's first day). ``workspace`` is prop|perps (defaults prop). The three
    judgment fields are optional free text."""
    period_type: str
    period_start: _date
    workspace: str = "perps"
    what_worked: Optional[str] = None
    what_didnt: Optional[str] = None
    next_focus: Optional[str] = None
    probe_flags: Optional[list[str]] = None
    problem: Optional[str] = None
    why: Optional[str] = None

    @field_validator("period_type")
    @classmethod
    def validate_period_type(cls, v):
        v = (v or "").upper()
        if v not in ("WEEK", "MONTH"):
            raise ValueError("period_type must be WEEK or MONTH")
        return v

    @field_validator("workspace")
    @classmethod
    def validate_workspace(cls, v):
        v = (v or "").lower()
        if v not in ("prop", "perps"):
            raise ValueError("workspace must be prop or perps")
        return v


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    user_id: Optional[int] = None
    period_type: str
    period_start: _date
    workspace: Optional[str] = None
    what_worked: Optional[str] = None
    what_didnt: Optional[str] = None
    next_focus: Optional[str] = None
    probe_flags: Optional[list[str]] = None
    problem: Optional[str] = None
    why: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Watchlist ─────────────────────────────────────────────────────────────────

class LevelIn(BaseModel):
    """A single price level on a watchlist item."""
    price: float
    label: Optional[str] = None

    @field_validator("price")
    @classmethod
    def price_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("price must be > 0")
        return v

    @field_validator("label")
    @classmethod
    def label_max_40(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 40:
            raise ValueError("label must be ≤ 40 characters")
        return v


class WatchlistIn(BaseModel):
    """Create / update body for a WatchlistItem.

    symbol is normalized to upper-case + stripped; market must be CRYPTO or
    EQUITY.  Every field except symbol and market is optional so a PUT can be
    a partial update (router uses model_dump(exclude_unset=True)).
    """
    symbol: str
    market: str
    note: Optional[str] = None
    levels: list[LevelIn] = []

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("symbol must not be empty")
        return v

    @field_validator("market")
    @classmethod
    def validate_market(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in {"CRYPTO", "EQUITY"}:
            raise ValueError("market must be CRYPTO or EQUITY")
        return v


class WatchlistUpdate(BaseModel):
    """Partial-update body — every field optional."""
    note: Optional[str] = None
    levels: Optional[list[LevelIn]] = None

    @field_validator("levels")
    @classmethod
    def _validate_levels(cls, v):
        # LevelIn validators already run; just pass through
        return v


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    symbol: str
    market: str
    note: Optional[str] = None
    levels: Optional[list[Any]] = None
    last_price: Optional[float] = None
    last_checked: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ── Alert ─────────────────────────────────────────────────────────────────────

class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    symbol: Optional[str] = None
    payload: Optional[Any] = None
    triggered_at: datetime
    seen: bool
