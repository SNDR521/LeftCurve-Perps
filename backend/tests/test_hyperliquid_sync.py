from datetime import datetime, timezone

from app.database import SessionLocal
from app.core.models import User
from app.perps.models import ExchangeAccount, Venue, Fill, Position, PositionStatus
from app.perps.services import hyperliquid_sync


class FakeHL:
    """Fake HyperliquidClient: serves fills/funding for any window, plus an open snapshot."""
    def __init__(self, fills, funding=None, open_positions=None):
        self._fills = fills
        self._funding = funding or []
        self._open = open_positions or []
        self.closed = False

    def iter_fills_by_time(self, start_ms, end_ms):
        for fl in self._fills:
            if start_ms <= int(fl["time"]) < end_ms:
                yield fl

    def iter_funding(self, start_ms, end_ms):
        for fn in self._funding:
            if start_ms <= int(fn["time"]) < end_ms:
                yield fn

    def fetch_open_positions(self):
        return self._open

    def close(self):
        self.closed = True


def _fill(time, side, sz, px, start, closed="0", coin="ETH", h=None):
    return {"coin": coin, "side": side, "sz": str(sz), "px": str(px), "time": time,
            "startPosition": str(start), "closedPnl": str(closed), "fee": "0.1",
            "hash": h or f"h{time}", "oid": time, "tid": time, "dir": ""}


def _setup_account(db):
    user = db.query(User).first()
    if user is None:
        user = User(email="hl@test.dev", password_hash="x")
        db.add(user); db.commit(); db.refresh(user)
    acc = ExchangeAccount(user_id=user.id, venue=Venue.HYPERLIQUID, label="HL",
                          encrypted_credentials="enc", sync_cursor=None)
    db.add(acc); db.commit(); db.refresh(acc)
    return acc


def test_sync_imports_fills_and_builds_closed_position(monkeypatch):
    db = SessionLocal()
    try:
        acc = _setup_account(db)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        client = FakeHL(fills=[
            _fill(now - 5000, "B", 1, 100, start=0),
            _fill(now - 4000, "A", 1, 110, start=1, closed=10),
        ])
        monkeypatch.setattr(hyperliquid_sync, "_client_for", lambda account: client)
        summary = hyperliquid_sync.sync_account(db, acc)
        assert summary["fills_added"] == 2
        assert summary["error"] is None
        closed = db.query(Position).filter(
            Position.exchange_account_id == acc.id,
            Position.status == PositionStatus.CLOSED).all()
        assert len(closed) == 1
        assert closed[0].realized_pnl == 10.0
    finally:
        db.close()


def test_sync_links_fills_to_closed_position(monkeypatch):
    """The trade-detail chart renders entry/exit markers from PositionFill links;
    the HL sync must create them (regression: it previously created none → no markers)."""
    from app.perps.models import PositionFill
    db = SessionLocal()
    try:
        acc = _setup_account(db)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        client = FakeHL(fills=[
            _fill(now - 5000, "B", 1, 100, start=0, h="hopen"),
            _fill(now - 4000, "A", 1, 110, start=1, closed=10, h="hclose"),
        ])
        monkeypatch.setattr(hyperliquid_sync, "_client_for", lambda account: client)
        hyperliquid_sync.sync_account(db, acc)
        closed = db.query(Position).filter(
            Position.exchange_account_id == acc.id,
            Position.status == PositionStatus.CLOSED).one()
        # the exact join /positions/{id}/detail uses → the chart's executions
        fills = (db.query(Fill).join(PositionFill, PositionFill.fill_id == Fill.id)
                 .filter(PositionFill.position_id == closed.id).all())
        assert {f.external_fill_id for f in fills} == {"hopen", "hclose"}

        # Real syncs run on a fresh session; this test reuses one and loaded the
        # position above, so detach it before the re-sync to avoid a benign
        # identity-map collision when SQLite reuses the deleted position's pk.
        db.expunge_all()
        acc.sync_cursor = None; db.commit()  # full re-scan must not duplicate links
        hyperliquid_sync.sync_account(db, acc)
        closed2 = db.query(Position).filter(
            Position.exchange_account_id == acc.id,
            Position.status == PositionStatus.CLOSED).one()
        assert db.query(PositionFill).filter(PositionFill.position_id == closed2.id).count() == 2
    finally:
        db.close()


