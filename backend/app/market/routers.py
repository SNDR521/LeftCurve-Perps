import logging
from fastapi import APIRouter, Depends, Query
import httpx
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from app.config import get_settings
from app.core.deps import get_current_user
from app.core.models import User

log = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["market"])

FINNHUB_BASE = "https://finnhub.io/api/v1"

TICKER_BAR_SYMBOLS = [
    # Futures/indices a CFD trader actually tracks (all served via Yahoo);
    # crypto is NOT here — the banner streams it live from Bybit's WebSocket.
    "ES=F", "NQ=F", "RTY=F", "^GDAXI", "^VIX", "GC=F", "CL=F",
]


async def _yahoo_quote(client, symbol: str) -> dict:
    """All quote symbols are fetched from Yahoo's v8 chart meta (free, intraday,
    keyless — the same source the prop charts use). Works for equities/ETFs,
    indices (^VIX, ^GDAXI), futures (ES=F, NQ=F) and crypto (BTC-USD)."""
    r = await client.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        params={"interval": "1d", "range": "2d"},
        headers={"User-Agent": "Mozilla/5.0"},
    )
    meta = r.json()["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = (price - prev) if (price is not None and prev) else None
    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "change_pct": (change / prev * 100) if (change is not None and prev) else None,
        "high": meta.get("regularMarketDayHigh"),
        "low": meta.get("regularMarketDayLow"),
        "open": None,
        "prev_close": prev,
    }


@router.get("/quotes")
async def get_quotes(symbols: str = Query(default=None), user: User = Depends(get_current_user)):
    symbol_list = [s.strip() for s in (symbols or ",".join(TICKER_BAR_SYMBOLS)).split(",") if s.strip()]
    async with httpx.AsyncClient(timeout=10) as client:
        results = []
        for symbol in symbol_list:
            try:
                results.append(await _yahoo_quote(client, symbol))
            except Exception as e:  # noqa: BLE001 — one bad symbol must not fail the batch
                log.warning("quote fetch failed for %s: %s", symbol, e)
                results.append({
                    "symbol": symbol, "price": None, "change": None,
                    "change_pct": None, "high": None, "low": None,
                    "open": None, "prev_close": None,
                })
    return results


@router.get("/news/equity")
async def get_equity_news(limit: int = Query(default=40), user: User = Depends(get_current_user)):
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{FINNHUB_BASE}/news",
            params={"category": "general", "token": settings.finnhub_api_key},
        )
        items = r.json() if r.status_code == 200 else []

    return [
        {
            "id": str(item.get("id", "")),
            "headline": item.get("headline", ""),
            "summary": item.get("summary", ""),
            "source": item.get("source", ""),
            "url": item.get("url", ""),
            "image": item.get("image", ""),
            "datetime": item.get("datetime"),
            "related": item.get("related", ""),
        }
        for item in items[:limit]
    ]


@router.get("/news/crypto")
async def get_crypto_news(limit: int = Query(default=40), user: User = Depends(get_current_user)):
    settings = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            f"{FINNHUB_BASE}/news",
            params={"category": "crypto", "token": settings.finnhub_api_key},
        )
        items = r.json() if r.status_code == 200 else []

    return [
        {
            "id": str(item.get("id", "")),
            "headline": item.get("headline", ""),
            "summary": item.get("summary", ""),
            "source": item.get("source", ""),
            "url": item.get("url", ""),
            "image": item.get("image", ""),
            "datetime": item.get("datetime"),
            "related": item.get("related", ""),
        }
        for item in items[:limit]
    ]


FJ_RSS_URL = "https://www.financialjuice.com/feed.ashx?xy=rss"
FJ_HEADERS = {"User-Agent": "Mozilla/5.0"}


@router.get("/squawk")
async def get_squawk(limit: int = Query(default=50), user: User = Depends(get_current_user)):
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(FJ_RSS_URL, headers=FJ_HEADERS)

    root = ET.fromstring(r.text)
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []

    results = []
    for item in items[:limit]:
        raw_title = (item.findtext("title") or "").strip()
        headline = raw_title.removeprefix("FinancialJuice: ").strip()
        pub_date = item.findtext("pubDate") or ""
        guid = item.findtext("guid") or ""
        url = item.findtext("link") or ""

        ts = None
        try:
            ts = parsedate_to_datetime(pub_date).isoformat()
        except Exception:
            ts = pub_date

        results.append({"id": guid, "headline": headline, "url": url, "datetime": ts})

    return results
