"""Minimal signed Bybit V5 REST client (linear perps).

Docs: https://bybit-exchange.github.io/docs/v5/intro
Read-only endpoints used:
  GET /v5/execution/list           (trade fills)
  GET /v5/account/transaction-log  (funding settlements)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Iterator, Optional
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)

RECV_WINDOW = "5000"
MAINNET = "https://api.bybit.com"
MAX_PAGES = 1000  # hard backstop against a non-terminating Bybit cursor
EMPTY_PAGE_LIMIT = 3  # consecutive empty pages before we treat the window as exhausted


class BybitError(Exception):
    def __init__(self, message: str, ret_code: int | None = None):
        super().__init__(message)
        self.ret_code = ret_code


def _query_string(params: dict) -> str:
    # Deterministic, sorted; the exact string is what we sign and send.
    return urlencode(sorted((k, v) for k, v in params.items() if v is not None))


def _sign(secret: str, timestamp: str, api_key: str, recv_window: str, query_string: str) -> str:
    payload = f"{timestamp}{api_key}{recv_window}{query_string}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


class BybitClient:
    def __init__(self, api_key: str, api_secret: str, base_url: str = MAINNET,
                 timeout: float = 30.0, min_interval_s: float = 0.0):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.min_interval_s = min_interval_s
        self._last_request = 0.0
        self._client = httpx.Client(timeout=timeout)

    def _signed_get(self, path: str, params: dict) -> dict:
        if self.min_interval_s:
            wait = self.min_interval_s - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
        self._last_request = time.monotonic()
        qs = _query_string(params)
        ts = str(int(time.time() * 1000))
        sig = _sign(self.api_secret, ts, self.api_key, RECV_WINDOW, qs)
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": sig,
        }
        for attempt in range(5):
            resp = self._client.get(f"{self.base_url}{path}?{qs}", headers=headers)
            if resp.status_code == 429:
                log.warning("bybit %s HTTP 429 (attempt %d) — backing off %ds", path, attempt, 2 ** attempt)
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            code = data.get("retCode")
            if code in (10006, 10018):  # rate limit
                log.warning("bybit %s retCode=%s (attempt %d) — backing off %ds", path, code, attempt, 2 ** attempt)
                time.sleep(2 ** attempt)
                continue
            if code != 0:
                raise BybitError(f"{path} retCode={code} {data.get('retMsg')}")
            return data
        raise BybitError(f"{path} rate-limited after retries")

    def _paged(self, path: str, params: dict) -> Iterator[dict]:
        cursor: Optional[str] = None
        total = 0
        empty_streak = 0
        for page in range(MAX_PAGES):
            page_params = {**params}
            if cursor:
                page_params["cursor"] = cursor
            data = self._signed_get(path, page_params)
            result = data.get("result") or {}
            rows = result.get("list") or []
            total += len(rows)
            for row in rows:
                yield row
            next_cursor = result.get("nextPageCursor") or ""
            empty_streak = empty_streak + 1 if not rows else 0
            if page % 10 == 0 or not rows:
                log.info("bybit %s page=%d rows=%d total=%d cursor=%r next=%r empties=%d",
                         path, page, len(rows), total, (cursor or "")[:14], (next_cursor or "")[:14], empty_streak)
            # Terminate on: no further cursor (true end), a cursor that stopped
            # advancing (stuck), or SEVERAL consecutive empty pages. A single empty
            # page must NOT stop us — Bybit intermittently returns an empty list with
            # a live, advancing cursor mid-stream, and stopping there silently dropped
            # the tail of busy windows (lost fills -> positions never net flat).
            if not next_cursor or next_cursor == cursor or empty_streak >= EMPTY_PAGE_LIMIT:
                return
            cursor = next_cursor
        log.warning("%s: hit MAX_PAGES (%d) — cursor may not be terminating", path, MAX_PAGES)

    def iter_executions(self, start_ms: int, end_ms: int) -> Iterator[dict]:
        yield from self._paged("/v5/execution/list", {
            "category": "linear", "startTime": start_ms, "endTime": end_ms, "limit": 100,
        })

    def iter_funding(self, start_ms: int, end_ms: int) -> Iterator[dict]:
        yield from self._paged("/v5/account/transaction-log", {
            "accountType": "UNIFIED", "category": "linear", "type": "SETTLEMENT",
            "startTime": start_ms, "endTime": end_ms, "limit": 100,
        })

    def iter_closed_pnl(self, start_ms: int, end_ms: int) -> Iterator[dict]:
        yield from self._paged("/v5/position/closed-pnl", {
            "category": "linear", "startTime": start_ms, "endTime": end_ms, "limit": 100,
        })

    def fetch_tickers(self, symbols: list[str] | None = None) -> dict:
        """Public mark price / funding snapshot for linear perps (keyless)."""
        resp = self._client.get(f"{self.base_url}/v5/market/tickers",
                                params={"category": "linear"})
        resp.raise_for_status()
        data = resp.json()
        if data.get("retCode") != 0:
            raise BybitError(f"tickers retCode={data.get('retCode')} {data.get('retMsg')}")
        out = {}
        wanted = set(symbols) if symbols else None
        for r in (data.get("result") or {}).get("list") or []:
            sym = r.get("symbol")
            if not sym or (wanted is not None and sym not in wanted):
                continue
            out[sym] = {
                "mark_price": float(r.get("markPrice") or 0.0),
                "funding_rate": float(r.get("fundingRate") or 0.0),
                "next_funding_time": int(r.get("nextFundingTime") or 0),
            }
        return out

    def fetch_wallet_balance(self) -> dict:
        data = self._signed_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        rows = (data.get("result") or {}).get("list") or []
        acct = rows[0] if rows else {}
        return {
            "equity": float(acct.get("totalEquity") or 0.0),
            "balance": float(acct.get("totalWalletBalance") or 0.0),
            "available": float(acct.get("totalAvailableBalance") or 0.0),
        }

    def iter_transaction_log(self, start_ms: int, end_ms: int) -> Iterator[dict]:
        """ALL transaction-log rows (no type filter) — balance snapshots need
        every event's cashBalance, and TRANSFER_IN/OUT rows mark deposits."""
        yield from self._paged("/v5/account/transaction-log", {
            "accountType": "UNIFIED", "category": "linear",
            "startTime": start_ms, "endTime": end_ms, "limit": 100,
        })

    def fetch_open_positions(self) -> list[dict]:
        """Live snapshot of open linear (USDT-settled) positions (size > 0)."""
        rows: list[dict] = []
        cursor: Optional[str] = None
        for _ in range(50):
            params = {"category": "linear", "settleCoin": "USDT", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = self._signed_get("/v5/position/list", params)
            result = data.get("result") or {}
            for r in result.get("list") or []:
                if float(r.get("size") or 0) > 0:
                    rows.append(r)
            cursor = result.get("nextPageCursor") or ""
            if not cursor:
                break
        return rows

    # --- trading (cockpit close) --------------------------------------------
    def _signed_post(self, path: str, params: dict) -> dict:
        """V5 signed POST. The signature covers the RAW JSON body, so the exact
        string signed is the exact string sent. Single attempt — an order POST
        must never blind-retry (a 429'd close is just clicked again)."""
        body = json.dumps(params, separators=(",", ":"))
        ts = str(int(time.time() * 1000))
        sig = _sign(self.api_secret, ts, self.api_key, RECV_WINDOW, body)
        headers = {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-TIMESTAMP": ts,
            "X-BAPI-RECV-WINDOW": RECV_WINDOW,
            "X-BAPI-SIGN": sig,
            "Content-Type": "application/json",
        }
        resp = self._client.post(f"{self.base_url}{path}", headers=headers, content=body)
        resp.raise_for_status()
        data = resp.json()
        code = data.get("retCode")
        if code != 0:
            raise BybitError(f"{path} retCode={code} {data.get('retMsg')}", ret_code=code)
        return data

    def close_position(self, symbol: str, qty: str, close_side: str) -> dict:
        """Reduce-only market order closing (part of) a position.
        close_side is the ORDER side: 'Sell' closes a LONG, 'Buy' a SHORT.
        positionIdx 0 = one-way mode; hedge-mode accounts get Bybit's own
        rejection, surfaced upstream as venue_rejected."""
        data = self._signed_post("/v5/order/create", {
            "category": "linear", "symbol": symbol, "side": close_side,
            "orderType": "Market", "qty": qty, "reduceOnly": True,
            "positionIdx": 0,
        })
        return {"order_id": ((data.get("result") or {}).get("orderId")) or ""}

    def fetch_lot_rules(self, symbol: str) -> dict:
        """qtyStep/minOrderQty from instruments-info (public endpoint; the
        signed GET's retry/backoff is reused, auth headers are ignored).
        Raises when the instrument is unknown — a close must never proceed
        on guessed rounding rules."""
        data = self._signed_get("/v5/market/instruments-info",
                                {"category": "linear", "symbol": symbol})
        rows = (data.get("result") or {}).get("list") or []
        f = (rows[0].get("lotSizeFilter") or {}) if rows else {}
        step, minq = f.get("qtyStep"), f.get("minOrderQty")
        if not step or minq in (None, ""):
            raise BybitError(f"no lot rules for {symbol}")
        return {"qty_step": step, "min_qty": minq}
