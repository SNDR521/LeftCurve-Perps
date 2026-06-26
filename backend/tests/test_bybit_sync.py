from datetime import datetime, timezone, timedelta
import pytest
from app.database import Base, make_engine
from sqlalchemy.orm import Session
from app.core.models import User
from app.core.security import hash_password, encrypt_credentials
from app.perps.models import ExchangeAccount, Fill, Position, Venue
from app.perps.services import bybit_sync


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'t.db'}")
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="a@b.c", password_hash=hash_password("x"))
    s.add(u); s.commit()
    acc = ExchangeAccount(user_id=u.id, venue=Venue.BYBIT, label="Bybit",
                          encrypted_credentials=encrypt_credentials({"api_key": "k", "api_secret": "s"}))
    s.add(acc); s.commit()
    yield s, u, acc
    s.close()


class FakeClient:
    def __init__(self, execs, funding): self._e, self._f = execs, funding
    def iter_executions(self, a, b): return iter(self._e)
    def iter_funding(self, a, b): return iter(self._f)
    def iter_closed_pnl(self, a, b): return iter([])
    def fetch_open_positions(self): return []
    def iter_transaction_log(self, a, b): return iter([])


def _exec(eid, side, price, qty, t):
    return {"execId": eid, "symbol": "BTCUSDT", "side": side, "execPrice": str(price),
            "execQty": str(qty), "execFee": "0.1", "feeCurrency": "USDT",
            "execTime": str(int(t.timestamp() * 1000)), "orderId": "o"}


def test_backfill_start_stays_inside_bybit_2y_limit(db, monkeypatch):
    # Bybit rejects execution/list startTime older than ~2 years (retCode 10001).
    # On a first sync (no cursor) the earliest window must stay inside that window.
    s, u, acc = db
    starts = []

    class RecordingClient:
        def iter_executions(self, a, b): starts.append(a); return iter([])
        def iter_funding(self, a, b): return iter([])
        def iter_closed_pnl(self, a, b): return iter([])
        def fetch_open_positions(self): return []
        def iter_transaction_log(self, a, b): return iter([])

    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: RecordingClient())
    bybit_sync.sync_account(s, acc)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    two_years_ms = 730 * 24 * 3600 * 1000
    assert starts, "expected at least one execution window"
    assert min(starts) > now_ms - two_years_ms     # within Bybit's 2-year limit
    assert min(starts) <= now_ms                    # not in the future


def test_sync_inserts_fills_funding_and_builds_position(db, monkeypatch):
    s, u, acc = db
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake = FakeClient(
        execs=[_exec("e1", "Buy", 100, 1, t0), _exec("e2", "Sell", 110, 1, t0 + timedelta(hours=2))],
        funding=[{"id": "f1", "symbol": "BTCUSDT", "change": "-0.5",
                  "transactionTime": str(int((t0 + timedelta(hours=1)).timestamp() * 1000))}],
    )
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    summary = bybit_sync.sync_account(s, acc)
    assert summary["fills_added"] == 2
    assert summary["funding_added"] == 1
    fills = s.query(Fill).filter(Fill.exchange_account_id == acc.id).all()
    assert len(fills) == 3                     # 2 execs + 1 funding fill
    # Closed positions now come from Bybit's closed-P&L, not fill-netting; the
    # FakeClient yields no closed-pnl records, so no closed position is built.
    assert s.query(Position).filter(Position.status == PositionStatus.CLOSED).count() == 0
    assert acc.sync_cursor is not None and acc.last_synced_at is not None


def test_sync_is_idempotent(db, monkeypatch):
    s, u, acc = db
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fake = FakeClient(execs=[_exec("e1", "Buy", 100, 1, t0)], funding=[])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    bybit_sync.sync_account(s, acc)
    acc.sync_cursor = None                     # force a re-scan of the same window
    s.commit()
    summary = bybit_sync.sync_account(s, acc)
    assert summary["fills_added"] == 0         # already present -> skipped
    assert s.query(Fill).filter(Fill.exchange_account_id == acc.id).count() == 1


