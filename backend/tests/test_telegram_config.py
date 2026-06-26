import pytest
from sqlalchemy.orm import Session

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password, encrypt_credentials
from app.alarms.models import TelegramBotConfig
from app.alarms.telegram import config as tgconfig


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


def test_token_from_db_overrides_env(db_session, monkeypatch):
    db_session.add(TelegramBotConfig(bot_token_enc=encrypt_credentials({"token": "DBTOKEN"}),
                                     bot_username="DbBot", webhook_secret="DBSEC"))
    db_session.commit()
    assert tgconfig.shared_token(db_session) == "DBTOKEN"
    assert tgconfig.bot_username(db_session) == "DbBot"
    assert tgconfig.webhook_secret(db_session) == "DBSEC"

def test_falls_back_to_env_when_no_row(db_session, monkeypatch):
    import app.config
    s = app.config.get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "ENVTOKEN", raising=False)
    monkeypatch.setattr(s, "telegram_bot_username", "EnvBot", raising=False)
    monkeypatch.setattr(s, "telegram_webhook_secret", "ENVSEC", raising=False)
    assert tgconfig.shared_token(db_session) == "ENVTOKEN"
    assert tgconfig.bot_username(db_session) == "EnvBot"
    assert tgconfig.webhook_secret(db_session) == "ENVSEC"

def test_empty_when_neither(db_session, monkeypatch):
    import app.config
    s = app.config.get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "", raising=False)
    monkeypatch.setattr(s, "telegram_bot_username", "", raising=False)
    monkeypatch.setattr(s, "telegram_webhook_secret", "", raising=False)
    assert tgconfig.shared_token(db_session) == ""
    assert tgconfig.bot_username(db_session) is None
    assert tgconfig.webhook_secret(db_session) == ""
