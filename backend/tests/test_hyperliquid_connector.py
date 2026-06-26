from app.perps.connectors.hyperliquid import HyperliquidClient


class FakePost:
    """Stand-in for HyperliquidClient._post: returns queued responses by request `type`."""
    def __init__(self, responses):
        self.responses = responses  # dict: type -> list of response payloads (popped in order)
        self.calls = []

    def __call__(self, body):
        self.calls.append(body)
        queue = self.responses.get(body["type"])
        if isinstance(queue, list):
            return queue.pop(0) if queue else []
        return queue


def make_client(responses):
    c = HyperliquidClient("0x" + "b" * 40)
    c._post = FakePost(responses)
    return c


def _fill(t, coin="ETH", sz="1", side="B", px="100", dir="Open Long"):
    return {"coin": coin, "px": px, "sz": sz, "side": side, "time": t, "dir": dir,
            "closedPnl": "0", "fee": "0.1", "oid": t, "hash": f"h{t}",
            "startPosition": "0", "tid": t}


def test_iter_fills_single_page():
    c = make_client({"userFillsByTime": [[_fill(1000), _fill(2000)]]})
    fills = list(c.iter_fills_by_time(0, 9999))
    assert [f["time"] for f in fills] == [1000, 2000]


def test_iter_fills_paginates_until_short_page():
    full = [_fill(1000 + i) for i in range(2000)]  # exactly PAGE_LIMIT -> must request again
    tail = [_fill(5000), _fill(5001)]
    c = make_client({"userFillsByTime": [full, tail, []]})
    fills = list(c.iter_fills_by_time(0, 9999))
    assert len(fills) == 2002
    # Second request must advance startTime past the last fill time of page 1.
    assert c._post.calls[1]["startTime"] == 1000 + 1999 + 1


def test_iter_fills_stops_if_cursor_does_not_advance():
    # Pathological: a full page whose last time == window start; must not loop forever.
    stuck = [_fill(0) for _ in range(2000)]
    c = make_client({"userFillsByTime": [stuck] * 50})
    fills = list(c.iter_fills_by_time(0, 9999))
    assert len(fills) == 2000  # one page then bail (startTime did not advance)


def test_fetch_open_positions_maps_to_bybit_shape():
    c = make_client({"clearinghouseState": {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "60000",
                          "unrealizedPnl": "120", "liquidationPx": "50000",
                          "leverage": {"type": "cross", "value": 10}}},
            {"position": {"coin": "ETH", "szi": "-2", "entryPx": "3000",
                          "unrealizedPnl": "-40", "liquidationPx": "3600",
                          "leverage": {"type": "isolated", "value": 5}}},
            {"position": {"coin": "SOL", "szi": "0", "entryPx": "0"}},  # flat -> skipped
        ],
        "marginSummary": {"accountValue": "10000", "totalMarginUsed": "2000"},
        "withdrawable": "8000",
    }})
    rows = c.fetch_open_positions()
    assert len(rows) == 2
    btc = next(r for r in rows if r["symbol"] == "BTC")
    assert btc["side"] == "Buy" and btc["size"] == 0.5 and btc["avgPrice"] == 60000.0
    assert btc["liqPrice"] == 50000.0 and btc["leverage"] == 10.0 and btc["stopLoss"] is None
    eth = next(r for r in rows if r["symbol"] == "ETH")
    assert eth["side"] == "Sell" and eth["size"] == 2.0


def test_fetch_open_positions_reads_stop_from_trigger_orders():
    c = make_client({
        "clearinghouseState": {
            "assetPositions": [
                {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "60000",
                              "liquidationPx": "50000", "leverage": {"value": 10}}},
                {"position": {"coin": "ETH", "szi": "-2", "entryPx": "3000",
                              "liquidationPx": "3600", "leverage": {"value": 5}}},
            ],
            "marginSummary": {"accountValue": "10000"}, "withdrawable": "8000",
        },
        "frontendOpenOrders": [[
            # BTC stop-loss → picked up; the take-profit on BTC is ignored
            {"coin": "BTC", "isTrigger": True, "orderType": "Stop Market",
             "triggerPx": "58000", "reduceOnly": True, "isPositionTpsl": True},
            {"coin": "BTC", "isTrigger": True, "orderType": "Take Profit Market",
             "triggerPx": "65000", "reduceOnly": True, "isPositionTpsl": True},
            # a non-reduce stop-entry is ignored; ETH has no stop
            {"coin": "SOL", "isTrigger": True, "orderType": "Stop Market",
             "triggerPx": "100", "reduceOnly": False, "isPositionTpsl": False},
        ]],
    })
    rows = c.fetch_open_positions()
    btc = next(r for r in rows if r["symbol"] == "BTC")
    eth = next(r for r in rows if r["symbol"] == "ETH")
    assert btc["stopLoss"] == 58000.0     # the stop-loss trigger, not the take-profit
    assert eth["stopLoss"] is None        # no stop order for ETH


