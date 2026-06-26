import pytest
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from unittest.mock import patch, MagicMock

from app.database import Base, make_engine
from app.core.models import User
from app.core.security import hash_password


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


# ─── Task 3: bot.send_message ────────────────────────────────────────────────

from app.alarms.telegram import bot


def test_send_message_uses_explicit_token_then_shared(monkeypatch):
    calls = []
    def fake_post(url, json, timeout):
        calls.append((url, json))
        r = MagicMock(); r.status_code = 200; r.json = lambda: {"ok": True}
        return r
    with patch("app.alarms.telegram.bot.httpx.post", side_effect=fake_post):
        assert bot.send_message("123", "hi", token="USERTOKEN") is True
        assert "USERTOKEN" in calls[-1][0]
        monkeypatch.setattr(bot, "_shared_token", lambda: "SHARED")
        assert bot.send_message("123", "hi") is True
        assert "SHARED" in calls[-1][0]


def test_send_message_no_token_is_noop():
    with patch("app.alarms.telegram.bot._shared_token", return_value=""):
        assert bot.send_message("123", "hi") is False


def test_send_message_swallows_errors():
    with patch("app.alarms.telegram.bot._shared_token", return_value="T"), \
         patch("app.alarms.telegram.bot.httpx.post", side_effect=RuntimeError("net")):
        assert bot.send_message("123", "hi") is False


# ─── Task 4: notify ──────────────────────────────────────────────────────────

from app.alarms.telegram import notify
from app.alarms.models import TelegramLink
from app.workflow.models import Alert


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_collect_targets_filters_and_resolves(db_session):
    db_session.add(TelegramLink(user_id=1, chat_id="555", bot_token_enc=None))
    db_session.commit()
    a1 = Alert(user_id=1, kind="ALARM", symbol="BTCUSDT", triggered_at=_now(),
               payload={"telegram": True, "text": "BTC crossed up 100"})
    a2 = Alert(user_id=1, kind="ALARM", symbol="ETHUSDT", triggered_at=_now(),
               payload={"telegram": False, "text": "no tg"})
    a3 = Alert(user_id=2, kind="ALARM", symbol="SOLUSDT", triggered_at=_now(),
               payload={"telegram": True, "text": "unlinked user"})
    db_session.add_all([a1, a2, a3]); db_session.commit()
    targets = notify.collect_targets(db_session, [a1, a2, a3])
    assert len(targets) == 1
    chat_id, token, text = targets[0]
    assert chat_id == "555" and token is None and "BTC crossed up 100" in text


def test_send_all_dispatches_each(monkeypatch):
    sent = []
    monkeypatch.setattr(notify.bot, "send_message",
                        lambda chat_id, text, token=None: sent.append((chat_id, text, token)) or True)
    notify.send_all([("555", None, "a"), ("777", "TOK", "b")])
    assert sent == [("555", "a", None), ("777", "b", "TOK")]


# ─── Task 8: Router — link/start, status, token, webhook ─────────────────────

def test_link_start_and_status(auth_client):
    r = auth_client.post("/api/alarms/telegram/link/start")
    assert r.status_code == 200
    body = r.json()
    assert "t.me/" in body["url"] and "start=" in body["url"] and body["code"]
    st = auth_client.get("/api/alarms/telegram/status").json()
    assert st["linked"] is False and st["has_own_token"] is False



