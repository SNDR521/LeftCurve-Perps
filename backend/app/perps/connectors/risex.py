"""Keyless, address-only RiseX REST client (read-only).

RiseX is an on-chain perps DEX on RISE Chain. Read endpoints take an EVM
account address; no API key. Returns Bybit-compatible position/wallet/ticker
shapes so the perps build_cockpit is reused unchanged (mirrors hyperliquid.py).
Docs: https://developer.rise.trade/reference/
"""
from __future__ import annotations

import logging
import time
from typing import Iterator

import httpx

log = logging.getLogger(__name__)

MAX_PAGES = 1000  # backstop against a server that never sets has_next_page=False


class RiseXError(Exception):
    pass


class RiseXClient:
    def __init__(self, address: str, base_url: str, timeout: float = 30.0,
                 min_interval_s: float = 0.1):
        self.address = address
        self.base_url = base_url.rstrip("/")
        self.min_interval_s = min_interval_s
        self._last_request = 0.0
        self._client = httpx.Client(timeout=timeout)
        self._markets: dict[int, str] | None = None

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict | None = None):
        if self.min_interval_s:
            wait = self.min_interval_s - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
        for attempt in range(5):
            self._last_request = time.monotonic()
            resp = self._client.get(f"{self.base_url}{path}", params=params)
            if resp.status_code == 429:
                log.warning("risex %s HTTP 429 (attempt %d) — backing off %ds",
                            path, attempt, 2 ** attempt)
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            # Every RiseX response is wrapped: {"data": <payload>, "request_id": ...}.
            # Unwrap to the inner payload so callers see the real fields. (Defensive:
            # if a response ever lacks the envelope, return it as-is.)
            body = resp.json()
            if isinstance(body, dict) and "data" in body and "request_id" in body:
                return body["data"]
            return body
        raise RiseXError(f"{path} rate-limited after retries")

    # --- pagination helpers ---
    def _iter_pages(self, path: str, params: dict, items_key: str) -> Iterator[dict]:
        """Page a list endpoint. After _get unwraps the envelope, the paginated
        payload carries the item list under its own key (realized-pnl -> "data",
        trade-history -> "trades") plus a top-level "has_next_page"."""
        page = 1
        for _ in range(MAX_PAGES):
            body = self._get(path, {**params, "page": page, "limit": 1000}) or {}
            for item in body.get(items_key) or []:
                yield item
            if not body.get("has_next_page"):
                return
            page += 1
        log.warning("risex %s: hit MAX_PAGES", path)

    def iter_realized_pnl(self, start_ns: int, end_ns: int) -> Iterator[dict]:
        yield from self._iter_pages("/v1/portfolio/realized-pnl",
                                    {"account": self.address, "from": start_ns, "to": end_ns},
                                    items_key="data")

    def iter_trade_history(self, start_ns: int, end_ns: int) -> Iterator[dict]:
        yield from self._iter_pages("/v1/trade-history",
                                    {"account": self.address,
                                     "start_time": start_ns, "end_time": end_ns},
                                    items_key="trades")

    # --- markets (id -> name) ---
    def fetch_markets(self) -> dict[int, str]:
        """market_id (int) -> display name. The unwrapped /v1/markets payload is
        {"markets": [{"market_id": "1", "config": {"name": "BTC/USDC"}, "display_name":
        "BTC/USDC", ...}]}; market_id is a string. Falls back to the portfolio
        snapshot's id->name pairs for open markets, and to f"MKT{id}" otherwise
        (never crash)."""
        if self._markets is not None:
            return self._markets
        out: dict[int, str] = {}
        try:
            body = self._get("/v1/markets") or {}
            for m in (body.get("markets") or []):
                mid = m.get("market_id") if m.get("market_id") is not None else m.get("id")
                name = ((m.get("config") or {}).get("name")
                        or m.get("display_name") or m.get("market_name") or m.get("name"))
                if mid is not None and name:
                    out[int(mid)] = name
        except Exception:  # noqa: BLE001 — markets endpoint optional; fall back below
            log.warning("risex markets fetch failed; falling back to portfolio names")
        # supplement with any names from the live portfolio snapshot (failure-
        # isolated: a market-data-only client has no/empty address, so the
        # portfolio call may 4xx — the markets list above already covers names).
        try:
            for p in (self.fetch_portfolio().get("positions") or []):
                if p.get("market_id") is not None and p.get("market_name"):
                    out[int(p["market_id"])] = p["market_name"]
        except Exception:  # noqa: BLE001
            log.warning("risex portfolio supplement for markets failed; using markets list only")
        self._markets = out
        return out

    def market_name(self, market_id) -> str:
        return self.fetch_markets().get(int(market_id), f"MKT{market_id}")

    def candle_snapshot(self, market_id, from_ms: int, to_ms: int) -> list[dict]:
        """Ascending 1-minute OHLCV for a market from the trading-view-data
        endpoint. RiseX serves only 1m bars (resolution params are ignored), so
        callers aggregate to coarser intervals. The unwrapped payload is
        {"data": [{time(ns str), open, high, low, close, volume(strings)}]}.
        Returns lightweight-charts rows [{time(seconds), open, high, low, close,
        volume}]. time params are nanoseconds."""
        body = self._get(f"/v1/markets/id/{int(market_id)}/trading-view-data",
                         {"from": int(from_ms) * 1_000_000, "to": int(to_ms) * 1_000_000}) or {}
        rows = body.get("data") or []
        out = [{
            "time": int(r["time"]) // 1_000_000_000,
            "open": float(r.get("open") or 0.0), "high": float(r.get("high") or 0.0),
            "low": float(r.get("low") or 0.0), "close": float(r.get("close") or 0.0),
            "volume": float(r.get("volume") or 0.0),
        } for r in rows if r.get("time") is not None]
        out.sort(key=lambda b: b["time"])
        return out

    # --- portfolio / cockpit shapes ---
    def fetch_portfolio(self) -> dict:
        return self._get("/v1/portfolio/details", {"account": self.address}) or {}

    def _stop_loss_by_market(self) -> dict[int, float]:
        """market_id -> active stop-loss trigger price, from the account's TP/SL
        orders (RiseX keeps stops as separate orders at /v1/orders/tpsl, not on the
        position — like Hyperliquid). Take-profit orders are excluded.

        /v1/orders/tpsl returns the FULL history — changing a stop cancels the old
        order and accepts a new one, so cancelled/triggered orders linger. Only an
        order with status TPSL_ORDER_STATUS_ACCEPTED is live; we keep the latest
        ACCEPTED stop per market (by created_at) so the cockpit tracks edits instead
        of locking on a stale value. Failure-isolated: returns {} on any error."""
        try:
            body = self._get("/v1/orders/tpsl", {"account": self.address}) or {}
        except Exception:  # noqa: BLE001
            log.warning("risex tpsl-orders fetch failed; no exchange stops")
            return {}
        best: dict[int, tuple[int, float]] = {}  # market_id -> (created_at, stop_price)
        for o in (body.get("orders") or []):
            if str(o.get("stop_type", "")).upper() != "STOP_LOSS":
                continue  # exclude take-profit orders
            if o.get("status") != "TPSL_ORDER_STATUS_ACCEPTED":
                continue  # skip cancelled / triggered / non-live orders
            mid, px = o.get("market_id"), o.get("stop_price")
            if mid is None or px in (None, ""):
                continue
            try:
                mid_i, px_f, ts = int(mid), float(px), int(o.get("created_at") or 0)
            except (TypeError, ValueError):
                continue
            if mid_i not in best or ts >= best[mid_i][0]:
                best[mid_i] = (ts, px_f)
        return {m: tp[1] for m, tp in best.items()}

    def fetch_open_positions(self) -> list[dict]:
        stops = self._stop_loss_by_market()
        out: list[dict] = []
        for p in (self.fetch_portfolio().get("positions") or []):
            # `size` is SIGNED (negative = short); the `side` field is unreliable
            # (observed 0 on a short), so direction comes from the sign of size.
            size_signed = float(p.get("size") or 0.0)
            if size_signed == 0.0:
                continue
            mid = p.get("market_id")
            out.append({
                "symbol": p.get("market_name") or self.market_name(mid),
                "side": "Buy" if size_signed > 0 else "Sell",
                "size": abs(size_signed),
                "avgPrice": float(p.get("avg_entry_price") or 0.0),
                "unrealisedPnl": float(p.get("unrealized_pnl") or 0.0),
                "liqPrice": float(p["liquidation_price"]) if p.get("liquidation_price") else None,
                "leverage": float(p["leverage"]) if p.get("leverage") else None,
                "stopLoss": stops.get(int(mid)) if mid is not None else None,
                "tradeMode": 1 if p.get("margin_mode") in (1, "1") else 0,
            })
        return out

    def fetch_wallet_balance(self) -> dict:
        s = self.fetch_portfolio().get("summary") or {}
        return {
            "equity": float(s.get("total_account_value") or 0.0),
            "balance": float(s.get("usdc_balance") or 0.0),
            "available": float(s.get("free_collateral") or 0.0),
        }

    def fetch_tickers(self, symbols: list[str] | None = None) -> dict:
        """Marks from the portfolio snapshot's per-position mark_price. Funding is
        omitted (0.0) in v1 — RiseX returns only last_funding_payment, not a
        forward rate; the cockpit shows funding=0 rather than a wrong projection."""
        wanted = set(symbols) if symbols else None
        next_funding = ((int(time.time() * 1000) // (8 * 3600_000)) + 1) * (8 * 3600_000)
        out: dict = {}
        for p in (self.fetch_portfolio().get("positions") or []):
            sym = p.get("market_name") or self.market_name(p.get("market_id"))
            if wanted is not None and sym not in wanted:
                continue
            out[sym] = {"mark_price": float(p.get("mark_price") or 0.0),
                        "funding_rate": 0.0, "next_funding_time": next_funding}
        return out
