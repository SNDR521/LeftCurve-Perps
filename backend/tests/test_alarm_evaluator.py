import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.alarms.models import Alarm
from app.alarms.engine.evaluator import evaluate_ticks


@pytest.fixture()
def db_session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 't.db'}")
    import app.core.models  # noqa: F401
    import app.perps.models  # noqa: F401
    import app.workflow.models  # noqa: F401
    import app.alarms.models  # noqa: F401
    Base.metadata.create_all(engine)
    s = Session(engine)
    u = User(email="trader@test.com", password_hash=hash_password("x"))
    s.add(u)
    s.commit()
    yield s
    s.close()


def _mk(db, user_id=1, **kw):
    a = Alarm(user_id=user_id, target_type="SYMBOL", market="CRYPTO",
              condition=kw.pop("condition", "CROSS_UP"), value=kw.pop("value", 100),
              symbol=kw.pop("symbol", "BTCUSDT"), trigger_mode=kw.pop("trigger_mode", "ONCE"),
              deliver={"in_app": True}, status="ACTIVE", enabled=True, **kw)
    db.add(a); db.commit(); db.refresh(a); return a


def test_first_tick_records_price_no_fire(db_session):
    a = _mk(db_session, condition="CROSS_UP", value=100)
    fired = evaluate_ticks(db_session, {"BTCUSDT": 99})
    assert fired == []
    db_session.refresh(a); assert a.last_price == 99 and a.status == "ACTIVE"

def test_once_fires_then_pauses(db_session):
    a = _mk(db_session, condition="CROSS_UP", value=100, trigger_mode="ONCE")
    evaluate_ticks(db_session, {"BTCUSDT": 99})
    fired = evaluate_ticks(db_session, {"BTCUSDT": 101})
    assert len(fired) == 1
    db_session.refresh(a)
    assert a.status == "TRIGGERED" and a.enabled is False and a.fired_count == 1
    assert evaluate_ticks(db_session, {"BTCUSDT": 102}) == []

def test_every_refires_after_rearm(db_session):
    a = _mk(db_session, condition="CROSS", value=100, trigger_mode="EVERY")
    evaluate_ticks(db_session, {"BTCUSDT": 99})
    assert len(evaluate_ticks(db_session, {"BTCUSDT": 101})) == 1
    assert len(evaluate_ticks(db_session, {"BTCUSDT": 99})) == 1
    db_session.refresh(a); assert a.status == "ACTIVE" and a.fired_count == 2

def test_expired_alarm_skipped(db_session):
    from datetime import datetime, timedelta, timezone
    a = _mk(db_session, condition="CROSS_UP", value=100,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1))
    evaluate_ticks(db_session, {"BTCUSDT": 99})
    assert evaluate_ticks(db_session, {"BTCUSDT": 101}) == []
    db_session.refresh(a); assert a.status == "EXPIRED"

def test_disabled_alarm_ignored(db_session):
    a = _mk(db_session, condition="CROSS_UP", value=100); a.enabled = False; db_session.commit()
    assert evaluate_ticks(db_session, {"BTCUSDT": 101}) == []

def test_telegram_only_alarm_still_fires_alert(db_session):
    from app.alarms.models import Alarm
    from app.alarms.engine.evaluator import evaluate_ticks
    a = Alarm(user_id=1, target_type="SYMBOL", market="CRYPTO", condition="CROSS_UP",
              value=100, symbol="BTCUSDT", trigger_mode="ONCE",
              deliver={"in_app": False, "telegram": True}, status="ACTIVE", enabled=True)
    db_session.add(a); db_session.commit()
    evaluate_ticks(db_session, {"BTCUSDT": 99})       # seed
    fired = evaluate_ticks(db_session, {"BTCUSDT": 101})  # cross up
    assert len(fired) == 1
    assert fired[0].payload["telegram"] is True and fired[0].payload["in_app"] is False



def test_position_upnl_alarm_fires_with_ctx(db_session):
    from app.alarms.models import Alarm
    from app.alarms.engine.evaluator import evaluate_ticks
    a = Alarm(user_id=1, target_type="POSITION", market="CRYPTO", condition="UPNL",
              value=-150, params={"unit": "USD"}, symbol="BTCUSDT", trigger_mode="ONCE",
              deliver={"in_app": True}, status="ACTIVE", enabled=True)
    db_session.add(a); db_session.commit()
    pos = {(1, "BTCUSDT"): {"direction": "LONG", "entry": 100.0, "qty": 2.0,
                            "stop": 90.0, "liq": 80.0, "risk_usd": 20.0}}
    evaluate_ticks(db_session, {"BTCUSDT": 30}, position_ctx=pos)
    fired = evaluate_ticks(db_session, {"BTCUSDT": 24}, position_ctx=pos)
    assert len(fired) == 1
    db_session.refresh(a); assert a.status == "TRIGGERED"

def test_position_alarm_without_ctx_does_not_fire(db_session):
    from app.alarms.models import Alarm
    from app.alarms.engine.evaluator import evaluate_ticks
    a = Alarm(user_id=1, target_type="POSITION", market="CRYPTO", condition="LIQ_DIST",
              value=5, symbol="ETHUSDT", trigger_mode="EVERY", deliver={"in_app": True},
              status="ACTIVE", enabled=True)
    db_session.add(a); db_session.commit()
    evaluate_ticks(db_session, {"ETHUSDT": 100}, position_ctx={})
    assert evaluate_ticks(db_session, {"ETHUSDT": 80}, position_ctx={}) == []

def test_snoozed_alarm_does_not_fire(db_session):
    from datetime import datetime, timezone, timedelta
    from app.alarms.models import Alarm
    from app.alarms.engine.evaluator import evaluate_ticks
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    a = Alarm(user_id=1, target_type="SYMBOL", market="CRYPTO", condition="CROSS_UP",
              value=100, symbol="BTCUSDT", trigger_mode="EVERY", deliver={"in_app": True},
              status="ACTIVE", enabled=True, snoozed_until=future)
    db_session.add(a); db_session.commit()
    evaluate_ticks(db_session, {"BTCUSDT": 99})
    assert evaluate_ticks(db_session, {"BTCUSDT": 101}) == []

def test_expired_snooze_fires_again(db_session):
    from datetime import datetime, timezone, timedelta
    from app.alarms.models import Alarm
    from app.alarms.engine.evaluator import evaluate_ticks
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1)
    a = Alarm(user_id=1, target_type="SYMBOL", market="CRYPTO", condition="CROSS_UP",
              value=100, symbol="ETHUSDT", trigger_mode="ONCE", deliver={"in_app": True},
              status="ACTIVE", enabled=True, snoozed_until=past)
    db_session.add(a); db_session.commit()
    evaluate_ticks(db_session, {"ETHUSDT": 99})
    assert len(evaluate_ticks(db_session, {"ETHUSDT": 101})) == 1