def test_webhook_rejects_bad_secret(db_session, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.alarms.routers import telegram as tg
    from app.alarms.models import TelegramBotConfig
    db_session.add(TelegramBotConfig(webhook_secret="S")); db_session.commit()
    req = SimpleNamespace(json=lambda: asyncio.sleep(0, result={}))  # not reached
    import fastapi
    try:
        asyncio.run(tg.webhook("WRONG", req, db_session))
        assert False, "should have raised"
    except fastapi.HTTPException as e:
        assert e.status_code == 404


def test_webhook_rejects_empty_secret(db_session, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.alarms.routers import telegram as tg
    async def fake_json():
        return {"message": {"text": "/start ANYTHING", "chat": {"id": 1}}}
    req = SimpleNamespace(json=fake_json)
    import fastapi
    # Even an empty path secret must NOT authenticate when the server secret is unset
    # (no TelegramBotConfig in DB, env var also empty → secret resolves to "").
    try:
        asyncio.run(tg.webhook("", req, db_session))
        assert False, "empty server secret must reject all webhook calls"
    except fastapi.HTTPException as e:
        assert e.status_code == 404


def test_webhook_links_via_start_code(db_session, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.alarms.routers import telegram as tg
    from app.alarms.models import TelegramLink, TelegramLinkCode, TelegramBotConfig
    from datetime import datetime, timezone, timedelta
    db_session.add(TelegramBotConfig(webhook_secret="S"))
    db_session.add(TelegramLinkCode(code="ABC", user_id=1,
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=10)))
    db_session.commit()
    monkeypatch.setattr(tg.bot, "send_message", lambda *a, **k: True)
    async def fake_json():
        return {"message": {"text": "/start ABC", "chat": {"id": 999, "username": "joe"}}}
    req = SimpleNamespace(json=fake_json)
    asyncio.run(tg.webhook("S", req, db_session))
    link = db_session.query(TelegramLink).filter(TelegramLink.user_id == 1).first()
    assert link and link.chat_id == "999"
    code = db_session.query(TelegramLinkCode).filter(TelegramLinkCode.code == "ABC").first()
    assert code.used is True


def test_webhook_dispatches_alarms_command(db_session, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from app.alarms.routers import telegram as tg
    from app.alarms.models import TelegramLink, TelegramBotConfig
    db_session.add(TelegramBotConfig(webhook_secret="S"))
    db_session.add(TelegramLink(user_id=1, chat_id="777")); db_session.commit()
    sent = []
    monkeypatch.setattr(tg.bot, "send_message", lambda chat_id, text, token=None: sent.append((chat_id, text)) or True)
    async def fake_json(): return {"message": {"text": "/alarms", "chat": {"id": 777}}}
    asyncio.run(tg.webhook("S", SimpleNamespace(json=fake_json), db_session))
    assert sent and sent[0][0] == "777" and "alarm" in sent[0][1].lower()


# ─── Task 3 (new): resolver wired into router + shared-token dispatch ─────────

def test_webhook_secret_from_db_config(db_session, monkeypatch):
    import asyncio, fastapi
    from types import SimpleNamespace
    from app.alarms.routers import telegram as tg
    from app.alarms.models import TelegramBotConfig
    db_session.add(TelegramBotConfig(webhook_secret="DBSEC")); db_session.commit()
    monkeypatch.setattr(tg.bot, "send_message", lambda *a, **k: True)
    async def fake_json(): return {"message": {"text": "/help", "chat": {"id": 1}}}
    try:
        asyncio.run(tg.webhook("WRONG", SimpleNamespace(json=fake_json), db_session)); assert False
    except fastapi.HTTPException as e:
        assert e.status_code == 404
    r = asyncio.run(tg.webhook("DBSEC", SimpleNamespace(json=fake_json), db_session))
    assert r == {"ok": True}


def test_collect_targets_uses_shared_token(db_session):
    from datetime import datetime
    from app.alarms.models import TelegramLink, TelegramBotConfig
    from app.alarms.telegram import notify
    from app.workflow.models import Alert
    from app.core.security import encrypt_credentials
    db_session.add(TelegramBotConfig(bot_token_enc=encrypt_credentials({"token": "SHARED"})))
    db_session.add(TelegramLink(user_id=1, chat_id="555"))
    db_session.commit()
    a = Alert(user_id=1, kind="ALARM", symbol="BTCUSDT",
              payload={"telegram": True, "text": "x"}, triggered_at=datetime.utcnow())
    db_session.add(a); db_session.commit()
    targets = notify.collect_targets(db_session, [a])
    assert len(targets) == 1 and targets[0][1] == "SHARED"


# ─── Bot-config endpoints (authenticated user = owner) ────────────────────────

def test_bot_config_requires_auth(client):
    r = client.post("/api/alarms/telegram/bot-config", json={"token": "x", "base_url": "https://h"})
    assert r.status_code == 401


def test_bot_config_bad_token_rejected(auth_client, monkeypatch):
    import app.alarms.routers.telegram as tg
    monkeypatch.setattr(tg.httpx, "get",
        lambda *a, **k: type("R", (), {"json": lambda self: {"ok": False, "description": "Unauthorized"}})())
    r = auth_client.post("/api/alarms/telegram/bot-config", json={"token": "bad", "base_url": "https://trade.x"})
    assert r.status_code == 400 and "Unauthorized" in r.text


def test_bot_config_activate_ok(auth_client, monkeypatch):
    import app.alarms.routers.telegram as tg
    monkeypatch.setattr(tg.httpx, "get",
        lambda *a, **k: type("R", (), {"json": lambda self: {"ok": True, "result": {"username": "LeftCurveBot"}}})())
    monkeypatch.setattr(tg.httpx, "post",
        lambda *a, **k: type("R", (), {"json": lambda self: {"ok": True}})())
    r = auth_client.post("/api/alarms/telegram/bot-config", json={"token": "good", "base_url": "https://trade.x"})
    body = r.json()
    assert r.status_code == 200 and body["username"] == "LeftCurveBot" and body["webhook_set"] is True
    g = auth_client.get("/api/alarms/telegram/bot-config").json()
    assert g["configured"] is True and g["username"] == "LeftCurveBot" and g["webhook_set_at"]


def test_delete_bot_config_removes_orphan_row(auth_client):
    from app.database import SessionLocal
    from app.alarms.models import TelegramBotConfig
    db = SessionLocal()
    try:
        db.query(TelegramBotConfig).delete(); db.commit()
        db.add(TelegramBotConfig(webhook_secret="DBSEC")); db.commit()  # no token set
    finally:
        db.close()
    r = auth_client.delete("/api/alarms/telegram/bot-config")
    assert r.status_code == 200 and r.json()["configured"] is False
    db2 = SessionLocal()
    try:
        assert db2.query(TelegramBotConfig).count() == 0
    finally:
        db2.close()
