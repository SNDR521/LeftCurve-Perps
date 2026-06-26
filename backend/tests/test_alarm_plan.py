import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.alarms.models import Alarm
from app.alarms.engine.positions import evaluate_plan_alarms


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


def _plan_alarm(db, condition):
    a = Alarm(user_id=1, target_type="PLAN", market="CRYPTO", condition=condition,
              trigger_mode="EVERY", deliver={"in_app": True}, status="ACTIVE", enabled=True)
    db.add(a); db.commit(); db.refresh(a); return a


def test_plan_loss_limit_fires_once_per_day(db_session):
    _plan_alarm(db_session, "PLAN_LOSS_LIMIT")
    plan = {"date": "2026-06-18", "loss_breached": True, "trades_over": False, "realized": -500}
    assert len(evaluate_plan_alarms(db_session, {1: plan})) == 1
    assert evaluate_plan_alarms(db_session, {1: plan}) == []
    plan2 = dict(plan, date="2026-06-19")
    assert len(evaluate_plan_alarms(db_session, {1: plan2})) == 1


def test_plan_max_trades_only_when_over(db_session):
    _plan_alarm(db_session, "PLAN_MAX_TRADES")
    assert evaluate_plan_alarms(db_session, {1: {"date": "d", "trades_over": False}}) == []
    assert len(evaluate_plan_alarms(db_session, {1: {"date": "d", "trades_over": True}})) == 1


def test_plan_alarm_no_plan_ctx_noop(db_session):
    _plan_alarm(db_session, "PLAN_LOSS_LIMIT")
    assert evaluate_plan_alarms(db_session, {}) == []

def test_snoozed_plan_alarm_skipped(db_session):
    from datetime import datetime, timezone, timedelta
    from app.alarms.models import Alarm
    from app.alarms.engine.positions import evaluate_plan_alarms
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    a = Alarm(user_id=1, target_type="PLAN", market="CRYPTO", condition="PLAN_LOSS_LIMIT",
              trigger_mode="EVERY", deliver={"in_app": True}, status="ACTIVE", enabled=True,
              snoozed_until=future)
    db_session.add(a); db_session.commit()
    assert evaluate_plan_alarms(db_session, {1: {"date": "d", "loss_breached": True}}) == []