def test_sync_writes_progress_running_to_ok(db, monkeypatch):
    s, u, acc = db
    from datetime import datetime as _dt, timezone as _tz
    t0 = _dt(2026, 1, 1, tzinfo=_tz.utc)
    fake = FakeClient(execs=[_exec("e1", "Buy", 100, 1, t0)], funding=[])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    bybit_sync.sync_account(s, acc)
    p = acc.sync_progress
    assert p is not None
    assert p["state"] == "ok"
    assert p["fills"] == 1 and p["funding"] == 0
    assert p["windows_done"] == p["windows_total"]
    assert p["cursor_ms"] == p["to_ms"]


def test_sync_progress_error_state(db, monkeypatch):
    s, u, acc = db
    class Boom:
        def iter_executions(self, a, b): raise RuntimeError("nope")
        def iter_funding(self, a, b): return iter([])
        def iter_transaction_log(self, a, b): return iter([])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: Boom())
    out = bybit_sync.sync_account(s, acc)
    assert out["error"]
    assert acc.sync_progress["state"] == "error"


def test_sync_dedups_duplicate_ids_within_a_window(db, monkeypatch):
    # Bybit can return the same id twice in one window (overlapping pages). Two rows
    # with the same external_fill_id in one commit would violate the unique index and
    # abort the window — the sync must dedup within the batch.
    s, u, acc = db
    from datetime import datetime as _dt, timezone as _tz
    t0 = _dt(2026, 1, 1, tzinfo=_tz.utc)
    fake = FakeClient(execs=[_exec("dup", "Buy", 100, 1, t0), _exec("dup", "Buy", 100, 1, t0)], funding=[])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    out = bybit_sync.sync_account(s, acc)
    assert out["error"] is None
    assert s.query(Fill).filter(Fill.exchange_account_id == acc.id).count() == 1
    assert acc.sync_progress["state"] == "ok"


from app.perps.models import Position, PositionStatus, Direction


class FakeClientCPnl:
    def __init__(self, closed=None, openpos=None):
        self._closed = closed or []
        self._open = openpos or []
    def iter_executions(self, a, b): return iter([])
    def iter_funding(self, a, b): return iter([])
    def iter_closed_pnl(self, a, b): return iter(self._closed)
    def fetch_open_positions(self): return list(self._open)
    def iter_transaction_log(self, a, b): return iter([])


def _cpnl(order_id, side, entry, exit_, qty, pnl, t):
    return {"symbol": "BTCUSDT", "orderId": order_id, "side": side,
            "avgEntryPrice": str(entry), "avgExitPrice": str(exit_),
            "closedSize": str(qty), "closedPnl": str(pnl),
            "openFee": "0.1", "closeFee": "0.2",
            "createdTime": str(int(t.timestamp() * 1000)),
            "updatedTime": str(int(t.timestamp() * 1000))}


def test_sync_builds_closed_position_from_closed_pnl(db, monkeypatch):
    from datetime import datetime as _dt, timezone as _tz
    s, u, acc = db
    t0 = _dt(2026, 1, 5, tzinfo=_tz.utc)
    fake = FakeClientCPnl(closed=[_cpnl("o1", "Sell", 100, 110, 2, 20.0, t0)])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    bybit_sync.sync_account(s, acc)
    pos = s.query(Position).filter(Position.status == PositionStatus.CLOSED).one()
    assert pos.direction == Direction.LONG          # closing Sell => was LONG
    assert pos.avg_entry == 100 and pos.avg_exit == 110 and pos.quantity == 2
    assert pos.realized_pnl == 20.0                 # closedPnl verbatim, no double fee subtraction
    assert round(pos.total_fees, 6) == 0.3
    assert pos.total_funding == 0.0
    assert pos.position_key == f"{acc.id}:BTCUSDT:cpnl:o1"


