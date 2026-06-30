from app.perps.models import Venue
from app.config import get_settings
from app.perps.connectors.risex import RiseXClient


def test_risex_venue_value():
    assert Venue.RISEX.value == "RISEX"


def test_risex_api_base_default():
    assert get_settings().risex_api_base.startswith("https://")


def _client(monkeypatch, responses):
    """responses: dict {path: payload}. Patches _get to return canned payloads."""
    c = RiseXClient("0xabc", "https://api.test")
    def fake_get(path, params=None):
        return responses[path]
    monkeypatch.setattr(c, "_get", fake_get)
    return c


def test_fetch_open_positions_shape(monkeypatch):
    portfolio = {
        "summary": {"total_account_value": "10000.5", "usdc_balance": "9000",
                    "free_collateral": "8000"},
        "positions": [
            {"market_id": 1, "market_name": "BTC-USD", "size": "2", "side": 0,
             "avg_entry_price": "60000", "mark_price": "61000",
             "unrealized_pnl": "2000", "liquidation_price": "50000",
             "leverage": "5", "margin_mode": 0, "last_funding_payment": "-1.5"},
            {"market_id": 2, "market_name": "ETH-USD", "size": "-3", "side": 1,
             "avg_entry_price": "3000", "mark_price": "2900",
             "unrealized_pnl": "300", "liquidation_price": "3500",
             "leverage": "10", "margin_mode": 1, "last_funding_payment": "0.2"},
        ],
    }
    c = _client(monkeypatch, {"/v1/portfolio/details": portfolio})
    rows = c.fetch_open_positions()
    assert rows[0] == {"symbol": "BTC-USD", "side": "Buy", "size": 2.0,
                       "avgPrice": 60000.0, "unrealisedPnl": 2000.0,
                       "liqPrice": 50000.0, "leverage": 5.0, "stopLoss": None,
                       "tradeMode": 0}
    assert rows[1]["side"] == "Sell" and rows[1]["size"] == 3.0 and rows[1]["tradeMode"] == 1


def test_fetch_wallet_balance(monkeypatch):
    portfolio = {"summary": {"total_account_value": "10000.5", "usdc_balance": "9000",
                             "free_collateral": "8000"}, "positions": []}
    c = _client(monkeypatch, {"/v1/portfolio/details": portfolio})
    assert c.fetch_wallet_balance() == {"equity": 10000.5, "balance": 9000.0, "available": 8000.0}


def test_iter_realized_pnl_paginates(monkeypatch):
    pages = {
        1: {"data": [{"timestamp": 1, "market_id": 1, "side": "BUY"}], "has_next_page": True},
        2: {"data": [{"timestamp": 2, "market_id": 1, "side": "SELL"}], "has_next_page": False},
    }
    c = RiseXClient("0xabc", "https://api.test")
    calls = []
    def fake_get(path, params=None):
        calls.append(params["page"])
        return pages[params["page"]]
    monkeypatch.setattr(c, "_get", fake_get)
    out = list(c.iter_realized_pnl(0, 10**9))
    assert [e["timestamp"] for e in out] == [1, 2]
    assert calls == [1, 2]  # stopped after has_next_page=False


# --- Real RiseX response-shape regression tests (the live API wraps every
# response in {"data": <payload>, "request_id": ...}; these mock the HTTP layer
# so they exercise the real _get unwrap, which the _get-stubbing tests above
# could not catch). ---

class _FakeResp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200
    def raise_for_status(self):
        pass
    def json(self):
        return self._p


class _FakeHttp:
    def __init__(self, by_path):
        self.by_path = by_path
    def get(self, url, params=None):
        for suffix, payload in self.by_path.items():
            if url.endswith(suffix):
                return _FakeResp(payload)
        return _FakeResp({"data": {}, "request_id": "x"})
    def close(self):
        pass


def _live_client(by_path):
    c = RiseXClient("0xabc", "https://api.test", min_interval_s=0)
    c._client = _FakeHttp(by_path)
    return c


def test_get_unwraps_data_envelope():
    c = _live_client({"/whatever": {"data": {"x": 1}, "request_id": "r"}})
    assert c._get("/whatever") == {"x": 1}


def test_iter_realized_pnl_real_envelope():
    item = {"timestamp": "1782750984000000000", "market_id": "5", "side": "SELL",
            "entry_price": "64.196", "exit_price": "64.1972534", "size": "1.57",
            "pnl": "-0.001967838", "funding": "0"}
    env = {"data": {"address": "0xabc", "data": [item], "page": 1, "total": 1,
                    "has_next_page": False}, "request_id": "r"}
    c = _live_client({"/v1/portfolio/realized-pnl": env})
    out = list(c.iter_realized_pnl(0, 10**18))
    assert len(out) == 1 and out[0]["market_id"] == "5" and out[0]["side"] == "SELL"


def test_iter_trade_history_real_envelope():
    fill = {"id": "0xfill", "order_id": "0xord", "market_id": "5", "side": "BUY",
            "price": "64.178", "size": "1.57", "fee": "0.03", "time": "1782750984000000000"}
    env = {"data": {"market_id": "5", "wallet_address": "0xabc", "trades": [fill],
                    "page": 1, "has_next_page": False}, "request_id": "r"}
    c = _live_client({"/v1/trade-history": env})
    out = list(c.iter_trade_history(0, 10**18))
    assert len(out) == 1 and out[0]["id"] == "0xfill"