def test_fetch_open_positions_no_stop_when_no_orders():
    c = make_client({"clearinghouseState": {
        "assetPositions": [{"position": {"coin": "BTC", "szi": "1", "entryPx": "60000",
                                         "leverage": {"value": 10}}}],
        "marginSummary": {"accountValue": "1"}, "withdrawable": "1"}})
    assert c.fetch_open_positions()[0]["stopLoss"] is None


def test_fetch_wallet_balance():
    c = make_client({"clearinghouseState": {
        "marginSummary": {"accountValue": "10000"}, "withdrawable": "8000"}})
    bal = c.fetch_wallet_balance()
    assert bal == {"equity": 10000.0, "balance": 10000.0, "available": 8000.0}


def test_iter_funding_yields_rows():
    c = make_client({"userFunding": [[
        {"time": 1000, "hash": "f1", "delta": {"coin": "ETH", "usdc": "-0.5",
                                               "szi": "1", "fundingRate": "0.0001", "type": "funding"}},
    ]]})
    rows = list(c.iter_funding(0, 9999))
    assert rows[0]["delta"]["coin"] == "ETH"


def test_fetch_tickers_maps_bybit_shape():
    # FakePost treats list values as a queue (pops items); wrap the full [meta, ctxs]
    # array in an outer list so one pop returns the complete 2-element array.
    c = make_client({"metaAndAssetCtxs": [
        [
            {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
            [
                {"markPx": "60000.0", "funding": "0.0000125"},   # hourly rate
                {"markPx": "3000.0", "funding": "-0.00001"},
            ],
        ],
    ]})
    t = c.fetch_tickers(["BTC", "ETH"])
    assert t["BTC"]["mark_price"] == 60000.0
    # funding normalized to an 8h-equivalent (hourly * 8) to match Bybit's cadence
    assert abs(t["BTC"]["funding_rate"] - 0.0000125 * 8) < 1e-12
    assert t["ETH"]["mark_price"] == 3000.0
    assert t["BTC"]["next_funding_time"] > 0


def test_fetch_tickers_filters_to_requested_symbols():
    c = make_client({"metaAndAssetCtxs": [
        [
            {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}]},
            [{"markPx": "1", "funding": "0"}, {"markPx": "2", "funding": "0"},
             {"markPx": "3", "funding": "0"}],
        ],
    ]})
    t = c.fetch_tickers(["SOL"])
    assert set(t.keys()) == {"SOL"} and t["SOL"]["mark_price"] == 3.0


def test_candle_snapshot_maps_ascending_ohlcv():
    # FakePost treats list values as a queue; wrap candle rows in an outer list.
    c = make_client({"candleSnapshot": [
        [
            {"t": 2000, "T": 2999, "o": "11", "h": "13", "l": "10", "c": "12", "v": "5"},
            {"t": 1000, "T": 1999, "o": "9", "h": "10", "l": "8", "c": "10", "v": "3"},
        ],
    ]})
    candles = c.candle_snapshot("BTC", "1h", 0, 9999)
    assert [bar["time"] for bar in candles] == [1, 2]  # sorted ascending, ms -> seconds
    assert candles[0] == {"time": 1, "open": 9.0, "high": 10.0, "low": 8.0, "close": 10.0, "volume": 3.0}
    req = next(b for b in c._post.calls if b["type"] == "candleSnapshot")["req"]
    assert req["coin"] == "BTC" and req["interval"] == "1h"
