"""Two-way Telegram command handling. Pure-ish (DB only, no network): the
webhook calls handle_command and sends the returned reply. Phase 4 commands:
/alarms /mute /unmute /snooze /help. /new (guided create) is deferred."""
import re
from datetime import datetime, timezone, timedelta

from app.alarms.models import Alarm, TelegramLink

_DUR = re.compile(r"^(\d+)\s*([mhd])$", re.IGNORECASE)
_CMDS = {"/alarms", "/mute", "/unmute", "/snooze", "/help"}
_HELP = ("Commands:\n/alarms — list active\n/mute <id|all>\n"
         "/unmute <id|all>\n/snooze <id> <30m|2h|1d>")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_duration(s: str):
    m = _DUR.match((s or "").strip())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]


def _user_id_for(db, chat_id):
    link = db.query(TelegramLink).filter(TelegramLink.chat_id == str(chat_id)).first()
    return link.user_id if link else None


def _fmt(a) -> str:
    val = "" if a.value is None else a.value
    label = a.symbol or a.target_type
    base = f"#{a.id} {label} {a.condition} {val}".strip()
    if a.snoozed_until and a.snoozed_until > _now():
        base += f" (snoozed until {a.snoozed_until:%H:%M UTC})"
    return base


def handle_command(db, text, chat_id) -> str | None:
    text = (text or "").strip()
    if not text.startswith("/"):
        return None
    parts = text.split()
    cmd = parts[0].lower().split("@")[0]
    args = parts[1:]
    if cmd not in _CMDS:
        return None
    uid = _user_id_for(db, chat_id)
    if uid is None:
        return "Not linked. Open LeftCurve → Settings → Telegram to connect."
    if cmd == "/help":
        return _HELP
    if cmd == "/alarms":
        rows = (db.query(Alarm)
                .filter(Alarm.user_id == uid, Alarm.status == "ACTIVE", Alarm.enabled.is_(True))
                .order_by(Alarm.id).all())
        return "Active alarms:\n" + "\n".join(_fmt(a) for a in rows) if rows else "No active alarms."
    if cmd in ("/mute", "/unmute"):
        if not args:
            return f"Usage: {cmd} <id|all>"
        target = args[0].lower()
        q = db.query(Alarm).filter(Alarm.user_id == uid, Alarm.status == "ACTIVE")
        if target != "all":
            if not target.isdigit():
                return "Give a numeric alarm id or 'all'."
            q = q.filter(Alarm.id == int(target))
        rows = q.all()
        if not rows:
            return "No matching alarms."
        for a in rows:
            if cmd == "/mute":
                a.enabled = False
            else:
                a.enabled = True
                a.snoozed_until = None
        db.commit()
        return f"{'Muted' if cmd == '/mute' else 'Unmuted'} {len(rows)} alarm(s)."
    if cmd == "/snooze":
        if len(args) < 2 or not args[0].isdigit():
            return "Usage: /snooze <id> <30m|2h|1d>"
        dur = parse_duration(args[1])
        if dur is None:
            return "Duration like 30m, 2h, 1d."
        a = db.query(Alarm).filter(Alarm.user_id == uid, Alarm.id == int(args[0]),
                                   Alarm.status == "ACTIVE").first()
        if not a:
            return "No matching alarm."
        a.snoozed_until = _now() + dur
        db.commit()
        return f"Snoozed #{a.id} until {a.snoozed_until:%Y-%m-%d %H:%M} UTC."
    return None
