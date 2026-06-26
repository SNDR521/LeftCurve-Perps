import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.perps.models import ExchangeAccount, Venue, PerpsJournal
from app.alarms.engine import positions as pos


class FakeHLCockpitClient:
    """Bybit-shaped client build_cockpit consumes — stands in for a HL client."""
    _client = type("C", (), {"close": lambda self: None})()

    def fetch_open_positions(self):
        return [{"symbol": "BTC", "side": "Buy", "size": "0.5", "avgPrice": "60000",
                 "leverage": "5", "liqPrice": "50000", "unrealisedPnl": "100",
                 "stopLoss": None, "tradeMode": 0}]

    def fetch_tickers(self, symbols=None):
        return {"BTC": {"mark_price": 60500.0, "funding_rate": 0.0, "next_funding_time": 0}}

    def fetch_wallet_balance(self):
        return {"equity": 10000.0, "balance": 10000.0, "available": 8000.0}


@pytest.fixture()
def db_session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    import app.core.models  # noqa: F401
    import app.perps.models  # noqa: F401
    import app.workflow.models  # noqa: F401
    import app.alarms.models  # noqa: F401
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="hl@test.com", password_hash=hash_password("x"))
    s.add(u); s.commit(); s.refresh(u)
    s.add(ExchangeAccount(user_id=u.id, venue=Venue.HYPERLIQUID, label="HL",
                          encrypted_credentials="enc", is_active=True))
    s.add(PerpsJournal(user_id=u.id, position_key="1:BTC:open", stop_price=58000.0))
    from app.alarms.models import Alarm
    s.add(Alarm(user_id=u.id, target_type="POSITION", market="CRYPTO", symbol="BTC",
                condition="UPNL", value=50.0, trigger_mode="ONCE",
                deliver={"in_app": True}, status="ACTIVE", enabled=True))
    s.commit()
    yield s
    s.close()


def test_refresh_populates_hl_position_context(db_session, monkeypatch):
    monkeypatch.setattr(pos, "_POSITION_CTX", {})
    from app.perps.services import venue_sync
    monkeypatch.setattr(venue_sync, "client_for", lambda account: FakeHLCockpitClient())
    pos.refresh(db_session)
    ctx = pos.get_position_ctx()
    assert (1, "BTC") in ctx
    entry = ctx[(1, "BTC")]
    assert entry["direction"] == "LONG"
    assert entry["entry"] == 60000.0 and entry["qty"] == 0.5
    assert entry["stop"] == 58000.0          # from the journal stop
    assert entry["liq"] == 50000.0
    assert entry["risk_usd"] is not None
