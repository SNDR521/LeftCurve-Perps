"""Background asyncio loop: subscribe to Bybit public tickers for every symbol
with an active CRYPTO alarm and feed live prices into the tested evaluator.
Never crashes the app; reconnects with backoff. The set of subscribed symbols
is reconciled every RECONCILE_SECONDS from the DB."""
import asyncio
import json
import logging

from app.database import SessionLocal
from app.alarms.models import Alarm
from app.alarms.engine.evaluator import evaluate_ticks

log = logging.getLogger(__name__)
WS_URL = "wss://stream.bybit.com/v5/public/linear"
RECONCILE_SECONDS = 10
_task = None
_stop = False


def _active_symbols() -> list[str]:
    db = SessionLocal()
    try:
        rows = (db.query(Alarm.symbol)
                .filter(Alarm.status == "ACTIVE", Alarm.enabled.is_(True),
                        Alarm.market == "CRYPTO", Alarm.symbol.isnot(None))
                .distinct().all())
        # Bybit linear perps are USDT-quoted; the Hyperliquid loop serves bare-coin
        # symbols (BTC, HYPE, kPEPE), so exclude them from the Bybit subscription.
        return sorted({r[0] for r in rows if str(r[0]).endswith("USDT")})
    finally:
        db.close()


def _flush(prices: dict) -> list:
    if not prices:
        return []
    from app.alarms.telegram import notify
    from app.alarms.engine import positions
    db = SessionLocal()
    try:
        fired = evaluate_ticks(db, dict(prices), position_ctx=positions.get_position_ctx())
        return notify.collect_targets(db, fired)
    except Exception:  # noqa: BLE001
        log.exception("alarm evaluate_ticks failed")
        return []
    finally:
        db.close()


async def _run():
    import websockets
    global _stop
    backoff = 1
    while not _stop:
        symbols = _active_symbols()
        if not symbols:
            await asyncio.sleep(RECONCILE_SECONDS)
            continue
        try:
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                await ws.send(json.dumps({"op": "subscribe",
                                          "args": [f"tickers.{s}" for s in symbols]}))
                backoff = 1
                subscribed = set(symbols)
                last_reconcile = asyncio.get_running_loop().time()
                prices: dict = {}
                while not _stop:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=RECONCILE_SECONDS)
                        msg = json.loads(raw)
                        topic = msg.get("topic", "")
                        if topic.startswith("tickers."):
                            data = msg.get("data") or {}
                            lp = data.get("lastPrice")
                            if lp is not None:
                                prices[topic.split(".", 1)[1]] = float(lp)
                    except asyncio.TimeoutError:
                        pass
                    now = asyncio.get_running_loop().time()
                    if now - last_reconcile >= RECONCILE_SECONDS:
                        targets = _flush(prices); prices = {}
                        if targets:
                            from app.alarms.telegram import notify
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(None, notify.send_all, targets)
                        want = set(_active_symbols())
                        if want != subscribed:
                            break
                        last_reconcile = now
        except Exception:  # noqa: BLE001
            log.exception("alarm WS loop error; backing off %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def start():
    global _task, _stop
    _stop = False
    loop = asyncio.get_running_loop()
    _task = loop.create_task(_run())
    log.info("alarm realtime WS loop started")


def stop():
    global _stop, _task
    _stop = True
    if _task is not None and not _task.done():
        _task.cancel()
