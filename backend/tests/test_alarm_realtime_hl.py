import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.alarms.models import Alarm
from app.alarms.engine import realtime_hl
from app.alarms.engine import positions as pos


def test_parse_mids_reads_allmids_frame():
    msg = {"channel": "allMids", "data": {"mids": {"BTC": "60000.0", "ETH": "3000.5"}}}
    assert realtime_hl._parse_mids(msg) == {"BTC": 60000.0, "ETH": 3000.5}


def test_parse_mids_ignores_other_channels():
    assert realtime_hl._parse_mids({"channel": "pong"}) == {}
    assert realtime_hl._parse_mids({"channel": "subscriptionResponse"}) == {}


def test_scope_prices_keeps_only_position_symbols():
    mids = {"BTC": 60000.0, "ETH": 3000.0, "SOL": 150.0}
    ctx = {(1, "BTC"): {}, (2, "ETH"): {}}   # SOL not held by anyone
    assert realtime_hl._scope_prices(mids, ctx) == {"BTC": 60000.0, "ETH": 3000.0}


@pytest.fixture()
def app_db(monkeypatch):
    engine = make_engine("sqlite:///:memory:")
    import app.core.models  # noqa: F401
    import app.perps.models  # noqa: F401
    import app.workflow.models  # noqa: F401
    import app.alarms.models  # noqa: F401
    Base.metadata.create_all(engine)
    monkeypatch.setattr(realtime_hl, "SessionLocal", lambda: Session(engine))
    s = Session(engine)
    u = User(email="hlrt@test.com", password_hash=hash_password("x"))
    s.add(u); s.commit(); s.refresh(u)
    yield s, u
    s.close()


def test_flush_fires_hl_position_upnl_alarm(app_db, monkeypatch):
    s, u = app_db
    a = Alarm(user_id=u.id, target_type="POSITION", market="CRYPTO", symbol="BTC",
              condition="UPNL", value=100.0, trigger_mode="ONCE",
              deliver={"in_app": True}, status="ACTIVE", enabled=True, last_price=60000.0)
    s.add(a); s.commit()
    monkeypatch.setattr(pos, "_POSITION_CTX",
                        {(u.id, "BTC"): {"direction": "LONG", "entry": 60000.0,
                                         "qty": 1.0, "stop": None, "liq": None,
                                         "risk_usd": None}})
    # price 60100 -> uPnL = +100 -> crosses the +100 threshold from prev 60000 (uPnL 0)
    realtime_hl._flush({"BTC": 60100.0})
    from app.workflow.models import Alert
    s2 = Session(s.get_bind())
    assert s2.query(Alert).filter(Alert.kind == "ALARM").count() == 1
    s2.close()
