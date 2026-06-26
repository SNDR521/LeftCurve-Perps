"""Alert evaluation. Crypto: near-live crossing state machine fed by keyless
Bybit tickers."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.workflow.models import Alert, WatchlistItem

log = logging.getLogger(__name__)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fetch_crypto_prices(symbols: list[str]) -> dict:
    """{symbol: last_price} via the public tickers endpoint (no credentials)."""
    from app.perps.connectors.bybit import BybitClient
    client = BybitClient("", "")
    try:
        tickers = client.fetch_tickers(symbols)
        return {s: t["mark_price"] for s, t in tickers.items() if t.get("mark_price")}
    finally:
        try:
            client._client.close()
        except Exception:  # noqa: BLE001
            pass


def check_crypto_levels(db, user_id, prices=None) -> list[Alert]:
    """Crossing = sign change of (price - level) between the stored last_price
    and the fresh price. First observation only records state. An UNSEEN alert
    for the same (symbol, level) suppresses re-alerting until acknowledged."""
    items = (db.query(WatchlistItem)
             .filter(WatchlistItem.user_id == user_id,
                     WatchlistItem.market == "CRYPTO").all())
    if not items:
        return []
    if prices is None:
        prices = fetch_crypto_prices([i.symbol for i in items])
    created: list[Alert] = []
    for item in items:
        price = prices.get(item.symbol)
        if price is None:
            continue
        prev = item.last_price
        item.last_price = price
        item.last_checked = _now()
        if prev is None:
            continue
        for lvl in item.levels or []:
            level = float(lvl.get("price") or 0)
            if level <= 0:
                continue
            before, after = prev - level, price - level
            if before == 0 or after == 0 or (before < 0) == (after < 0):
                continue  # no sign change → no cross
            unseen = (db.query(Alert)
                      .filter(Alert.user_id == user_id,
                              Alert.kind == "LEVEL_CROSS",
                              Alert.symbol == item.symbol,
                              Alert.seen.is_(False))
                      .all())
            if any((a.payload or {}).get("level") == level for a in unseen):
                continue  # cooldown until acknowledged
            alert = Alert(user_id=user_id, kind="LEVEL_CROSS", symbol=item.symbol,
                          payload={"symbol": item.symbol, "market": "CRYPTO",
                                   "level": level, "label": lvl.get("label"),
                                   "price": price,
                                   "direction": "up" if after > 0 else "down",
                                   "source": "live"},
                          triggered_at=_now())
            db.add(alert)
            created.append(alert)
    db.commit()
    return created
