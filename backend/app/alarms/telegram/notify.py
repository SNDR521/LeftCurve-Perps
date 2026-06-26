"""Bridge fired alarm Alerts → Telegram pushes. collect_targets resolves
session-bound data into plain tuples (so the DB session can close before the
slow HTTP sends); send_all does the blocking sends off the hot path."""
import logging
from app.alarms.models import TelegramLink
from app.alarms.telegram import bot

log = logging.getLogger(__name__)


def collect_targets(db, alerts) -> list:
    """For alerts whose payload requests telegram AND whose user is linked,
    return [(chat_id, token_or_None, text), ...]. Resolve now (session open)."""
    want = [a for a in alerts if (a.payload or {}).get("telegram")]
    if not want:
        return []
    from app.alarms.telegram import config as tgconfig
    token = tgconfig.shared_token(db) or None  # "" -> None so bot.send_message falls back to its env-token default
    user_ids = {a.user_id for a in want}
    links = {l.user_id: l for l in db.query(TelegramLink)
             .filter(TelegramLink.user_id.in_(user_ids),
                     TelegramLink.chat_id.isnot(None)).all()}
    out = []
    for a in want:
        link = links.get(a.user_id)
        if not link:
            continue
        p = a.payload or {}
        text = (f"🔔 {p.get('message')}\n{p.get('text', '')}".strip()
                if p.get("message") else f"🔔 {p.get('text') or a.symbol or 'Alarm'}")
        out.append((link.chat_id, token, text))
    return out


def send_all(targets) -> int:
    sent = 0
    for chat_id, token, text in targets:
        if bot.send_message(chat_id, text, token=token):
            sent += 1
    return sent
