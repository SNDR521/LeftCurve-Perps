"""Venue dispatch for trade EXECUTION — the only module that places orders.
Mirrors venue_sync's dispatcher shape. Phase 1: Bybit reduce-only market
closes. Safety: qty is resolved against the LIVE exchange position and
rounded DOWN to the venue lot step; reduce-only means a close can never flip
or grow a position."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN

import httpx
from sqlalchemy.orm import Session

from app.perps.connectors.bybit import BybitError
from app.perps.models import ExchangeAccount, Venue
from app.perps.services import venue_sync

SUPPORTED_TRADING_VENUES = {Venue.BYBIT}


class CloseError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def can_close(account: ExchangeAccount) -> bool:
    """Venue supported AND trading-capable credentials stored. For Bybit the
    blob always carries key+secret — actual trade permission is only provable
    by the exchange, so permission failures are mapped at close time."""
    return (account.venue in SUPPORTED_TRADING_VENUES
            and bool(account.encrypted_credentials))


def resolve_close_qty(live_size: float, *, fraction: float | None = None,
                      qty: float | None = None,
                      qty_step: str = "0.001", min_qty: str = "0") -> str:
    if (fraction is None) == (qty is None):
        raise CloseError("bad_request", "exactly one of fraction/qty is required")
    size = Decimal(str(live_size))
    step = Decimal(qty_step)
    minq = Decimal(min_qty)
    if fraction is not None:
        if not 0 < fraction <= 1:
            raise CloseError("bad_request", "fraction must be in (0, 1]")
        if fraction == 1:
            # full close sends the venue's own (already step-aligned) size verbatim
            target = size
        else:
            target = size * Decimal(str(fraction))
            target = (target / step).to_integral_value(rounding=ROUND_DOWN) * step
    else:
        target = Decimal(str(qty))
        if target > size:
            raise CloseError("qty_exceeds_position", f"position size is {size}")
        target = (target / step).to_integral_value(rounding=ROUND_DOWN) * step
    if target <= 0 or target < minq:
        raise CloseError("qty_too_small",
                         f"quantity below venue minimum {minq} (step {qty_step})")
    return format(target.normalize(), "f")


def close_position(db: Session, account: ExchangeAccount, symbol: str, *,
                   fraction: float | None = None, qty: float | None = None) -> dict:
    if not can_close(account):
        raise CloseError("unsupported",
                         f"closing is not supported for {account.venue.value} accounts yet")
    client = venue_sync.client_for(account)
    try:
        try:
            pos = next((p for p in client.fetch_open_positions()
                        if p.get("symbol") == symbol and float(p.get("size") or 0) > 0), None)
            if pos is None:
                raise CloseError("no_position", f"no open {symbol} position on the exchange")
            rules = client.fetch_lot_rules(symbol)
            qty_str = resolve_close_qty(float(pos["size"]), fraction=fraction, qty=qty,
                                        qty_step=rules["qty_step"], min_qty=rules["min_qty"])
            # order side is the OPPOSITE of the position side
            close_side = "Sell" if str(pos.get("side", "")).upper().startswith("B") else "Buy"
            res = client.close_position(symbol, qty_str, close_side)
        except BybitError as e:
            if getattr(e, "ret_code", None) == 10005:
                raise CloseError("permission",
                                 "this API key has no trade permission — create a "
                                 "trade-enabled key (no withdrawal) and update the account")
            raise CloseError("venue_rejected", str(e))
        except httpx.HTTPError as e:
            raise CloseError("venue_rejected",
                             f"venue unreachable or request failed ({type(e).__name__}) — "
                             "check the exchange before retrying")
        return {"status": "accepted", "order_id": res.get("order_id", ""),
                "requested_qty": qty_str, "venue": account.venue.value}
    finally:
        try:
            client._client.close()
        except Exception:  # noqa: BLE001
            pass
