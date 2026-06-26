"""Telegram Bot API send. Resolves the token: explicit per-user token if given,
else the shared bot token from settings. Failure-isolated — never raises; a send
failure returns False and is logged (an alarm must never break because Telegram
is down)."""
import logging
import httpx
from app.config import get_settings

log = logging.getLogger(__name__)
_TIMEOUT = 5.0


def _shared_token() -> str:
    return get_settings().telegram_bot_token or ""


def send_message(chat_id: str, text: str, token: str | None = None) -> bool:
    tok = token or _shared_token()
    if not tok or not chat_id:
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=_TIMEOUT,
        )
        if r.status_code != 200:
            log.warning("telegram send failed: %s %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception:  # noqa: BLE001
        log.exception("telegram send error")
        return False
