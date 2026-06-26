import pytest
from sqlalchemy.orm import Session
from datetime import timedelta

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password
from app.alarms.models import Alarm, TelegramLink
from app.alarms.telegram.commands import handle_command, parse_duration


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


def _link(db, chat_id="555", user_id=1):
    db.add(TelegramLink(user_id=user_id, chat_id=chat_id)); db.commit()

def _alarm(db, user_id=1, **kw):
    a = Alarm(user_id=user_id, target_type="SYMBOL", market="CRYPTO",
              condition=kw.pop("condition", "CROSS_UP"), value=kw.pop("value", 100),
              symbol=kw.pop("symbol", "BTCUSDT"), trigger_mode="EVERY",
              deliver={"in_app": True}, status="ACTIVE", enabled=True, **kw)
    db.add(a); db.commit(); db.refresh(a); return a


def test_parse_duration():
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("2h") == timedelta(hours=2)
    assert parse_duration("1d") == timedelta(days=1)
    assert parse_duration("nonsense") is None

def test_unlinked_chat_gets_prompt(db_session):
    assert "Settings" in handle_command(db_session, "/alarms", "999")

def test_non_command_returns_none(db_session):
    _link(db_session)
    assert handle_command(db_session, "hello there", "555") is None

def test_alarms_list_and_empty(db_session):
    _link(db_session)
    assert "No active alarms" in handle_command(db_session, "/alarms", "555")
    a = _alarm(db_session)
    out = handle_command(db_session, "/alarms", "555")
    assert f"#{a.id}" in out and "BTCUSDT" in out

def test_mute_and_unmute_by_id(db_session):
    _link(db_session); a = _alarm(db_session)
    assert "Muted 1" in handle_command(db_session, f"/mute {a.id}", "555")
    db_session.refresh(a); assert a.enabled is False
    assert "Unmuted 1" in handle_command(db_session, f"/unmute {a.id}", "555")
    db_session.refresh(a); assert a.enabled is True and a.status == "ACTIVE"

def test_mute_all(db_session):
    _link(db_session); _alarm(db_session); _alarm(db_session, symbol="ETHUSDT")
    assert "Muted 2" in handle_command(db_session, "/mute all", "555")

def test_snooze_sets_until(db_session):
    _link(db_session); a = _alarm(db_session)
    out = handle_command(db_session, f"/snooze {a.id} 2h", "555")
    db_session.refresh(a)
    assert a.snoozed_until is not None and "Snoozed" in out

def test_snooze_bad_duration(db_session):
    _link(db_session); a = _alarm(db_session)
    assert "Duration" in handle_command(db_session, f"/snooze {a.id} xyz", "555")

def test_mute_other_users_alarm_not_touched(db_session):
    _link(db_session, chat_id="555", user_id=1)
    other = _alarm(db_session, user_id=2)
    out = handle_command(db_session, f"/mute {other.id}", "555")
    assert "No matching" in out
    db_session.refresh(other); assert other.enabled is True

def test_unmute_does_not_resurrect_triggered(db_session):
    _link(db_session)
    a = _alarm(db_session)
    a.status = "TRIGGERED"; a.enabled = False; db_session.commit()
    out = handle_command(db_session, f"/unmute {a.id}", "555")
    assert "No matching" in out
    db_session.refresh(a); assert a.status == "TRIGGERED" and a.enabled is False

def test_alarms_list_shows_snoozed(db_session):
    from datetime import datetime, timezone, timedelta
    _link(db_session); a = _alarm(db_session)
    a.snoozed_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
    db_session.commit()
    out = handle_command(db_session, "/alarms", "555")
    assert "snoozed" in out.lower()

def test_snooze_terminated_alarm_no_match(db_session):
    _link(db_session)
    a = _alarm(db_session)
    a.status = "TRIGGERED"; db_session.commit()
    assert "No matching" in handle_command(db_session, f"/snooze {a.id} 1h", "555")
