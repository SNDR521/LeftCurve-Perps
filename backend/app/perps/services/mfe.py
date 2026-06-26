"""MFE/MAE (max favorable/adverse excursion) for closed positions with
verified (EXACT) entry times. Price excursions come from public Bybit klines;
ESTIMATED positions are skipped (their entry time is unknown).

Excursions are bar-based: the opening and closing bars may include
pre-entry/post-exit price action at the chosen interval resolution."""
from __future__ import annotations

import logging
from datetime import timezone

import httpx
from sqlalchemy.orm import Session

from app.perps.models import Direction, OpenedAtSource, Position, PositionStatus, Venue
from app.perps.services.candles import choose_interval, fetch_klines, fetch_hl_klines

log = logging.getLogger(__name__)


def _ms(dt) -> int:
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def compute_mfe_mae(db: Session, account, fetch=None) -> int:
    """Fill in mfe/mae for this account's eligible positions. Returns count computed.

    `fetch` resolves at call time (not as a bound default) so tests can
    monkeypatch module-level `fetch_klines`. One shared HTTP client is used
    across the whole batch (first prod run touches ~700 positions — per-call
    clients would mean ~700 TLS handshakes).
    """
    # Candle source follows the account's venue (both return the same OHLCV shape).
    do_fetch = fetch or (fetch_hl_klines if account.venue == Venue.HYPERLIQUID else fetch_klines)
    q = (db.query(Position)
         .filter(Position.exchange_account_id == account.id,
                 Position.status == PositionStatus.CLOSED,
                 Position.opened_at_source == OpenedAtSource.EXACT,
                 Position.mfe_usd.is_(None),
                 Position.closed_at.isnot(None))
         .order_by(Position.closed_at.desc()))  # newest first: a partial batch leaves only old rows uncomputed
    done = 0
    with httpx.Client(timeout=15.0) as shared:
        for p in q.all():
            try:
                if not p.avg_entry or not p.quantity:
                    # zero/null entry or size would produce garbage excursions
                    log.warning("mfe/mae skipped for position %s %s: avg_entry=%s quantity=%s",
                                p.id, p.symbol, p.avg_entry, p.quantity)
                    continue
                duration = max((p.closed_at - p.opened_at).total_seconds(), 60)
                interval = choose_interval(duration)
                candles = do_fetch(p.symbol, interval, _ms(p.opened_at), _ms(p.closed_at),
                                   client=shared)
                if not candles:
                    log.debug("no klines for position %s %s (delisted?), skipping", p.id, p.symbol)
                    continue
                hi = max(c["high"] for c in candles)
                lo = min(c["low"] for c in candles)
                entry = p.avg_entry
                if p.direction == Direction.LONG:
                    mfe, mae = hi - entry, entry - lo
                else:
                    mfe, mae = entry - lo, hi - entry
                p.mfe_price = max(mfe, 0.0)
                p.mae_price = max(mae, 0.0)
                p.mfe_usd = p.mfe_price * p.quantity
                p.mae_usd = p.mae_price * p.quantity
                done += 1
            except Exception:
                log.exception("mfe/mae failed for position %s %s", p.id, p.symbol)
    db.commit()
    return done
