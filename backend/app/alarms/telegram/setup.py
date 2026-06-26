"""One-time webhook registration. Run after deploy once the bot token + webhook
secret + public base URL are set:
    python -m app.alarms.telegram.setup https://your-public-url.example.com
"""
import sys
import httpx
from app.config import get_settings


def set_webhook(base_url: str) -> dict:
    s = get_settings()
    if not s.telegram_bot_token or not s.telegram_webhook_secret:
        raise SystemExit("TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET must be set")
    url = f"{base_url.rstrip('/')}/api/alarms/telegram/webhook/{s.telegram_webhook_secret}"
    r = httpx.post(f"https://api.telegram.org/bot{s.telegram_bot_token}/setWebhook",
                   json={"url": url}, timeout=10)
    print(r.status_code, r.text)
    return r.json()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m app.alarms.telegram.setup <public_base_url>")
    set_webhook(sys.argv[1])
