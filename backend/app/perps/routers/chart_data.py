"""Candle proxy for perps trade charts (public Bybit/Hyperliquid candles, short TTL cache)."""
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.perps.models import ExchangeAccount, Venue
from app.perps.services.candles import VALID_INTERVALS, choose_interval, fetch_klines, fetch_hl_klines

router = APIRouter(prefix="/chart-data", tags=["perps-chart"])

_cache: dict[tuple, tuple[float, dict]] = {}
_TTL_S = 60.0
_MAX_ENTRIES = 256


@router.get("")
def get_chart_data(symbol: str, from_ts: int, to_ts: int, interval: str | None = None,
                   account_id: int | None = None,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if to_ts <= from_ts:
        raise HTTPException(status_code=422, detail="to_ts must be after from_ts")
    iv = interval or choose_interval(to_ts - from_ts)
    if iv not in VALID_INTERVALS:
        raise HTTPException(status_code=422, detail=f"invalid interval {iv!r}")

    # Dispatch the candle source by the position's account venue. Default (no
    # account_id, or an account not owned by the user) = Bybit (back-compatible).
    venue = Venue.BYBIT
    if account_id is not None:
        acc = (db.query(ExchangeAccount)
               .filter(ExchangeAccount.id == account_id,
                       ExchangeAccount.user_id == user.id).first())
        if acc is not None:
            venue = acc.venue

    key = (venue.value, symbol, iv, from_ts, to_ts)
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    try:
        if venue == Venue.HYPERLIQUID:
            candles = fetch_hl_klines(symbol, iv, from_ts * 1000, to_ts * 1000)
        else:
            candles = fetch_klines(symbol, iv, from_ts * 1000, to_ts * 1000)
    except Exception as e:  # noqa: BLE001 — surface upstream failure as 502
        raise HTTPException(status_code=502, detail=f"kline fetch failed: {e}")
    out = {"symbol": symbol, "interval": iv, "candles": candles}
    if len(_cache) >= _MAX_ENTRIES:
        _cache.pop(next(iter(_cache)))  # evict oldest insertion, keep the rest warm
    _cache[key] = (now + _TTL_S, out)
    return out