def test_fetch_markets_real_shape():
    env = {"data": {"markets": [
        {"market_id": "1", "config": {"name": "BTC/USDC"}, "display_name": "BTC/USDC"},
        {"market_id": "5", "config": {"name": "WIF/USDC"}, "display_name": "WIF/USDC"},
    ]}, "request_id": "r"}
    # portfolio/details with no positions so the supplement step adds nothing
    pd = {"data": {"account": "0xabc", "summary": {}, "positions": []}, "request_id": "r"}
    c = _live_client({"/v1/markets": env, "/v1/portfolio/details": pd})
    markets = c.fetch_markets()
    assert markets[1] == "BTC/USDC" and markets[5] == "WIF/USDC"
    assert c.market_name(5) == "WIF/USDC"


def test_fetch_open_positions_uses_size_sign_and_tpsl_stop():
    # `size` is SIGNED (negative = short); the `side` field is unreliable (here 0
    # on a short). Stop loss comes from the /v1/orders/tpsl STOP_LOSS order matched
    # by market_id; take-profit orders are ignored.
    pd = {"data": {"account": "0xabc", "summary": {}, "positions": [
        {"size": "0", "side": 0, "market_name": "TAO/USDC", "market_id": "7"},  # flat -> skipped
        {"size": "-77.01", "side": 0, "market_name": "HYPE/USDC", "market_id": "5",
         "avg_entry_price": "64.2", "mark_price": "64.0", "unrealized_pnl": "12",
         "liquidation_price": "80", "leverage": "20", "margin_mode": 0},
    ]}, "request_id": "r"}
    tpsl = {"data": {"orders": [
        {"market_id": "5", "stop_type": "STOP_LOSS", "stop_price": "67.83", "side": "BUY",
         "status": "TPSL_ORDER_STATUS_ACCEPTED", "created_at": "100"},
        {"market_id": "5", "stop_type": "TAKE_PROFIT", "stop_price": "60.0", "side": "BUY"},
    ]}, "request_id": "r"}
    c = _live_client({"/v1/portfolio/details": pd, "/v1/orders/tpsl": tpsl})
    rows = c.fetch_open_positions()
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "HYPE/USDC" and r["side"] == "Sell" and r["size"] == 77.01
    assert r["stopLoss"] == 67.83   # STOP_LOSS used, TAKE_PROFIT ignored


def test_stop_loss_uses_latest_accepted_not_cancelled():
    # /v1/orders/tpsl returns full history: editing a stop cancels the old order and
    # accepts a new one. Only the latest ACCEPTED order is the live stop — cancelled
    # orders (even if last in the list) must be ignored, else the cockpit locks on a
    # stale value.
    tpsl = {"data": {"orders": [
        {"market_id": "5", "stop_type": "STOP_LOSS", "stop_price": "67.164",
         "status": "TPSL_ORDER_STATUS_ACCEPTED", "created_at": "200"},   # the live one
        {"market_id": "5", "stop_type": "STOP_LOSS", "stop_price": "66.836",
         "status": "TPSL_ORDER_STATUS_CANCELLED", "created_at": "150"},
        {"market_id": "5", "stop_type": "STOP_LOSS", "stop_price": "67.83",
         "status": "TPSL_ORDER_STATUS_CANCELLED", "created_at": "100"},   # oldest, last in list
        {"market_id": "5", "stop_type": "TAKE_PROFIT", "stop_price": "54",
         "status": "TPSL_ORDER_STATUS_ACCEPTED", "created_at": "210"},
    ]}, "request_id": "r"}
    c = _live_client({"/v1/orders/tpsl": tpsl})
    assert c._stop_loss_by_market() == {5: 67.164}   # latest ACCEPTED stop-loss, not a cancelled one


def test_fetch_wallet_balance_real_envelope():
    pd = {"data": {"account": "0xabc", "summary": {"total_account_value": "510.10",
          "usdc_balance": "510.10", "free_collateral": "510.10"}, "positions": []},
          "request_id": "r"}
    c = _live_client({"/v1/portfolio/details": pd})
    assert c.fetch_wallet_balance() == {"equity": 510.10, "balance": 510.10, "available": 510.10}


def test_candle_snapshot_parses_trading_view_envelope():
    # trading-view-data wraps bars under data.data (same outer envelope); 1m bars,
    # ns timestamps, string OHLCV.
    env = {"data": {"data": [
        {"market_id": "5", "interval": "1m", "time": "1782801540000000000",
         "open": "65.554", "high": "65.629", "low": "65.576", "close": "65.588", "volume": "19.53"},
        {"market_id": "5", "interval": "1m", "time": "1782801600000000000",
         "open": "65.588", "high": "65.600", "low": "65.492", "close": "65.492", "volume": "2.86"},
    ]}, "request_id": "r"}
    c = _live_client({"/v1/markets/id/5/trading-view-data": env})
    bars = c.candle_snapshot(5, 1782801540000, 1782801700000)
    assert len(bars) == 2
    assert bars[0]["time"] == 1782801540          # ns -> seconds
    assert bars[0]["open"] == 65.554 and bars[0]["close"] == 65.588
    assert bars[0]["high"] == 65.629 and bars[0]["low"] == 65.576
    assert bars[1]["time"] == 1782801600


def test_fetch_markets_survives_portfolio_supplement_error(monkeypatch):
    # a market-data-only client (empty address) must still resolve markets even if
    # the portfolio supplement call fails.
    env = {"data": {"markets": [{"market_id": "5", "config": {"name": "HYPE/USDC"}}]},
           "request_id": "r"}
    c = RiseXClient("", "https://api.test", min_interval_s=0)
    c._client = _FakeHttp({"/v1/markets": env})
    def boom():
        raise RuntimeError("400 no account")
    monkeypatch.setattr(c, "fetch_portfolio", boom)
    assert c.fetch_markets()[5] == "HYPE/USDC"