def test_sync_attributes_funding_to_closed_position(monkeypatch):
    """Funding settled while a position was open is summed into total_funding and
    linked (chart funding tick); funding outside the window is not attributed."""
    from app.perps.models import PositionFill
    db = SessionLocal()
    try:
        acc = _setup_account(db)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        client = FakeHL(
            fills=[
                _fill(now - 10000, "B", 1, 100, start=0, h="hopen"),
                _fill(now - 4000, "A", 1, 110, start=1, closed=10, h="hclose"),
            ],
            funding=[
                {"time": now - 7000, "hash": "fin", "delta": {"coin": "ETH", "usdc": "-0.5"}},   # in window
                {"time": now - 1000, "hash": "fout", "delta": {"coin": "ETH", "usdc": "-9.0"}},  # after close
            ],
        )
        monkeypatch.setattr(hyperliquid_sync, "_client_for", lambda account: client)
        monkeypatch.setattr("app.perps.services.mfe.fetch_hl_klines", lambda *a, **k: [])  # no live candles
        hyperliquid_sync.sync_account(db, acc)
        closed = db.query(Position).filter(
            Position.exchange_account_id == acc.id,
            Position.status == PositionStatus.CLOSED).one()
        assert closed.total_funding == -0.5    # only the in-window funding
        linked = {f.external_fill_id for f in
                  db.query(Fill).join(PositionFill, PositionFill.fill_id == Fill.id)
                  .filter(PositionFill.position_id == closed.id).all()}
        assert "funding:fin" in linked and "funding:fout" not in linked
    finally:
        db.close()


def test_sync_computes_mfe_via_hl_candles_and_carries_forward(monkeypatch):
    db = SessionLocal()
    try:
        acc = _setup_account(db)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        client = FakeHL(fills=[
            _fill(now - 5000, "B", 1, 100, start=0, h="o"),
            _fill(now - 4000, "A", 1, 110, start=1, closed=10, h="c"),
        ])
        monkeypatch.setattr(hyperliquid_sync, "_client_for", lambda account: client)
        calls = {"hl": 0}
        def fake_hl(symbol, interval, s, e, client=None):
            calls["hl"] += 1
            assert symbol == "ETH"   # HL coin, via the HL candle source
            return [{"time": (now - 5000) // 1000, "open": 100, "high": 120,
                     "low": 95, "close": 110, "volume": 1}]
        monkeypatch.setattr("app.perps.services.mfe.fetch_hl_klines", fake_hl)
        monkeypatch.setattr("app.perps.services.mfe.fetch_klines",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("Bybit fetch used for HL")))
        hyperliquid_sync.sync_account(db, acc)
        closed = db.query(Position).filter(
            Position.exchange_account_id == acc.id,
            Position.status == PositionStatus.CLOSED).one()
        # LONG entry 100: mfe = 120-100 = 20, mae = 100-95 = 5 (× qty 1)
        assert closed.mfe_usd == 20.0 and closed.mae_usd == 5.0
        assert calls["hl"] == 1

        # carry-forward: a re-sync (full re-scan) must NOT recompute MFE
        db.expunge_all(); acc.sync_cursor = None; db.commit()
        hyperliquid_sync.sync_account(db, acc)
        assert calls["hl"] == 1   # not 2 — MFE carried forward by position_key
        closed2 = db.query(Position).filter(
            Position.exchange_account_id == acc.id,
            Position.status == PositionStatus.CLOSED).one()
        assert closed2.mfe_usd == 20.0
    finally:
        db.close()


def test_resync_is_idempotent(monkeypatch):
    db = SessionLocal()
    try:
        acc = _setup_account(db)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        client = FakeHL(fills=[
            _fill(now - 5000, "B", 1, 100, start=0),
            _fill(now - 4000, "A", 1, 110, start=1, closed=10),
        ])
        monkeypatch.setattr(hyperliquid_sync, "_client_for", lambda account: client)
        hyperliquid_sync.sync_account(db, acc)
        acc.sync_cursor = None  # force a full re-scan
        db.commit()
        hyperliquid_sync.sync_account(db, acc)
        assert db.query(Fill).filter(Fill.exchange_account_id == acc.id).count() == 2
        assert db.query(Position).filter(
            Position.exchange_account_id == acc.id,
            Position.status == PositionStatus.CLOSED).count() == 1
    finally:
        db.close()


def test_open_snapshot_written(monkeypatch):
    db = SessionLocal()
    try:
        acc = _setup_account(db)
        client = FakeHL(fills=[], open_positions=[
            {"symbol": "BTC", "side": "Buy", "size": 0.5, "avgPrice": 60000.0,
             "leverage": 10.0, "liqPrice": 50000.0, "stopLoss": None, "tradeMode": 0},
        ])
        monkeypatch.setattr(hyperliquid_sync, "_client_for", lambda account: client)
        hyperliquid_sync.sync_account(db, acc)
        openp = db.query(Position).filter(
            Position.exchange_account_id == acc.id,
            Position.status == PositionStatus.OPEN).all()
        assert len(openp) == 1 and openp[0].symbol == "BTC"
        assert openp[0].direction.name == "LONG" and openp[0].quantity == 0.5
    finally:
        db.close()
