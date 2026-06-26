# LeftCurve

Self-hosted perpetuals trading journal for Bybit and Hyperliquid.

## Features

- **Live cockpit** — real-time mark prices, open positions, unrealised P&L, and funding
- **Auto-import** — Bybit via a read-only API key; Hyperliquid via wallet address only (no key required)
- **Analytics** — funding costs, fees, leverage, MFE/MAE, win rate, streaks, equity curve
- **Trade journal** — per-trade notes, screenshots, and lightweight-charts price replay
- **Daily plan, playbooks, and reviews** — structured pre-session plan, saved playbooks, weekly/monthly review templates
- **Alarms** — price, position, and plan alarms with optional Telegram delivery
- **News** — market news feed (Finnhub, optional)

## Tech stack

| Layer | Libraries |
|-------|-----------|
| Backend | FastAPI, SQLAlchemy, Alembic, SQLite (default) or Postgres |
| Frontend | React 18, Vite, Tailwind CSS, lightweight-charts, TanStack Query |

## Quickstart — local (recommended)

```bash
git clone https://github.com/your-org/leftcurve-perps.git
cd leftcurve-perps
```

**Backend**

```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# Edit .env — set SECRET_KEY and SESSION_SECRET (see Configuration below)
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open the URL shown by Vite (default `http://localhost:5173`). The first run shows a setup screen where you create your account.

## Quickstart — Docker

```bash
cp backend/.env.example backend/.env
# Edit backend/.env — set SECRET_KEY and SESSION_SECRET
docker compose up --build
```

Open `http://localhost:3000`. The first run shows a setup screen to create your account.

Note: a full `docker compose build` is required once; subsequent starts are fast.

## Configuration

Set these in `backend/.env` (or as environment variables):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | — | JWT signing key. Generate: `openssl rand -hex 32` |
| `SESSION_SECRET` | Yes | — | Session cookie signing key. Generate: `openssl rand -hex 32` |
| `DATABASE_URL` | No | `sqlite:///./trades.db` | Postgres: `postgresql+psycopg://user:pass@host:5432/db` |
| `FINNHUB_API_KEY` | No | — | Free key from [finnhub.io](https://finnhub.io) — required for the News feed |
| `TELEGRAM_BOT_TOKEN` | No | — | Bot token from @BotFather (env-var method; see Telegram Alarms below) |
| `TELEGRAM_BOT_USERNAME` | No | — | Bot username without `@` |
| `TELEGRAM_WEBHOOK_SECRET` | No | — | Random hex, used to secure the inbound webhook path |
| `CORS_ORIGINS` | No | `http://localhost:5173` | Comma-separated list of allowed CORS origins. Docker/remote users must set this to their public frontend URL |
| `FRONTEND_URL` | No | `http://localhost:5173` | Base URL of the frontend, used for redirect links (e.g. in emails). Update when running behind a reverse proxy |

## Connecting an exchange

**Bybit** — Go to Settings → Exchange Accounts → Add Bybit. Enter a read-only API key. The key needs the **Positions** read scope so closed-P&L history can sync.

**Hyperliquid** — Go to Settings → Exchange Accounts → Add Hyperliquid. Enter your wallet address only — no API key needed.

## Telegram alarms (optional)

1. Open Telegram and start a chat with **@BotFather**. Send `/newbot` and copy the token.
2. In the app, go to **Settings → Telegram**, paste the token, and click **Activate**. LeftCurve registers the webhook automatically.
3. Each user clicks **Connect Telegram** to link their account. A one-time deep-link opens the bot; press **Start** to confirm.

If the app is not publicly reachable (local dev), use the env-var method instead: set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, and `TELEGRAM_WEBHOOK_SECRET` in `.env`, then register the webhook manually:

```bash
python -m app.alarms.telegram.setup https://your-public-url.example.com
```

## Password reset

Run this in the backend directory with the venv active:

```bash
python -m app.core.reset_password <email> <new-password>
```

## License

MIT — see [LICENSE](LICENSE).
