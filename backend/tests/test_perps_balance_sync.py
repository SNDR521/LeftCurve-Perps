"""Tests for the balance-snapshot pass (balance_sync.py) and its wiring in bybit_sync."""
import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password, encrypt_credentials
from app.perps.models import ExchangeAccount, Venue, BalanceSnapshot
from app.perps.services.balance_sync import snapshot_window
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


def _row(t_ms, bal, kind="TRADE", change="0"):
    return {"type": kind, "transactionTime": str(t_ms), "cashBalance": str(bal), "change": change}


D1 = 1767225600000   # 2026-01-01 00:00 UTC
H = 3600 * 1000


def test_snapshot_daily_last_per_day(db):
    s, u, acc = db
    rows = [_row(D1 + 1 * H, 1000), _row(D1 + 5 * H, 1050),      # day 1 -> last 1050
            _row(D1 + 25 * H, 1100)]                              # day 2 -> 1100
    n = snapshot_window(s, acc, rows)
    snaps = s.query(BalanceSnapshot).filter_by(kind="SNAPSHOT").order_by(BalanceSnapshot.ts).all()
    assert [sn.balance for sn in snaps] == [1050.0, 1100.0]
    assert all(sn.ts.hour == 0 and sn.ts.minute == 0 for sn in snaps)
    assert n == 2


def test_transfers_recorded_at_event_time(db):
    s, u, acc = db
    rows = [_row(D1 + 2 * H, 1500, kind="TRANSFER_IN", change="500")]
    snapshot_window(s, acc, rows)
    tr = s.query(BalanceSnapshot).filter_by(kind="TRANSFER_IN").one()
    assert tr.balance == 1500.0
    assert tr.ts.hour == 2
    # the transfer's cashBalance also feeds the daily snapshot
    assert s.query(BalanceSnapshot).filter_by(kind="SNAPSHOT").one().balance == 1500.0


def test_idempotent_and_replaces_balance(db):
    s, u, acc = db
    snapshot_window(s, acc, [_row(D1 + 1 * H, 1000)])
    snapshot_window(s, acc, [_row(D1 + 6 * H, 1234)])   # later event same day
    snaps = s.query(BalanceSnapshot).filter_by(kind="SNAPSHOT").all()
    assert len(snaps) == 1 and snaps[0].balance == 1234.0
    snapshot_window(s, acc, [_row(D1 + 6 * H, 1234)])   # exact rerun
    assert s.query(BalanceSnapshot).count() == 1


def test_rows_without_cash_balance_skipped(db):
    s, u, acc = db
    n = snapshot_window(s, acc, [{"type": "TRADE", "transactionTime": str(D1), "cashBalance": ""}])
    assert n == 0 and s.query(BalanceSnapshot).count() == 0


# ---------------------------------------------------------------------------
# Sync-wiring tests
# ---------------------------------------------------------------------------

class _FakeClientWithTxLog:
    """Returns one transaction-log row per window — verifies balance_rows is counted."""
    def __init__(self):
        self._call_count = 0

    def iter_executions(self, a, b): return iter([])
    def iter_funding(self, a, b): return iter([])
    def iter_closed_pnl(self, a, b): return iter([])
    def fetch_open_positions(self): return []

    def iter_transaction_log(self, a, b):
        # Return one SNAPSHOT-eligible row per window
        yield {"type": "TRADE", "transactionTime": str(a + 1000), "cashBalance": "9999", "change": "0"}


class _FakeClientTxLogRaises:
    """iter_transaction_log raises — sync must still complete without error."""
    def iter_executions(self, a, b): return iter([])
    def iter_funding(self, a, b): return iter([])
    def iter_closed_pnl(self, a, b): return iter([])
    def fetch_open_positions(self): return []

    def iter_transaction_log(self, a, b):
        raise RuntimeError("tx log boom")


def test_sync_wiring_balance_rows_counted(db, monkeypatch):
    s, u, acc = db
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: _FakeClientWithTxLog())
    summary = bybit_sync.sync_account(s, acc)
    assert summary["error"] is None
    assert summary.get("balance_rows", 0) >= 1
    assert s.query(BalanceSnapshot).count() >= 1


def test_sync_wiring_balance_failure_isolated(db, monkeypatch):
    s, u, acc = db
    monkeypatch.setattr(bybit_sync, "_client_for", lambda account: _FakeClientTxLogRaises())
    summary = bybit_sync.sync_account(s, acc)
    # transaction-log failure must NOT propagate as a sync error
    assert summary["error"] is None
