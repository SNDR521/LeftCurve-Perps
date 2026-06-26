import pytest

from app.perps.services.candles import choose_interval, fetch_klines, VALID_INTERVALS


def test_choose_interval_scales_with_duration():
    assert choose_interval(30 * 60) == "1"            # 30m trade → 1m bars
    assert choose_interval(20 * 3600) == "3"          # 20h → 1200 1m-bars > 1000 → 3m
    assert choose_interval(7 * 24 * 3600) == "15"     # 1 week → 15m
    assert choose_interval(400 * 24 * 3600) == "720"  # ~13 months → 12h bars
    assert choose_interval(5 * 365 * 24 * 3600) == "D"


def test_valid_intervals_contains_bybit_codes():
    assert {"1", "5", "60", "240", "D"} <= VALID_INTERVALS


class _Resp:
    status_code = 200
    def __init__(self, rows): self._rows = rows
    def raise_for_status(self): pass
    def json(self):
        return {"retCode": 0, "result": {"list": self._rows}}


class _Client:
    """Bybit returns newest-first rows: [startMs, open, high, low, close, volume, turnover]."""
    def __init__(self, pages): self.pages = pages; self.calls = []
    def get(self, url, params=None):
        self.calls.append(params)
        return _Resp(self.pages.pop(0) if self.pages else [])


def test_fetch_klines_paginates_and_returns_ascending():
    page1 = [["120000", "101", "103", "100", "102", "5", "0"],
             ["60000", "100", "102", "99", "101", "4", "0"]]
    page2 = [["0", "99", "101", "98", "100", "3", "0"]]
    client = _Client([page1, page2])
    candles = fetch_klines("BTCUSDT", "1", 0, 120000, client=client)
    assert [c["time"] for c in candles] == [0, 60, 120]
    assert candles[0]["open"] == 99.0 and candles[2]["close"] == 102.0
    # second request must page backwards from the oldest seen bar
    assert client.calls[1]["end"] == 60000 - 1


def test_fetch_klines_dedupes_overlapping_pages():
    page1 = [["60000", "100", "102", "99", "101", "4", "0"]]
    page2 = [["60000", "100", "102", "99", "101", "4", "0"],
             ["0", "99", "101", "98", "100", "3", "0"]]
    candles = fetch_klines("BTCUSDT", "1", 0, 60000, client=_Client([page1, page2]))
    assert [c["time"] for c in candles] == [0, 60]


def test_fetch_klines_raises_on_bad_retcode():
    class _BadResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"retCode": 10001, "retMsg": "params error"}
    class _ErrClient:
        def get(self, url, params=None): return _BadResp()
    with pytest.raises(RuntimeError, match="retCode=10001"):
        fetch_klines("BTCUSDT", "1", 0, 60000, client=_ErrClient())


def test_fetch_klines_keeps_bar_containing_start():
    # Bybit may return the bar that CONTAINS start_ms (startMs < start_ms).
    # MFE needs that bar — it must not be filtered out.
    page = [["60000", "100", "102", "99", "101", "4", "0"],
            ["0", "99", "101", "98", "100", "3", "0"]]
    candles = fetch_klines("BTCUSDT", "1", 30000, 60000, client=_Client([page]))
    assert [c["time"] for c in candles] == [0, 60]


def test_fetch_klines_retries_on_429(monkeypatch):
    import app.perps.services.candles as candles_mod
    monkeypatch.setattr(candles_mod.time, "sleep", lambda s: None)

    class _R429:
        status_code = 429
        def raise_for_status(self): pass
        def json(self): return {}

    page = [["0", "99", "101", "98", "100", "3", "0"]]

    class _C:
        def __init__(self): self.calls = 0
        def get(self, url, params=None):
            self.calls += 1
            return _R429() if self.calls == 1 else _Resp(page)

    c = _C()
    out = fetch_klines("BTCUSDT", "1", 0, 60000, client=c)
    assert [x["time"] for x in out] == [0]
    assert c.calls == 2
