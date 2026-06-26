import hmac, hashlib
from app.perps.connectors.bybit import BybitClient, _query_string, _sign


def test_query_string_is_sorted_and_joined():
    assert _query_string({"category": "linear", "startTime": 10, "endTime": 20}) == \
        "category=linear&endTime=20&startTime=10"


def test_sign_matches_hmac_sha256():
    qs = "category=linear&endTime=20&startTime=10"
    sig = _sign("secret", "1700000000000", "k", "5000", qs)
    expected = hmac.new(b"secret", b"1700000000000k5000" + qs.encode(), hashlib.sha256).hexdigest()
    assert sig == expected


def test_iter_executions_pages_and_normalizes(monkeypatch):
    c = BybitClient("k", "s")
    pages = [
        {"result": {"list": [{"execId": "e1", "symbol": "BTCUSDT", "side": "Buy",
                              "execPrice": "100", "execQty": "1", "execFee": "0.1",
                              "feeCurrency": "USDT", "execTime": "1700000000000", "orderId": "o1"}],
                    "nextPageCursor": "CUR"}},
        {"result": {"list": [{"execId": "e2", "symbol": "BTCUSDT", "side": "Sell",
                              "execPrice": "110", "execQty": "1", "execFee": "0.1",
                              "feeCurrency": "USDT", "execTime": "1700000100000", "orderId": "o2"}],
                    "nextPageCursor": ""}},
    ]
    calls = []
    def fake_get(path, params):
        calls.append(params.get("cursor"))
        return pages[len(calls) - 1]
    monkeypatch.setattr(c, "_signed_get", fake_get)
    rows = list(c.iter_executions(1_700_000_000_000, 1_700_000_200_000))
    assert [r["execId"] for r in rows] == ["e1", "e2"]
    assert calls == [None, "CUR"]            # second call used the cursor


def test_client_throttles_between_requests(monkeypatch):
    import time as _t
    from app.perps.connectors import bybit
    c = bybit.BybitClient("k", "s", min_interval_s=0.05)

    class _Resp:
        status_code = 200
        def json(self): return {"retCode": 0, "result": {}}
        def raise_for_status(self): pass

    monkeypatch.setattr(c._client, "get", lambda *a, **k: _Resp())
    t0 = _t.monotonic()
    c._signed_get("/x", {})   # first call: no wait
    c._signed_get("/x", {})   # second: must wait ~min_interval
    assert _t.monotonic() - t0 >= 0.045


def test_paged_recovers_tail_after_transient_empty_page(monkeypatch):
    # Bybit intermittently returns an empty list with a live, ADVANCING cursor
    # mid-stream. The pager must keep going and recover the rest of the window —
    # stopping on the first empty page silently dropped fills (positions then
    # never net flat). The window ends when the cursor finally comes back empty.
    from app.perps.connectors import bybit
    c = bybit.BybitClient("k", "s")
    pages = [
        {"result": {"list": [{"execId": "e1"}], "nextPageCursor": "C1"}},
        {"result": {"list": [], "nextPageCursor": "C2"}},          # transient empty page
        {"result": {"list": [{"execId": "e2"}], "nextPageCursor": "C3"}},
        {"result": {"list": [{"execId": "e3"}], "nextPageCursor": ""}},  # true end
    ]
    calls = {"n": 0}
    def fake_get(path, params):
        i = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return pages[i]
    monkeypatch.setattr(c, "_signed_get", fake_get)
    rows = list(c._paged("/v5/execution/list", {}))
    assert [r["execId"] for r in rows] == ["e1", "e2", "e3"]   # tail recovered, nothing dropped


def test_paged_terminates_on_persistent_empty_pages(monkeypatch):
    # The infinite-loop guard still holds: if Bybit keeps returning empty lists with
    # an ever-changing cursor (past the end), the pager bails after a few of them.
    from app.perps.connectors import bybit
    c = bybit.BybitClient("k", "s")
    calls = {"n": 0}
    def fake_get(path, params):
        calls["n"] += 1
        return {"result": {"list": [], "nextPageCursor": f"C{calls['n']}"}}  # always empty, new cursor
    monkeypatch.setattr(c, "_signed_get", fake_get)
    rows = list(c._paged("/v5/execution/list", {}))
    assert rows == []
    assert calls["n"] <= bybit.EMPTY_PAGE_LIMIT + 1   # bailed quickly, no infinite loop


