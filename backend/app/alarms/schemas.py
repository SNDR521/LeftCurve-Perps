from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

PRICE_CONDITIONS = {"CROSS", "CROSS_UP", "CROSS_DOWN", "GTE", "LTE", "PCT_MOVE"}
POSITION_CONDITIONS = {"NEAR_STOP", "UPNL", "LIQ_DIST"}
PLAN_CONDITIONS = {"PLAN_LOSS_LIMIT", "PLAN_MAX_TRADES"}
TARGET_CONDITIONS = {
    "SYMBOL": PRICE_CONDITIONS,
    "POSITION": POSITION_CONDITIONS,
    "PLAN": PLAN_CONDITIONS,
}


class AlarmIn(BaseModel):
    target_type: Literal["SYMBOL", "POSITION", "PLAN"] = "SYMBOL"
    symbol: Optional[str] = None
    market: str = "CRYPTO"
    condition: str
    value: Optional[float] = None
    params: Optional[dict] = None
    trigger_mode: str = "ONCE"
    cooldown_seconds: int = 0
    expires_at: Optional[datetime] = None
    message: Optional[str] = None
    deliver: Optional[dict] = None

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v):
        return v.upper().strip() if v else v

    @field_validator("trigger_mode")
    @classmethod
    def _trigger_mode(cls, v):
        if v not in {"ONCE", "EVERY"}:
            raise ValueError(f"trigger_mode must be ONCE or EVERY, got {v!r}")
        return v

    @field_validator("market")
    @classmethod
    def _market(cls, v):
        if v not in {"CRYPTO", "EQUITY"}:
            raise ValueError(f"market must be CRYPTO or EQUITY, got {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_target_condition(self):
        allowed = TARGET_CONDITIONS.get(self.target_type)
        if allowed is None:
            raise ValueError(f"unknown target_type {self.target_type}")
        if self.condition not in allowed:
            raise ValueError(f"condition {self.condition} not valid for target {self.target_type}")
        if self.target_type in ("SYMBOL", "POSITION") and not self.symbol:
            raise ValueError(f"{self.target_type} alarms require a symbol")
        if self.target_type in ("SYMBOL", "POSITION") and self.value is None:
            raise ValueError(f"{self.target_type} alarms require a value")
        if self.target_type == "POSITION" and self.market != "CRYPTO":
            raise ValueError("POSITION alarms must use market CRYPTO")
        return self


class AlarmOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    target_type: str
    symbol: Optional[str]
    market: str
    condition: str
    value: Optional[float]
    params: Optional[dict]
    trigger_mode: str
    cooldown_seconds: int
    expires_at: Optional[datetime]
    enabled: bool
    message: Optional[str]
    deliver: Optional[dict]
    last_fired_at: Optional[datetime]
    fired_count: int
    status: str
    created_at: Optional[datetime]
