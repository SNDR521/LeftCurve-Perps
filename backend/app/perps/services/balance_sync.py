"""Daily balance snapshots + transfer events from Bybit's transaction log."""
from __future__ import annotations

from datetime import datetime, timezone

from app.perps.models import BalanceSnapshot

_TRANSFERS = {"TRANSFER_IN", "TRANSFER_OUT"}


def _upsert(db, account, ts, balance, kind):
    row = (db.query(BalanceSnapshot)
           .filter(BalanceSnapshot.exchange_account_id == account.id,
                   BalanceSnapshot.ts == ts,
                   BalanceSnapshot.kind == kind).first())
    if row is None:
        db.add(BalanceSnapshot(user_id=account.user_id, exchange_account_id=account.id,
                               ts=ts, balance=balance, kind=kind))
    else:
        row.balance = balance


def snapshot_window(db, account, rows) -> int:
    """Process one window of transaction-log rows (any types): record every
    transfer at its event time and the LAST cashBalance per UTC day."""
    daily_last: dict = {}   # day(naive midnight) -> (transactionTime ms, balance)
    n = 0
    for r in rows:
        bal = r.get("cashBalance")
        if bal in (None, ""):
            continue
        t_ms = int(r.get("transactionTime") or 0)
        when = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        kind = str(r.get("type") or "")
        if kind in _TRANSFERS:
            _upsert(db, account, when, float(bal), kind)
            n += 1
        day = when.replace(hour=0, minute=0, second=0, microsecond=0)
        prev = daily_last.get(day)
        if prev is None or t_ms >= prev[0]:
            daily_last[day] = (t_ms, float(bal))
    for day, (_, bal) in daily_last.items():
        _upsert(db, account, day, bal, "SNAPSHOT")
        n += 1
    db.commit()
    return n