def test_sync_closed_pnl_is_idempotent(db, monkeypatch):
    from datetime import datetime as _dt, timezone as _tz
    s, u, acc = db
    t0 = _dt(2026, 1, 5, tzinfo=_tz.utc)
    fake = FakeClientCPnl(closed=[_cpnl("o1", "Buy", 100, 90, 1, 10.0, t0)])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    bybit_sync.sync_account(s, acc)
    acc.sync_cursor = None; s.commit()
    bybit_sync.sync_account(s, acc)
    assert s.query(Position).filter(Position.status == PositionStatus.CLOSED).count() == 1


def test_sync_cleans_up_legacy_fill_netted_positions(db, monkeypatch):
    s, u, acc = db
    from datetime import datetime as _dt, timezone as _tz
    from app.perps.models import AssetClass
    s.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="OLDUSDT",
                   asset_class=AssetClass.PERP, direction=Direction.SHORT, status=PositionStatus.CLOSED,
                   opened_at=_dt(2025, 1, 1, tzinfo=_tz.utc), closed_at=_dt(2025, 1, 2, tzinfo=_tz.utc),
                   avg_entry=1, avg_exit=1, quantity=1, realized_pnl=999, total_fees=0, total_funding=0,
                   position_key=f"{acc.id}:OLDUSDT:2025-01-01T00:00:00+00:00"))
    s.commit()
    fake = FakeClientCPnl(closed=[])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    bybit_sync.sync_account(s, acc)
    assert s.query(Position).filter(Position.symbol == "OLDUSDT").count() == 0  # legacy purged


def test_sync_open_snapshot_replaces(db, monkeypatch):
    s, u, acc = db
    from datetime import datetime as _dt, timezone as _tz
    from app.perps.models import AssetClass
    s.add(Position(user_id=u.id, exchange_account_id=acc.id, symbol="STALEUSDT",
                   asset_class=AssetClass.PERP, direction=Direction.LONG, status=PositionStatus.OPEN,
                   opened_at=_dt(2026, 1, 1, tzinfo=_tz.utc), closed_at=None,
                   avg_entry=1, avg_exit=None, quantity=5, realized_pnl=0, total_fees=0, total_funding=0,
                   position_key=f"{acc.id}:STALEUSDT:open"))
    s.commit()
    fake = FakeClientCPnl(openpos=[{"symbol": "SOLUSDT", "side": "Buy", "size": "3", "avgPrice": "150",
                                    "createdTime": "1767225600000"}])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    bybit_sync.sync_account(s, acc)
    opens = s.query(Position).filter(Position.status == PositionStatus.OPEN).all()
    assert [p.symbol for p in opens] == ["SOLUSDT"]              # stale replaced by snapshot
    assert opens[0].direction == Direction.LONG and opens[0].quantity == 3


def test_sync_runs_linker_and_links_closed_pnl_position(db, monkeypatch):
    from app.perps.models import PositionFill, OpenedAtSource
    s, u, acc = db
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(hours=2)

    class LinkedClient(FakeClient):
        def iter_closed_pnl(self, a, b):
            return iter([{
                "symbol": "BTCUSDT", "side": "Sell", "orderId": "oclose",
                "avgEntryPrice": "100", "avgExitPrice": "110", "closedSize": "1",
                "closedPnl": "9.8", "openFee": "0.1", "closeFee": "0.1",
                "createdTime": str(int(t0.timestamp() * 1000)),
                "updatedTime": str(int(t1.timestamp() * 1000)),
            }])

    e1 = _exec("e1", "Buy", 100, 1, t0)
    e2 = {**_exec("e2", "Sell", 110, 1, t1), "orderId": "oclose"}
    fake = LinkedClient(execs=[e1, e2], funding=[])
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: fake)
    # avoid live kline calls in tests
    monkeypatch.setattr("app.perps.services.mfe.fetch_klines", lambda *a, **k: [])

    bybit_sync.sync_account(s, acc)

    pos = s.query(Position).filter(Position.status == PositionStatus.CLOSED).one()
    assert pos.opened_at_source == OpenedAtSource.EXACT
    assert pos.duration_seconds == 2 * 3600
    assert s.query(PositionFill).filter_by(position_id=pos.id).count() == 2
