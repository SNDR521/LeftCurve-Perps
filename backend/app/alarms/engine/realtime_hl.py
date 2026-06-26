"""Background asyncio loop: subscribe to Hyperliquid's public allMids stream and
feed HL-position marks into the shared alarm evaluator on a short flush cadence.
Mirrors engine/realtime.py (the Bybit loop). Never crashes the app; reconnects
with backoff; sends an application-level ping so HL doesn't drop the idle socket.
The position context (entry/stop/liq/risk) is refreshed separately by
engine/positions.py every 15s and read here via get_position_ctx()."""
import asyncio
import json
import logging

from app.database import SessionLocal

log = logging.getLogger(__name__)

WS_URL = "wss://api.hyperliquid.xyz/ws"
FLUSH_SECONDS = 2      # how often we evaluate HL position alarms against the latest mids
PING_SECONDS = 30      # HL drops idle sockets (~60s); keep it alive
_task = None
_stop = False


def _parse_mids(msg: dict) -> dict:
    """Extract {coin: float price} from an allMids frame; {} for any other frame."""
    if msg.get("channel") != "allMids":
        return {}
    raw = (msg.get("data") or {}).get("mids") or {}
    out = {}
    for coin, px in raw.items():
        try:
            out[coin] = float(px)
        except (TypeError, ValueError):
            continue
    return out


def _scope_prices(mids: dict, ctx: dict) -> dict:
    """Keep only mids for symbols that are someone's open position (the ctx keys).
    Bybit's USDT symbols are absent from allMids, so this is naturally HL-only."""
    wanted = {sym for (_uid, sym) in ctx}
    return {s: mids[s] for s in wanted if s in mids}


def _flush(prices: dict, ctx: dict | None = None) -> list:
    if not prices:
        return []
    from app.alarms.engine.evaluator import evaluate_ticks
    from app.alarms.engine import positions
    from app.alarms.telegram import notify
    # Use the same ctx snapshot that scoped the prices (avoids a TOCTOU gap where
    # the 15s refresh swaps _POSITION_CTX between scoping and evaluating).
    if ctx is None:
        ctx = positions.get_position_ctx()
    db = SessionLocal()
    try:
        fired = evaluate_ticks(db, dict(prices), position_ctx=ctx)
        return notify.collect_targets(db, fired)
    except Exception:  # noqa: BLE001
        log.exception("HL alarm evaluate_ticks failed")
        return []
    finally:
        db.close()


async def _run():
    import websockets
    from app.alarms.engine import positions
    from app.alarms.telegram import notify
    global _stop
    backoff = 1
    while not _stop:
        try:
            # ping_interval keeps the TCP layer alive (WS protocol PING frames);
            # HL also needs an application-level JSON ping — PING_SECONDS handles that.
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                await ws.send(json.dumps({"method": "subscribe",
                                          "subscription": {"type": "allMids"}}))
                backoff = 1
                mids: dict = {}
                loop = asyncio.get_running_loop()
                last_flush = loop.time()
                last_ping = loop.time()
                while not _stop:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        mids.update(_parse_mids(json.loads(raw)))
                    except asyncio.TimeoutError:
                        pass
                    now = loop.time()
                    if now - last_ping >= PING_SECONDS:
                        await ws.send(json.dumps({"method": "ping"}))
                        last_ping = now
                    if now - last_flush >= FLUSH_SECONDS:
                        ctx = positions.get_position_ctx()
                        prices = _scope_prices(mids, ctx)
                        targets = _flush(prices, ctx)
                        if targets:
                            await loop.run_in_executor(None, notify.send_all, targets)
                        last_flush = now
        except Exception:  # noqa: BLE001
            log.exception("HL alarm WS loop error; backing off %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def start():
    global _task, _stop
    _stop = False
    loop = asyncio.get_running_loop()
    _task = loop.create_task(_run())
    log.info("HL alarm realtime WS loop started")


def stop():
    global _stop, _task
    _stop = True
    if _task is not None and not _task.done():
        _task.cancel()
