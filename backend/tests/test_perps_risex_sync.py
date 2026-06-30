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


# --- fill_ids tracking + PositionFill link tests ---

def test_build_closed_positions_returns_fill_ids(db):
    """build_closed_positions rows must include fill_ids with the round-trip's external_ids."""
    _, _, acc = db
    views = [
        _view("o", "HYPE/USDC", "SELL", "SELL", "64.196", "1.57", "0.0302", "-0.0302", 1782750970000000000),
        _view("c", "HYPE/USDC", "BUY",  "SELL", "64.178", "1.57", "0.0302", "-0.00197", 1782750984000000000),
    ]
    rows = risex_sync.build_closed_positions(acc, views)
    assert len(rows) == 1
    assert rows[0]["fill_ids"] == ["o", "c"]


def test_sync_creates_and_idempotent_position_fill_links(db, monkeypatch):
    """After sync_account, the closed Position has exactly 2 PositionFill links.
    Re-running sync (idempotent) must leave the count at exactly 2 — no growth."""
    from app.perps.models import PositionFill
    s, _, acc = db
    monkeypatch.setattr(risex_sync, "_client_for", lambda account: _FakeClient())

    risex_sync.sync_account(s, acc)
    closed = s.query(Position).filter_by(exchange_account_id=acc.id,
                                         status=PositionStatus.CLOSED).one()
    links = s.query(PositionFill).filter_by(position_id=closed.id).count()
    assert links == 2, f"Expected 2 PositionFill links after first sync, got {links}"

    # Re-sync: idempotency — link count must not grow
    risex_sync.sync_account(s, acc)
    closed2 = s.query(Position).filter_by(exchange_account_id=acc.id,
                                          status=PositionStatus.CLOSED).one()
    links2 = s.query(PositionFill).filter_by(position_id=closed2.id).count()
    assert links2 == 2, f"After re-sync expected 2 PositionFill links, got {links2}"
    total = (s.query(PositionFill)
             .join(Position, PositionFill.position_id == Position.id)
             .filter(Position.exchange_account_id == acc.id)
             .count())
    assert total == 2, f"Total PositionFill for account must be 2 after re-sync, got {total}"
    # Raw table count (not JOIN-shielded) proves the pre-delete ran — orphan rows
    # pointing at the wiped+recreated positions would be invisible to the JOIN above
    # but would show here. The test DB holds only this account.
    raw = s.query(PositionFill).count()
    assert raw == 2, f"Raw PositionFill rows must be 2 after re-sync (no orphans), got {raw}"


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


# --- balance snapshot reconstruction tests ---

from app.perps.services.risex_sync import build_balance_snapshots  # noqa: E402
from app.perps.models import BalanceSnapshot  # noqa: E402

NS_DAY = 86_400 * 1_000_000_000
D0 = 1_782_000_000 * 1_000_000_000  # an arbitrary ns anchor day start-ish


def test_build_balance_snapshots_no_transfers_anchors_to_realized_now(db):
    _, _, acc = db
    # two realized-pnl events: +10 on day A, -4 on day B; realized_now = 106.
    events = [
        {"ts_ns": D0 + 1 * NS_DAY, "delta": 10.0},
        {"ts_ns": D0 + 2 * NS_DAY, "delta": -4.0},
    ]
    rows = build_balance_snapshots(acc, realized_now=106.0, events=events, transfers=[])
    snaps = [r for r in rows if r["kind"] == "SNAPSHOT"]
    # initial = 106 - (10 - 4) = 100; after day A = 110; after day B = 106
    vals = [r["balance"] for r in sorted(snaps, key=lambda r: r["ts"])]
    assert vals[0] == 110.0          # end of day A (initial 100 + 10)
    assert vals[-1] == 106.0         # latest snapshot == realized_now (anchor)
    assert all(r["kind"] == "SNAPSHOT" for r in snaps)


def test_build_balance_snapshots_daily_last_wins(db):
    _, _, acc = db
    # two events same day -> only the day-last running balance is the snapshot
    events = [
        {"ts_ns": D0 + 5_000, "delta": 10.0},
        {"ts_ns": D0 + 9_000, "delta": -2.0},
    ]
    rows = build_balance_snapshots(acc, realized_now=8.0, events=events, transfers=[])
    snaps = [r for r in rows if r["kind"] == "SNAPSHOT"]
    assert len(snaps) == 1 and snaps[0]["balance"] == 8.0   # initial 0 +10 -2 = 8


def test_build_balance_snapshots_transfer_marker_and_shift(db):
    _, _, acc = db
    events = [{"ts_ns": D0 + 1 * NS_DAY, "delta": 5.0}]
    transfers = [{"ts_ns": D0 + 1 * NS_DAY + 100, "delta": 50.0, "kind": "TRANSFER_IN"}]
    rows = build_balance_snapshots(acc, realized_now=155.0, events=events, transfers=transfers)
    markers = [r for r in rows if r["kind"] == "TRANSFER_IN"]
    snaps = [r for r in rows if r["kind"] == "SNAPSHOT"]
    assert len(markers) == 1
    assert sorted(snaps, key=lambda r: r["ts"])[-1]["balance"] == 155.0  # anchor preserved


