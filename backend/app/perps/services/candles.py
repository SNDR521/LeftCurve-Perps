"""Public Bybit kline fetcher (keyless) + interval selection for trade spans.

Bybit /v5/market/kline returns newest-first rows of
[startMs, open, high, low, close, volume, turnover], max 1000 per call.
"""
from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

PUBLIC_BASE = "https://api.bybit.com"
MAX_BARS = 1000
_INTERVALS = [(1, "1"), (3, "3"), (5, "5"), (15, "15"), (30, "30"), (60, "60"),
              (120, "120"), (240, "240"), (360, "360"), (720, "720")]
VALID_INTERVALS = {code for _, code in _INTERVALS} | {"D"}


def choose_interval(duration_seconds: float, max_bars: int = MAX_BARS) -> str:
    """Smallest Bybit interval that covers the span in <= max_bars bars."""
    minutes = max(duration_seconds, 60) / 60
    for mins, code in _INTERVALS:
        if minutes / mins <= max_bars:
            return code
    return "D"


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int,
                 client: httpx.Client | None = None) -> list[dict]:
    """Ascending OHLCV candles covering [start_ms, end_ms]. Pages newest→oldest."""
    own = client is None
    client = client or httpx.Client(timeout=15.0)
    try:
        raw: list[list] = []
        end = end_ms
        for _ in range(50):  # backstop: 50k bars max
            for attempt in range(4):
                resp = client.get(f"{PUBLIC_BASE}/v5/market/kline", params={
                    "category": "linear", "symbol": symbol, "interval": interval,
                    "start": start_ms, "end": end, "limit": MAX_BARS,
                })
                if resp.status_code != 429:
                    break
                log.warning("kline 429 for %s (attempt %d) — backing off %ds",
                            symbol, attempt, 2 ** attempt)
                time.sleep(2 ** attempt)
            resp.raise_for_status()
            data = resp.json()
            if data.get("retCode") != 0:
                raise RuntimeError(f"kline retCode={data.get('retCode')} {data.get('retMsg')}")
            rows = (data.get("result") or {}).get("list") or []
            if not rows:
                break
            raw.extend(rows)
            oldest = int(rows[-1][0])
            if oldest <= start_ms:
                break
            end = oldest - 1
        else:
            log.warning("kline page backstop hit symbol=%s interval=%s span=%s..%s — result truncated",
                        symbol, interval, start_ms, end_ms)

        seen: set[int] = set()
        candles = []
        for r in raw:
            t = int(r[0]) // 1000
            if t in seen:
                continue
            seen.add(t)
            candles.append({"time": t, "open": float(r[1]), "high": float(r[2]),
                            "low": float(r[3]), "close": float(r[4]),
                            "volume": float(r[5])})
        candles.sort(key=lambda c: c["time"])
        return candles
    finally:
        if own:
            client.close()


# Bybit interval code -> Hyperliquid interval string. HL has no 6h bar; 360 -> "4h".
HL_INTERVAL_MAP = {
    "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m",
    "60": "1h", "120": "2h", "240": "4h", "360": "4h", "720": "12h", "D": "1d",
}


def fetch_hl_klines(coin: str, interval: str, start_ms: int, end_ms: int, client=None) -> list[dict]:
    """Ascending OHLCV from Hyperliquid for a Bybit-style interval code.
    Public candleSnapshot — no credentials needed (a throwaway keyless client).
    `client` is accepted for call-signature parity with fetch_klines (the shared
    httpx client) but ignored — Hyperliquid uses its own keyless client here."""
    from app.perps.connectors.hyperliquid import HyperliquidClient
    hl_iv = HL_INTERVAL_MAP.get(interval, "1h")
    client = HyperliquidClient("")
    try:
        return client.candle_snapshot(coin, hl_iv, start_ms, end_ms)
    finally:
        client.close()


# Bybit interval code -> minutes per bar (for aggregating RiseX's 1m bars).
_CODE_MINUTES = {"1": 1, "3": 3, "5": 5, "15": 15, "30": 30, "60": 60,
                 "120": 120, "240": 240, "360": 360, "720": 720, "D": 1440}


def _aggregate(bars: list[dict], bucket_s: int) -> list[dict]:
    """Aggregate ascending 1m OHLCV bars into fixed-width time buckets."""
    if bucket_s <= 60:
        return bars
    buckets: dict[int, dict] = {}
    for b in bars:  # bars are time-ascending, so first seen = open, last = close
        k = (b["time"] // bucket_s) * bucket_s
        agg = buckets.get(k)
        if agg is None:
            buckets[k] = {"time": k, "open": b["open"], "high": b["high"],
                          "low": b["low"], "close": b["close"], "volume": b["volume"]}
        else:
            agg["high"] = max(agg["high"], b["high"])
            agg["low"] = min(agg["low"], b["low"])
            agg["close"] = b["close"]
            agg["volume"] += b["volume"]
    return [buckets[k] for k in sorted(buckets)]


def fetch_risex_klines(symbol: str, interval: str, start_ms: int, end_ms: int, client=None) -> list[dict]:
    """Ascending OHLCV from RiseX for a Bybit-style interval code. RiseX's
    trading-view-data endpoint keys by numeric market_id and serves only 1m bars,
    so we resolve the symbol -> market_id (public markets list) and aggregate the
    1m bars up to the requested interval. `client` accepted for signature parity,
    ignored (RiseX uses its own keyless market-data client). Raises if the symbol
    is unknown (surfaced as a 502 -> the chart shows 'unavailable')."""
    from app.config import get_settings
    from app.perps.connectors.risex import RiseXClient
    rc = RiseXClient("", get_settings().risex_api_base)  # public market data — no address
    try:
        market_id = next((mid for mid, name in rc.fetch_markets().items() if name == symbol), None)
        if market_id is None:
            raise RuntimeError(f"unknown RiseX market {symbol!r}")
        bars = rc.candle_snapshot(market_id, start_ms, end_ms)
    finally:
        rc.close()
    return _aggregate(bars, _CODE_MINUTES.get(interval, 1) * 60)
