"""Telegram linking + inbound webhook. Mounted at /api/alarms.
Phase 2: webhook handles only /start <code> linking (commands are Phase 4)."""
import asyncio
import secrets
import logging
import httpx
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.core.deps import get_current_user
from app.core.models import User
from app.core.security import encrypt_credentials
from app.alarms.models import TelegramLink, TelegramLinkCode, TelegramBotConfig
from app.alarms.telegram import bot
from app.alarms.telegram import config as tgconfig

log = logging.getLogger(__name__)
router = APIRouter(prefix="/alarms/telegram", tags=["alarms-telegram"])
CODE_TTL_MIN = 15


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _get_or_create_link(db, user_id) -> TelegramLink:
    link = db.query(TelegramLink).filter(TelegramLink.user_id == user_id).first()
    if not link:
        link = TelegramLink(user_id=user_id); db.add(link); db.flush()
    return link


@router.post("/link/start")
def link_start(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code = secrets.token_urlsafe(8)
    db.add(TelegramLinkCode(code=code, user_id=user.id,
                            expires_at=_now() + timedelta(minutes=CODE_TTL_MIN)))
    db.commit()
    uname = tgconfig.bot_username(db) or "your_bot"
    return {"code": code, "url": f"https://t.me/{uname}?start={code}",
            "expires_in_min": CODE_TTL_MIN}


@router.get("/status")
def status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = db.query(TelegramLink).filter(TelegramLink.user_id == user.id).first()
    return {
        "linked": bool(link and link.chat_id),
        "username": link.username if link else None,
        "has_own_token": bool(link and link.bot_token_enc),
        "bot_username": tgconfig.bot_username(db),
    }



@router.delete("/link")
def unlink(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = db.query(TelegramLink).filter(TelegramLink.user_id == user.id).first()
    if link:
        link.chat_id = None; link.username = None; link.linked_at = None; db.commit()
    return {"linked": False}


@router.post("/webhook/{secret}")
async def webhook(secret: str, request: Request, db: Session = Depends(get_db)):
    """Inbound Telegram updates. UNAUTHENTICATED (called by Telegram) — guarded
    by the path secret. Handles /start <code> linking and the two-way commands
    (/alarms /mute /unmute /snooze /help) via app.alarms.telegram.commands."""
    expected = tgconfig.webhook_secret(db)
    if not expected or not secrets.compare_digest(secret, expected):
        raise HTTPException(404)
    update = await request.json()
    msg = (update or {}).get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id")) if chat.get("id") is not None else None
    tok = tgconfig.shared_token(db)
    if text.startswith("/start") and chat_id:
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        rec = (db.query(TelegramLinkCode)
               .filter(TelegramLinkCode.code == code,
                       TelegramLinkCode.used.is_(False),
                       TelegramLinkCode.expires_at > _now()).first()) if code else None
        if rec:
            link = _get_or_create_link(db, rec.user_id)
            link.chat_id = chat_id
            link.username = (chat.get("username") or (msg.get("from") or {}).get("username"))
            link.linked_at = _now()
            rec.used = True
            db.commit()
            await asyncio.get_running_loop().run_in_executor(None, bot.send_message, chat_id, "✅ LeftCurve alarms linked. You'll get alerts here.", tok)
        else:
            await asyncio.get_running_loop().run_in_executor(None, bot.send_message, chat_id, "This link is invalid or expired. Generate a new one in LeftCurve → Settings.", tok)
    elif chat_id and text.startswith("/"):
        from app.alarms.telegram import commands
        reply = commands.handle_command(db, text, chat_id)
        if reply:
            await asyncio.get_running_loop().run_in_executor(None, bot.send_message, chat_id, reply, tok)
    return {"ok": True}


# ─── Bot-config endpoints (authenticated user = owner) ───

class BotConfigBody(BaseModel):
    token: str
    base_url: str


@router.get("/bot-config")
def get_bot_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = tgconfig.get_config(db)
    return {
        "configured": bool(cfg and cfg.bot_token_enc),
        "username": cfg.bot_username if cfg else None,
        "webhook_set_at": cfg.webhook_set_at.isoformat() if (cfg and cfg.webhook_set_at) else None,
    }


@router.post("/bot-config")
def set_bot_config(body: BotConfigBody, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    token = body.token.strip()
    base = body.base_url.rstrip("/")
    try:
        me = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"could not reach Telegram: {e}")
    if not me.get("ok"):
        raise HTTPException(400, me.get("description") or "invalid bot token")
    username = (me.get("result") or {}).get("username")

    cfg = tgconfig.get_config(db)
    if cfg is None:
        cfg = TelegramBotConfig(); db.add(cfg)
    cfg.bot_token_enc = encrypt_credentials({"token": token})
    if username:
        cfg.bot_username = username
    if not cfg.webhook_secret:
        cfg.webhook_secret = secrets.token_urlsafe(24)
    cfg.public_base_url = base
    db.flush()

    hook = f"{base}/api/alarms/telegram/webhook/{cfg.webhook_secret}"
    webhook_set, err = False, None
    try:
        r = httpx.post(f"https://api.telegram.org/bot{token}/setWebhook", json={"url": hook}, timeout=10).json()
        webhook_set = bool(r.get("ok"))
        if webhook_set:
            cfg.webhook_set_at = _now()
        else:
            err = r.get("description")
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    db.commit()
    out = {"configured": True, "username": username, "webhook_set": webhook_set}
    if err:
        out["error"] = err
    return out


@router.delete("/bot-config")
def delete_bot_config(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = tgconfig.get_config(db)
    if cfg:
        token = tgconfig.shared_token(db)
        if token:
            try:
                httpx.post(f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=10)
            except Exception:  # noqa: BLE001
                pass
        db.delete(cfg)
        db.commit()
    return {"configured": False}
