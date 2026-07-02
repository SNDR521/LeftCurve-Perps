"""venue_trade: the only module that places orders. Reduce-only closes."""
import pytest

from app.perps.models import Venue
from app.perps.services import venue_trade
from app.perps.services.venue_trade import CloseError, resolve_close_qty


# --- resolve_close_qty (pure) ------------------------------------------------

def test_fraction_rounds_down_to_step():
    # 25% of 0.7 = 0.175 -> step 0.01 -> 0.17 (never round up on a close)
    assert resolve_close_qty(0.7, fraction=0.25, qty=None,
                             qty_step="0.01", min_qty="0.01") == "0.17"


def test_full_close_uses_exact_size_without_rounding():
    # 100% must send the venue's own (step-aligned) size verbatim
    assert resolve_close_qty(0.703, fraction=1.0, qty=None,
                             qty_step="0.01", min_qty="0.01") == "0.703"


def test_custom_qty_rounds_down_and_caps_at_size():
    assert resolve_close_qty(2.0, fraction=None, qty=1.2345,
                             qty_step="0.1", min_qty="0.1") == "1.2"
    with pytest.raises(CloseError) as e:
        resolve_close_qty(2.0, fraction=None, qty=2.5, qty_step="0.1", min_qty="0.1")
    assert e.value.code == "qty_exceeds_position"


def test_qty_below_min_or_zero_after_rounding_errors():
    with pytest.raises(CloseError) as e:
        resolve_close_qty(0.005, fraction=0.1, qty=None, qty_step="0.001", min_qty="0.001")
    # 10% of 0.005 = 0.0005 -> rounds to 0 -> too small
    assert e.value.code == "qty_too_small"
    assert "0.001" in e.value.message  # error names the step/min


def test_exactly_one_of_fraction_qty():
    for kw in ({"fraction": None, "qty": None}, {"fraction": 0.5, "qty": 1.0}):
        with pytest.raises(CloseError) as e:
            resolve_close_qty(1.0, qty_step="0.1", min_qty="0", **kw)
        assert e.value.code == "bad_request"


def test_fraction_out_of_range():
    for f in (0.0, -0.5, 1.5):
        with pytest.raises(CloseError) as e:
            resolve_close_qty(1.0, fraction=f, qty=None, qty_step="0.1", min_qty="0")
        assert e.value.code == "bad_request"


def test_decimal_precision_no_float_dust():
    # 0.1 steps are inexact in binary floats; Decimal math must keep "0.3" clean
    assert resolve_close_qty(1.0, fraction=None, qty=0.3, qty_step="0.1", min_qty="0.1") == "0.3"


# --- can_close ----------------------------------------------------------------

class _Acc:
    def __init__(self, venue, creds=b"x"):
        self.venue = venue
        self.encrypted_credentials = creds
        self.id = 1


def test_can_close_bybit_with_creds_only():
    assert venue_trade.can_close(_Acc(Venue.BYBIT)) is True
    assert venue_trade.can_close(_Acc(Venue.BYBIT, creds=None)) is False
    assert venue_trade.can_close(_Acc(Venue.HYPERLIQUID)) is False
    assert venue_trade.can_close(_Acc(Venue.RISEX)) is False


# --- close_position dispatch ---------------------------------------------------

class _FakeTradingClient:
    def __init__(self, positions, fail=None):
        self._positions = positions
        self._fail = fail
        self.placed = None
        class _C:
            def close(self):
                pass
        self._client = _C()

    def fetch_open_positions(self):
        return self._positions

    def fetch_lot_rules(self, symbol):
        return {"qty_step": "0.01", "min_qty": "0.01"}

    def close_position(self, symbol, qty, close_side):
        if self._fail is not None:
            raise self._fail
        self.placed = {"symbol": symbol, "qty": qty, "close_side": close_side}
        return {"order_id": "oid-1"}


def _close(monkeypatch, acc, client, symbol="ETHUSDT", **kw):
    monkeypatch.setattr(venue_trade.venue_sync, "client_for", lambda a: client)
    return venue_trade.close_position(None, acc, symbol, **kw)


def test_close_long_places_sell(monkeypatch):
    client = _FakeTradingClient([{"symbol": "ETHUSDT", "side": "Buy", "size": "2"}])
    out = _close(monkeypatch, _Acc(Venue.BYBIT), client, fraction=0.5)
    assert client.placed == {"symbol": "ETHUSDT", "qty": "1", "close_side": "Sell"}
    assert out == {"status": "accepted", "order_id": "oid-1",
                   "requested_qty": "1", "venue": "BYBIT"}


def test_close_short_places_buy(monkeypatch):
    client = _FakeTradingClient([{"symbol": "ETHUSDT", "side": "Sell", "size": "2"}])
    _close(monkeypatch, _Acc(Venue.BYBIT), client, fraction=1.0)
    assert client.placed["close_side"] == "Buy" and client.placed["qty"] == "2"


def test_close_no_position(monkeypatch):
    client = _FakeTradingClient([])
    with pytest.raises(CloseError) as e:
        _close(monkeypatch, _Acc(Venue.BYBIT), client, fraction=0.5)
    assert e.value.code == "no_position"


def test_close_unsupported_venue(monkeypatch):
    with pytest.raises(CloseError) as e:
        _close(monkeypatch, _Acc(Venue.HYPERLIQUID), _FakeTradingClient([]), fraction=0.5)
    assert e.value.code == "unsupported"


def test_permission_retcode_maps(monkeypatch):
    from app.perps.connectors.bybit import BybitError
    client = _FakeTradingClient([{"symbol": "ETHUSDT", "side": "Buy", "size": "2"}],
                                fail=BybitError("denied", ret_code=10005))
    with pytest.raises(CloseError) as e:
        _close(monkeypatch, _Acc(Venue.BYBIT), client, fraction=0.5)
    assert e.value.code == "permission"
    assert "trade" in e.value.message.lower()


def test_other_bybit_error_maps_to_venue_rejected(monkeypatch):
    from app.perps.connectors.bybit import BybitError
    client = _FakeTradingClient([{"symbol": "ETHUSDT", "side": "Buy", "size": "2"}],
                                fail=BybitError("reduce-only rule", ret_code=110017))
    with pytest.raises(CloseError) as e:
        _close(monkeypatch, _Acc(Venue.BYBIT), client, fraction=0.5)
    assert e.value.code == "venue_rejected"


def test_lot_rules_bybit_error_maps_to_venue_rejected(monkeypatch):
    """Amendment: fetch_lot_rules now raises BybitError on unknown instrument."""
    from app.perps.connectors.bybit import BybitError
    client = _FakeTradingClient([{"symbol": "ETHUSDT", "side": "Buy", "size": "2"}])
    def _raise_rules(symbol):
        raise BybitError(f"no lot rules for {symbol}")
    client.fetch_lot_rules = _raise_rules
    with pytest.raises(CloseError) as e:
        _close(monkeypatch, _Acc(Venue.BYBIT), client, fraction=0.5)
    assert e.value.code == "venue_rejected"


def test_transport_error_maps_to_venue_rejected(monkeypatch):
    import httpx
    client = _FakeTradingClient([{"symbol": "ETHUSDT", "side": "Buy", "size": "2"}],
                                fail=httpx.ConnectTimeout("timed out"))
    with pytest.raises(CloseError) as e:
        _close(monkeypatch, _Acc(Venue.BYBIT), client, fraction=0.5)
    assert e.value.code == "venue_rejected"
    assert "check the exchange" in e.value.message
