import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.alarms.models import Alarm
from app.alarms.engine import realtime


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    import app.core.models  # noqa: F401
    import app.perps.models  # noqa: F401
    import app.workflow.models  # noqa: F401
    import app.alarms.models  # noqa: F401
    Base.metadata.create_all(engine)
    s = Session(engine)
    s.add(User(email="rt@test.com", password_hash=hash_password("x")))
    s.commit()
    # _active_symbols opens its own SessionLocal — point it at this engine
    monkeypatch.setattr(realtime, "SessionLocal", lambda: Session(engine))
    yield s
    s.close()


def _alarm(db, symbol, target_type="SYMBOL", condition="CROSS"):
    a = Alarm(user_id=1, target_type=target_type, market="CRYPTO", symbol=symbol,
              condition=condition, value=1.0, trigger_mode="ONCE",
              deliver={"in_app": True}, status="ACTIVE", enabled=True)
    db.add(a); db.commit()


def test_active_symbols_excludes_bare_hl_coins(db_session):
    _alarm(db_session, "BTCUSDT")
    _alarm(db_session, "ETHUSDT")
    _alarm(db_session, "BTC", target_type="POSITION", condition="UPNL")  # HL bare coin
    syms = realtime._active_symbols()
    assert "BTCUSDT" in syms and "ETHUSDT" in syms
    assert "BTC" not in syms