def test_iter_closed_pnl_pages_and_yields(monkeypatch):
    from app.perps.connectors import bybit
    c = bybit.BybitClient("k", "s")
    pages = [
        {"result": {"list": [{"symbol": "BTCUSDT", "orderId": "o1", "closedPnl": "5"}], "nextPageCursor": "C1"}},
        {"result": {"list": [{"symbol": "BTCUSDT", "orderId": "o2", "closedPnl": "7"}], "nextPageCursor": ""}},
    ]
    calls = {"n": 0}
    def fake_get(path, params):
        assert path == "/v5/position/closed-pnl"
        assert params["category"] == "linear"
        i = min(calls["n"], len(pages) - 1); calls["n"] += 1
        return pages[i]
    monkeypatch.setattr(c, "_signed_get", fake_get)
    rows = list(c.iter_closed_pnl(1, 2))
    assert [r["orderId"] for r in rows] == ["o1", "o2"]


def test_fetch_open_positions_filters_zero_size(monkeypatch):
    from app.perps.connectors import bybit
    c = bybit.BybitClient("k", "s")
    def fake_get(path, params):
        assert path == "/v5/position/list"
        assert params["settleCoin"] == "USDT"
        return {"result": {"list": [
            {"symbol": "BTCUSDT", "side": "Buy", "size": "1.5", "avgPrice": "100"},
            {"symbol": "ETHUSDT", "side": "Sell", "size": "0", "avgPrice": "0"},
        ], "nextPageCursor": ""}}
    monkeypatch.setattr(c, "_signed_get", fake_get)
    rows = c.fetch_open_positions()
    assert [r["symbol"] for r in rows] == ["BTCUSDT"]   # zero-size dropped


# ---------------------------------------------------------------------------
# New methods: fetch_tickers, fetch_wallet_balance, iter_transaction_log
# ---------------------------------------------------------------------------

def test_fetch_tickers_public_and_parsed(monkeypatch):
    from app.perps.connectors import bybit
    c = bybit.BybitClient("k", "s")

    captured = {}

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {
                "retCode": 0,
                "result": {
                    "list": [
                        {"symbol": "BTCUSDT", "markPrice": "50000.5",
                         "fundingRate": "0.0001", "nextFundingTime": "1781200000000"},
                        {"symbol": "ETHUSDT", "markPrice": "2000",
                         "fundingRate": "-0.0002", "nextFundingTime": "1781200000000"},
                    ]
                },
            }

    def fake_http_get(url, params=None, headers=None, **kwargs):
        captured["url"] = url
        captured["params"] = params or {}
        captured["headers"] = headers or {}
        return _Resp()

    monkeypatch.setattr(c._client, "get", fake_http_get)

    result = c.fetch_tickers(["BTCUSDT"])

    # Must use the public endpoint (no signature header)
    assert "X-BAPI-SIGN" not in captured["headers"]
    assert captured["params"].get("category") == "linear"

    # Filter: only requested symbol returned
    assert list(result.keys()) == ["BTCUSDT"]
    btc = result["BTCUSDT"]
    assert btc["mark_price"] == 50000.5
    assert btc["funding_rate"] == 0.0001
    assert btc["next_funding_time"] == 1781200000000


def test_fetch_wallet_balance_signed(monkeypatch):
    from app.perps.connectors import bybit
    c = bybit.BybitClient("k", "s")

    signed_calls = []

    def fake_signed_get(path, params):
        signed_calls.append({"path": path, "params": params})
        return {
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "totalEquity": "1234.5",
                        "totalWalletBalance": "1200",
                        "totalAvailableBalance": "1100",
                    }
                ]
            },
        }

    monkeypatch.setattr(c, "_signed_get", fake_signed_get)

    result = c.fetch_wallet_balance()

    # Signed path must have been called (X-BAPI-SIGN is set by _signed_get;
    # verifying _signed_get was invoked is equivalent per the file's pattern)
    assert len(signed_calls) == 1
    assert signed_calls[0]["path"] == "/v5/account/wallet-balance"
    assert signed_calls[0]["params"]["accountType"] == "UNIFIED"

    assert result == {"equity": 1234.5, "balance": 1200.0, "available": 1100.0}


def test_iter_transaction_log_no_type_filter(monkeypatch):
    from app.perps.connectors import bybit
    c = bybit.BybitClient("k", "s")

    pages = [
        {"result": {"list": [{"id": "tx1", "cashBalance": "1000"}], "nextPageCursor": ""}},
    ]
    calls = {"n": 0}

    def fake_signed_get(path, params):
        assert path == "/v5/account/transaction-log"
        assert params.get("accountType") == "UNIFIED"
        assert params.get("category") == "linear"
        assert params.get("startTime") == 0
        assert params.get("endTime") == 1000
        assert params.get("limit") == 100
        # Must NOT include a type filter
        assert "type" not in params
        i = min(calls["n"], len(pages) - 1)
        calls["n"] += 1
        return pages[i]

    monkeypatch.setattr(c, "_signed_get", fake_signed_get)

    rows = list(c.iter_transaction_log(0, 1000))
    assert rows == [{"id": "tx1", "cashBalance": "1000"}]
