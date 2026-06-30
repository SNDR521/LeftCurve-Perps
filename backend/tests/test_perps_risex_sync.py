from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password, encrypt_credentials
from app.perps.models import (
    ExchangeAccount, Venue, Position, PositionStatus, Direction, Fill,
)
from app.perps.services import risex_sync


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u); s.commit()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.RISEX, label="RiseX",
                          encrypted_credentials=encrypt_credentials({"address": "0xabc"}))
    s.add(acc); s.commit()
    yield s, u, acc
    s.close()


def _view(fid, symbol, side, position_side, price, size, fee, rpnl, time_ns):
    return {"id": fid, "symbol": symbol, "side": side, "position_side": position_side,
            "price": float(price), "size": float(size), "fee": float(fee),
            "realized_pnl": float(rpnl), "time_ns": time_ns}


def test_build_closed_positions_short_round_trip(db):
    # mirrors the real RiseX shape: open SELL then close BUY, position_side SELL.
    # Two realized-pnl/fill events that are ONE round-trip -> ONE closed position.
    _, _, acc = db
    views = [
        _view("o", "HYPE/USDC", "SELL", "SELL", "64.196", "1.57", "0.0302", "-0.0302", 1782750970000000000),
        _view("c", "HYPE/USDC", "BUY",  "SELL", "64.178", "1.57", "0.0302", "-0.00197", 1782750984000000000),
    ]
    rows = risex_sync.build_closed_positions(acc, views)
    assert len(rows) == 1
    r = rows[0]
    assert r["direction"] == Direction.SHORT
    assert r["quantity"] == 1.57
    assert abs(r["avg_entry"] - 64.196) < 1e-9 and abs(r["avg_exit"] - 64.178) < 1e-9
    assert abs(r["realized_pnl"] - (-0.03217)) < 1e-6   # sum of both fills' realized_pnl
    assert abs(r["total_fees"] - 0.0604) < 1e-9         # sum of both fills' fees
    assert r["position_key"] == f"{acc.id}:HYPE/USDC:rt:c"   # keyed by closing fill
    assert r["opened_at"] < r["closed_at"]


def test_build_closed_positions_scale_in_and_partial_close(db):
    _, _, acc = db
    views = [
        _view("e1", "BTC/USDC", "BUY",  "BUY", "100", "1", "0.1", "-0.1", 1),
        _view("e2", "BTC/USDC", "BUY",  "BUY", "120", "1", "0.1", "-0.1", 2),  # scale-in
        _view("x1", "BTC/USDC", "SELL", "BUY", "130", "1", "0.1", "9.9", 3),   # partial close
        _view("x2", "BTC/USDC", "SELL", "BUY", "140", "1", "0.1", "19.9", 4),  # full close
    ]
    rows = risex_sync.build_closed_positions(acc, views)
    assert len(rows) == 1
    r = rows[0]
    assert r["direction"] == Direction.LONG and r["quantity"] == 2.0
    assert abs(r["avg_entry"] - 110.0) < 1e-9   # (100+120)/2
    assert abs(r["avg_exit"] - 135.0) < 1e-9    # (130+140)/2
    assert abs(r["realized_pnl"] - 29.6) < 1e-9  # -0.1-0.1+9.9+19.9
    assert r["position_key"] == f"{acc.id}:BTC/USDC:rt:x2"


def test_build_closed_positions_unclosed_skipped(db):
    _, _, acc = db
    views = [_view("o", "SOL/USDC", "BUY", "BUY", "100", "1", "0.1", "-0.1", 1)]  # never flat
    assert risex_sync.build_closed_positions(acc, views) == []


def test_build_closed_positions_two_round_trips(db):
    _, _, acc = db
    views = [
        _view("a1", "ETH/USDC", "BUY",  "BUY",  "100", "1", "0", "0", 1),
        _view("a2", "ETH/USDC", "SELL", "BUY",  "110", "1", "0", "10", 2),  # close long
        _view("b1", "ETH/USDC", "SELL", "SELL", "120", "1", "0", "0", 3),   # open short
        _view("b2", "ETH/USDC", "BUY",  "SELL", "115", "1", "0", "5", 4),   # close short
    ]
    rows = risex_sync.build_closed_positions(acc, views)
    assert len(rows) == 2
    assert rows[0]["direction"] == Direction.LONG and rows[1]["direction"] == Direction.SHORT


