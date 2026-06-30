from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache
from dotenv import load_dotenv

# Absolute path so the .env is found regardless of the worker process cwd
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE, override=False)


class Settings(BaseSettings):
    # RiseX
    risex_api_base: str = "https://api.rise.trade"

    # Finnhub (News feed — optional)
    finnhub_api_key: str = ""

    # App
    database_url: str = "sqlite:///./trades.db"
    secret_key: str = "change-me"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Bybit API rate-limiting
    bybit_min_interval_s: float = 0.3

    # Telegram (Alarms delivery) — shared bot; users may override with their own token
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""      # without @, used to build t.me/<username>?start=<code>
    telegram_webhook_secret: str = ""    # path secret for the inbound webhook

    # Sessions
    session_secret: str = "dev-session-secret-change-me"
    frontend_url: str = "http://localhost:5173"

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
