from pydantic import BaseModel
from typing import Optional


# ── Analytics schemas shared across modules ────────────────────────
# Shared analytics response schemas used across perps services.

class OverviewMetrics(BaseModel):
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    avg_r_multiple: Optional[float] = None
    avg_risk_amount: Optional[float] = None
    period_start_balance: Optional[float] = None
    max_drawdown: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    avg_duration_seconds: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None

class DailyPnl(BaseModel):
    date: str  # YYYY-MM-DD
    pnl: float
    trade_count: int
    wins: int
    losses: int
    cumulative_pnl: float

class PerformanceByGroup(BaseModel):
    group: str  # symbol, setup, tag name, weekday, etc.
    trade_count: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    profit_factor: Optional[float] = None
    max_streak: Optional[int] = None

class SessionMetrics(BaseModel):
    session: str           # "New York", "London", "Tokyo", "Off-hours"
    utc_hours: str         # display label e.g. "13:00–22:00 UTC"
    trade_count: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    profit_factor: Optional[float] = None
    best_trade: float
    worst_trade: float

class HoldtimeBucket(BaseModel):
    bucket: str            # "<5m", "5–30m", etc.
    min_seconds: int
    max_seconds: int
    trade_count: int
    win_rate: float
    total_pnl: float
    avg_pnl: float
    profit_factor: Optional[float] = None

class HeatmapCell(BaseModel):
    weekday: int           # 0=Mon … 6=Sun
    hour: int              # 0–23 UTC
    trade_count: int
    total_pnl: float
    win_rate: float