class _FakeClient:
    """A single open(BUY)+close(SELL) round-trip -> one reconstructed LONG position."""
    def __init__(self):
        self.closed = False
    def fetch_markets(self):
        return {1: "BTC/USDC"}
    def market_name(self, mid):
        return {1: "BTC/USDC"}.get(int(mid), f"MKT{mid}")
    def iter_realized_pnl(self, a, b):
        return iter([])  # no longer used by the sync (closed positions come from fills)
    def iter_trade_history(self, a, b):
        return iter([
            {"id": "f1", "order_id": "o1", "market_id": 1, "side": "BUY",
             "position_side": "BUY", "price": "60000", "size": "2", "fee": "1.0",
             "realized_pnl": "-1.0", "time": 1_699_999_000_000_000_000},
            {"id": "f2", "order_id": "o2", "market_id": 1, "side": "SELL",
             "position_side": "BUY", "price": "62000", "size": "2", "fee": "1.0",
             "realized_pnl": "3999.0", "time": 1_699_999_500_000_000_000},
        ])
    def fetch_open_positions(self):
        return [{"symbol": "ETH/USDC", "side": "Sell", "size": 3.0, "avgPrice": 3000.0,
                 "unrealisedPnl": 0.0, "liqPrice": None, "leverage": 10.0,
                 "stopLoss": None, "tradeMode": 0}]
    def close(self):
        self.closed = True


def test_sync_account_end_to_end_and_idempotent(db, monkeypatch):
    s, _, acc = db
    monkeypatch.setattr(risex_sync, "_client_for", lambda account: _FakeClient())
    summary = risex_sync.sync_account(s, acc)
    assert summary["error"] is None
    assert summary["fills_added"] == 2
    assert summary["closed_added"] == 1 and summary["open_count"] == 1
    closed = s.query(Position).filter_by(exchange_account_id=acc.id,
                                         status=PositionStatus.CLOSED).all()
    assert len(closed) == 1
    assert closed[0].direction == Direction.LONG and closed[0].quantity == 2.0
    assert abs(closed[0].realized_pnl - 3998.0) < 1e-9   # -1.0 + 3999.0
    assert s.query(Fill).filter_by(exchange_account_id=acc.id).count() == 2
    # re-run: rebuild-from-fills + fill dedup => still ONE closed, TWO fills
    risex_sync.sync_account(s, acc)
    assert s.query(Position).filter_by(exchange_account_id=acc.id,
                                       status=PositionStatus.CLOSED).count() == 1
    assert s.query(Fill).filter_by(exchange_account_id=acc.id).count() == 2


# --- venue_sync wiring tests ---

from app.perps.services import venue_sync  # noqa: E402
from app.perps.connectors.risex import RiseXClient  # noqa: E402


def test_venue_sync_supports_and_dispatches_risex(db, monkeypatch):
    s, _, acc = db
    assert Venue.RISEX in venue_sync.SUPPORTED_VENUES
    assert isinstance(venue_sync.client_for(acc), RiseXClient)
    called = {}
    monkeypatch.setattr(risex_sync, "sync_account", lambda d, a: called.setdefault("hit", True) or {"ok": 1})
    venue_sync.sync_account(s, acc)
    assert called.get("hit") is True


# --- chunked fills tests (Fix 1 + Fix 2) ---

class _FakeClientLargeFills:
    def fetch_markets(self):
        return {1: "BTC-USD"}
    def market_name(self, mid):
        return {1: "BTC-USD"}.get(int(mid), f"MKT{mid}")
    def iter_realized_pnl(self, a, b):
        return iter([])
    def iter_trade_history(self, a, b):
        base_time = 1_699_999_000_000_000_000
        for i in range(600):
            yield {"id": f"fill_{i}", "order_id": f"ord_{i}", "market_id": 1,
                   "side": "BUY", "price": "60000", "size": "1", "fee": "0.1",
                   "time": base_time + i * 1_000_000}
    def fetch_open_positions(self):
        return []
    def close(self):
        pass


def test_large_fills_batch_chunked_and_dedups(db, monkeypatch):
    """600 fills (> CHUNK=500) sync without error; second run adds 0 duplicates."""
    s, _, acc = db
    monkeypatch.setattr(risex_sync, "_client_for", lambda account: _FakeClientLargeFills())
    summary = risex_sync.sync_account(s, acc)
    assert summary["error"] is None
    assert summary["fills_added"] == 600
    assert s.query(Fill).filter_by(exchange_account_id=acc.id).count() == 600
    # idempotency: re-run must not duplicate
    summary2 = risex_sync.sync_account(s, acc)
    assert summary2["fills_added"] == 0
    assert s.query(Fill).filter_by(exchange_account_id=acc.id).count() == 600


def test_sync_progress_fields_populated(db, monkeypatch):
    """sync_progress must contain the keys the SyncProgress widget reads (Fix 2)."""
    s, _, acc = db
    monkeypatch.setattr(risex_sync, "_client_for", lambda account: _FakeClientLargeFills())
    risex_sync.sync_account(s, acc)
    prog = acc.sync_progress
    for key in ("from_ms", "to_ms", "cursor_ms", "fills"):
        assert key in prog, f"sync_progress missing key: {key}"