def test_build_balance_snapshots_no_events_single_point(db):
    _, _, acc = db
    rows = build_balance_snapshots(acc, realized_now=500.0, events=[], transfers=[])
    snaps = [r for r in rows if r["kind"] == "SNAPSHOT"]
    assert len(snaps) == 1 and snaps[0]["balance"] == 500.0


class _FakeClientWithPortfolio:
    """Extends _FakeClient pattern: also implements fetch_portfolio() and
    iter_transfers() so _rebuild_balance_snapshots can run end-to-end."""
    def __init__(self):
        self.closed = False
    def fetch_markets(self):
        return {1: "BTC/USDC"}
    def market_name(self, mid):
        return {1: "BTC/USDC"}.get(int(mid), f"MKT{mid}")
    def iter_realized_pnl(self, a, b):
        # One realized-pnl event to produce a snapshot
        yield {"timestamp": 1_782_000_000 * 1_000_000_000, "pnl": 5.0, "funding": 0.0}
    def iter_trade_history(self, a, b):
        return iter([
            {"id": "f1", "order_id": "o1", "market_id": 1, "side": "BUY",
             "position_side": "BUY", "price": "60000", "size": "1", "fee": "0.5",
             "realized_pnl": "-0.5", "time": 1_782_000_000 * 1_000_000_000},
        ])
    def fetch_open_positions(self):
        return []
    def fetch_portfolio(self):
        # Response structure matching what RiseX API returns
        return {
            "summary": {
                "total_account_value": "110",
                "total_unrealized_pnl": "0",
                "usdc_balance": "110"
            },
            "positions": []
        }
    def iter_transfers(self, start_ns, end_ns):
        # No transfers: just return without yielding
        return
        yield  # noqa: F501 — unreachable, but syntactically valid generator
    def close(self):
        self.closed = True


def test_sync_account_writes_balance_snapshots(db, monkeypatch):
    """End-to-end: sync_account with _rebuild_balance_snapshots wired in;
    assert BalanceSnapshot rows are written to the database."""
    s, _, acc = db
    monkeypatch.setattr(risex_sync, "_client_for", lambda account: _FakeClientWithPortfolio())
    summary = risex_sync.sync_account(s, acc)
    assert summary["error"] is None
    # Assert that balance snapshots were actually written (end-to-end rebuild ran)
    snapshot_count = s.query(BalanceSnapshot).filter_by(exchange_account_id=acc.id).count()
    assert snapshot_count >= 1, f"Expected >= 1 BalanceSnapshot, got {snapshot_count}"


def test_build_balance_snapshots_drops_zero_ts(db):
    """An event with a zero/unparseable ts must not create a 1970-01-01 point; its
    delta is absorbed into the baseline so the anchor (latest snapshot) is preserved."""
    _, _, acc = db
    events = [
        {"ts_ns": 0, "delta": 50.0},                        # bad ts -> dropped from axis
        {"ts_ns": 1_782_000_000 * 1_000_000_000, "delta": 5.0},
    ]
    rows = build_balance_snapshots(acc, realized_now=155.0, events=events, transfers=[])
    snaps = [r for r in rows if r["kind"] == "SNAPSHOT"]
    assert all(r["ts"].year >= 2000 for r in snaps)         # no 1970 point
    assert sorted(snaps, key=lambda r: r["ts"])[-1]["balance"] == 155.0  # anchor preserved


class _FakeClientWithDeposit(_FakeClientWithPortfolio):
    """Yields a real-shaped DEPOSIT transfer (type/amount/block_time)."""
    def iter_transfers(self, start_ns, end_ns):
        yield {"type": "DEPOSIT", "amount": "100.0",
               "block_time": str(1_782_000_000 * 1_000_000_000)}


def test_rebuild_parses_deposit_transfer(db, monkeypatch):
    """A real-shaped DEPOSIT transfer yields a correctly-dated TRANSFER_IN marker
    (parsed from block_time), never a 1970 point."""
    s, _, acc = db
    monkeypatch.setattr(risex_sync, "_client_for", lambda account: _FakeClientWithDeposit())
    risex_sync.sync_account(s, acc)
    markers = s.query(BalanceSnapshot).filter(
        BalanceSnapshot.exchange_account_id == acc.id,
        BalanceSnapshot.kind == "TRANSFER_IN").all()
    assert len(markers) == 1 and markers[0].ts.year >= 2000   # block_time parsed, not 0->1970
    snaps = s.query(BalanceSnapshot).filter_by(
        exchange_account_id=acc.id, kind="SNAPSHOT").all()
    assert snaps and all(r.ts.year >= 2000 for r in snaps)    # no 1970 snapshot
