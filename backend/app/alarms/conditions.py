"""Pure alarm condition evaluation. No DB, no IO. Edge-triggered: an alarm
fires on the transition into the true state, never on first observation
(prev_price is None) and never while already in-state."""
from __future__ import annotations


def _crossed(prev, value, price, direction):
    """direction: 'up' | 'down' | 'either'. True iff (prev, price) straddles value."""
    before, after = prev - value, price - value
    if before == 0 or after == 0:
        before = before or (-1 if after > 0 else 1)
    crossed = (before < 0) != (after < 0)
    if not crossed:
        return False
    if direction == "either":
        return True
    if direction == "up":
        return after > 0
    return after < 0


def _upnl(price, ctx):
    sign = 1.0 if ctx.get("direction") == "LONG" else -1.0
    return (price - ctx["entry"]) * ctx["qty"] * sign


def _near_stop_dist_ok(price, alarm, ctx):
    stop = ctx.get("stop")
    if not stop:
        return None
    unit = (alarm.params or {}).get("unit", "PCT")
    thr = (alarm.value / 100.0 * price) if unit == "PCT" else alarm.value
    return abs(price - stop) <= thr


def _liq_dist_ok(price, alarm, ctx):
    liq = ctx.get("liq")
    if not liq or price <= 0:
        return None
    return abs(price - liq) / price * 100 <= alarm.value


def should_fire(alarm, prev_price, price, ctx=None) -> bool:
    if prev_price is None:
        return False
    c = alarm.condition
    v = alarm.value
    if c == "CROSS":
        return _crossed(prev_price, v, price, "either")
    if c == "CROSS_UP":
        return _crossed(prev_price, v, price, "up")
    if c == "CROSS_DOWN":
        return _crossed(prev_price, v, price, "down")
    if c == "GTE":
        return prev_price < v <= price
    if c == "LTE":
        return prev_price > v >= price
    if c == "PCT_MOVE":
        ref = float((alarm.params or {}).get("ref_price") or 0)
        if ref <= 0:
            return False
        prev_pct = abs(prev_price - ref) / ref * 100
        cur_pct = abs(price - ref) / ref * 100
        return prev_pct < v <= cur_pct
    if ctx is None:
        return False
    if c == "NEAR_STOP":
        return _near_stop_dist_ok(prev_price, alarm, ctx) is False and _near_stop_dist_ok(price, alarm, ctx) is True
    if c == "LIQ_DIST":
        return _liq_dist_ok(prev_price, alarm, ctx) is False and _liq_dist_ok(price, alarm, ctx) is True
    if c == "UPNL":
        unit = (alarm.params or {}).get("unit", "USD")
        denom = ctx.get("risk_usd") if unit == "R" else 1.0
        if not denom:
            return False
        prev_m = _upnl(prev_price, ctx) / denom
        cur_m = _upnl(price, ctx) / denom
        if alarm.value >= 0:
            return prev_m < alarm.value <= cur_m
        return prev_m > alarm.value >= cur_m
    return False
