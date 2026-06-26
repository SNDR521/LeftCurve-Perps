"""Minimal keyless Hyperliquid `/info` client (read-only, address-only).

Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
All requests POST JSON to {base}/info with a `type` discriminator. No signing.
Returns shapes for open positions / wallet match BybitClient so build_cockpit
(Phase 2) is reused unchanged.
"""
from __future__ import annotations

import logging
import time
from typing import Iterator

import httpx

log = logging.getLogger(__name__)

MAINNET = "https://api.hyperliquid.xyz"
PAGE_LIMIT = 2000   # userFillsByTime returns at most this many rows per response
MAX_PAGES = 1000    # hard backstop against a non-advancing cursor
HOUR_MS = 3_600_000  # Hyperliquid funds hourly, on the hour


class HyperliquidError(Exception):
    pass


class HyperliquidClient:
    def __init__(self, address: str, base_url: str = MAINNET,
                 timeout: float = 30.0, min_interval_s: float = 0.1):
        self.address = address
        self.base_url = base_url
        self.min_interval_s = min_interval_s
        self._last_request = 0.0
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _post(self, body: dict):
        if self.min_interval_s:
            wait = self.min_interval_s - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
        for attempt in range(5):
            self._last_request = time.monotonic()
            resp = self._client.post(f"{self.base_url}/info", json=body)
            if resp.status_code == 429:
                log.warning("hyperliquid %s HTTP 429 (attempt %d) — backing off %ds",
                            body.get("type"), attempt, 2 ** attempt)
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        raise HyperliquidError(f"{body.get('type')} rate-limited after retries")

    def iter_fills_by_time(self, start_ms: int, end_ms: int) -> Iterator[dict]:
        """Pages userFillsByTime ascending; advances startTime past the last fill
        time each page. Stops on a short page, an empty page, a cursor that fails
        to advance, or MAX_PAGES (the Bybit pagination lesson: never trust a cursor)."""
        cursor = int(start_ms)
        for page in range(MAX_PAGES):
            rows = self._post({"type": "userFillsByTime", "user": self.address,
                               "startTime": cursor, "endTime": int(end_ms)}) or []
            for r in rows:
                yield r
            if len(rows) < PAGE_LIMIT:
                return
            last_time = int(rows[-1]["time"])
            next_cursor = last_time + 1
            # Bail when the cursor would not advance past cursor+1 (i.e. last_time <= cursor:
            # the whole page sits on the starting ms). Fills are always >= startTime, so a
            # normal page has last_time > cursor and continues.
            if next_cursor <= cursor + 1:
                log.warning("hyperliquid fills cursor stuck at %d — stopping", cursor)
                return
            cursor = next_cursor
        log.warning("hyperliquid fills: hit MAX_PAGES (%d)", MAX_PAGES)

    def iter_funding(self, start_ms: int, end_ms: int) -> Iterator[dict]:
        rows = self._post({"type": "userFunding", "user": self.address,
                           "startTime": int(start_ms), "endTime": int(end_ms)}) or []
        yield from rows

    def _clearinghouse_state(self) -> dict:
        return self._post({"type": "clearinghouseState", "user": self.address}) or {}

    def _stop_by_coin(self) -> dict:
        """coin -> stop-loss trigger price, from the account's open reduce-only Stop
        trigger orders. Hyperliquid keeps a position's stop as a separate trigger
        order (not on the position), so the cockpit reads it here. Take-profit
        triggers are excluded. Failure-isolated — returns {} on any error."""
        try:
            orders = self._post({"type": "frontendOpenOrders", "user": self.address}) or []
        except Exception:  # noqa: BLE001
            return {}
        stops: dict = {}
        for o in orders:
            if not o.get("isTrigger"):
                continue
            if "stop" not in str(o.get("orderType") or "").lower():
                continue  # exclude take-profit triggers
            if not (o.get("reduceOnly") or o.get("isPositionTpsl")):
                continue  # only a position-reducing stop counts (not a stop-entry)
            coin, px = o.get("coin"), o.get("triggerPx")
            if coin and px is not None and coin not in stops:
                stops[coin] = float(px)
        return stops

    def fetch_open_positions(self) -> list[dict]:
        """clearinghouseState.assetPositions -> Bybit-compatible position rows
        (size > 0 only). Keys: symbol, side, size, avgPrice, unrealisedPnl,
        liqPrice, leverage, stopLoss, tradeMode. stopLoss is read from the
        account's open Stop trigger orders (Hyperliquid has none on the position)."""
        state = self._clearinghouse_state()
        stops = self._stop_by_coin()
        out: list[dict] = []
        for ap in state.get("assetPositions") or []:
            p = ap.get("position") or {}
            szi = float(p.get("szi") or 0.0)
            if szi == 0.0:
                continue
            lev = p.get("leverage") or {}
            out.append({
                "symbol": p.get("coin"),
                "side": "Buy" if szi > 0 else "Sell",
                "size": abs(szi),
                "avgPrice": float(p.get("entryPx") or 0.0),
                "unrealisedPnl": float(p.get("unrealizedPnl") or 0.0),
                "liqPrice": float(p["liquidationPx"]) if p.get("liquidationPx") is not None else None,
                "leverage": float(lev.get("value")) if isinstance(lev, dict) and lev.get("value") is not None else None,
                "stopLoss": stops.get(p.get("coin")),   # from open Stop trigger orders
                "tradeMode": 0,
            })
        return out

    def fetch_wallet_balance(self) -> dict:
        state = self._clearinghouse_state()
        ms = state.get("marginSummary") or {}
        equity = float(ms.get("accountValue") or 0.0)
        return {
            "equity": equity,
            "balance": equity,
            "available": float(state.get("withdrawable") or 0.0),
        }

    def fetch_tickers(self, symbols: list[str] | None = None) -> dict:
        """Bybit-compatible mark/funding snapshot from metaAndAssetCtxs.

        funding is normalized to an 8h-equivalent rate (HL funds hourly; Bybit's
        rate and build_cockpit's 3-per-day projection both assume an 8h cadence),
        so the cockpit's funding numbers stay correct and comparable across venues.
        Pass ``symbols`` to filter; ``None`` returns the full perp universe (~170).
        """
        data = self._post({"type": "metaAndAssetCtxs"}) or []
        if len(data) < 2:
            return {}
        universe = (data[0] or {}).get("universe") or []
        ctxs = data[1] or []
        wanted = set(symbols) if symbols else None
        next_funding = ((int(time.time() * 1000) // HOUR_MS) + 1) * HOUR_MS
        out: dict = {}
        for meta, ctx in zip(universe, ctxs):
            sym = meta.get("name")
            if not sym or (wanted is not None and sym not in wanted):
                continue
            out[sym] = {
                "mark_price": float(ctx.get("markPx") or 0.0),
                "funding_rate": float(ctx.get("funding") or 0.0) * 8,  # hourly -> 8h-equiv
                "next_funding_time": next_funding,
            }
        return out

    def candle_snapshot(self, coin: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
        """Public candleSnapshot -> ascending lightweight-charts OHLCV
        [{time(seconds), open, high, low, close, volume}]. `interval` is an HL
        interval string (e.g. "1h")."""
        rows = self._post({"type": "candleSnapshot",
                           "req": {"coin": coin, "interval": interval,
                                   "startTime": int(start_ms), "endTime": int(end_ms)}}) or []
        # Defensive across all fields (a still-forming live bar can be partial);
        # skip rows with no open time rather than crash the whole fetch.
        candles = [{
            "time": int(r["t"]) // 1000,
            "open": float(r.get("o") or 0.0), "high": float(r.get("h") or 0.0),
            "low": float(r.get("l") or 0.0), "close": float(r.get("c") or 0.0),
            "volume": float(r.get("v") or 0.0),
        } for r in rows if r.get("t") is not None]
        candles.sort(key=lambda bar: bar["time"])
        return candles
