# LeftCurve

Self-hosted perpetuals trading journal for Bybit and Hyperliquid.

**Full setup guide → [docs/MANUAL.md](docs/MANUAL.md)**

## Features

- **Live cockpit** — real-time mark prices, open positions, unrealised P&L, and funding
- **Auto-import** — Bybit via a read-only API key; Hyperliquid via wallet address only (no key required)
- **Analytics** — funding costs, fees, leverage, MFE/MAE, win rate, streaks, equity curve
- **Trade journal** — per-trade notes, screenshots, and lightweight-charts price replay
- **Daily plan, playbooks, and reviews** — structured pre-session plan, saved playbooks, weekly/monthly review templates
- **Alarms** — price, position, and plan alarms with optional Telegram delivery
- **News** — market news feed (Squawk works keyless; Finnhub Equity/Crypto tabs require a free key)

## Tech stack

| Layer | Libraries |
|-------|-----------|
| Backend | FastAPI, SQLAlchemy, Alembic, SQLite (default) or Postgres |
| Frontend | React 18, Vite, Tailwind CSS, lightweight-charts, TanStack Query |

---

## Quickstart — Docker (recommended)

```bash
git clone https://github.com/SNDR521/LeftCurve-Perps.git
cd LeftCurve-Perps
cp backend/.env.example backend/.env
```

Generate two secrets and set them in `backend/.env`:

```bash
# Linux / macOS / Git Bash
openssl rand -hex 32   # → paste as SECRET_KEY
openssl rand -hex 32   # → paste as SESSION_SECRET
```

```powershell
# Windows PowerShell
[System.Convert]::ToBase64String((1..32 | ForEach-Object { [byte](Get-Random -Max 256) }))
```

Then:

```bash
docker compose up --build
```

Open **http://localhost:3000**. The first run shows a setup screen — create your account. Database migrations run automatically on startup; no manual step needed.

For VPS deployment, HTTPS setup, Postgres, and all configuration options, see **[docs/MANUAL.md](docs/MANUAL.md)**.

---

## Quickstart — local dev (no Docker)

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
# Edit .env — set SECRET_KEY and SESSION_SECRET
alembic upgrade head
uvicorn app.main:app --reload
```

**Frontend** (separate terminal)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api/*` to the backend on port 8000.

---

## Configuration

Set these in `backend/.env`:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | **Yes** | — | JWT signing key. Generate: `openssl rand -hex 32` |
| `SESSION_SECRET` | **Yes** | — | Session cookie signing key. Generate separately. |
| `DATABASE_URL` | No | `sqlite:///./trades.db` | Postgres: `postgresql+psycopg://user:pass@host:5432/db` |
| `FINNHUB_API_KEY` | No | — | Free key from [finnhub.io](https://finnhub.io) — enables Equity/Crypto news tabs |
| `TELEGRAM_BOT_TOKEN` | No | — | Bot token from @BotFather |
| `TELEGRAM_BOT_USERNAME` | No | — | Bot username without `@` |
| `TELEGRAM_WEBHOOK_SECRET` | No | — | Random hex, secures the inbound webhook path |
| `CORS_ORIGINS` | No | `http://localhost:5173,http://localhost:3000` | Comma-separated allowed origins. Set to your domain when hosting remotely. |
| `FRONTEND_URL` | No | `http://localhost:5173` | Frontend base URL, used for redirect links. Update when behind a reverse proxy. |

See [docs/MANUAL.md — Configuration reference](docs/MANUAL.md#6-configuration-reference) for the full table.

---

## Connecting an exchange

**Bybit** — Settings → Exchange Accounts → Add Bybit. Enter a **read-only** API key (needs the Positions read scope for closed P&L history sync).

**Hyperliquid** — Settings → Exchange Accounts → Add Hyperliquid. Enter your **wallet address** — no API key needed.

## Telegram alarms (optional)

1. Open Telegram and start a chat with **@BotFather**. Send `/newbot` and copy the token.
2. In the app, go to **Settings → Telegram**, paste the token, and click **Activate**.
3. Each user clicks **Connect Telegram** to link their account via the bot deep-link.

If the app is not publicly reachable (local dev), set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, and `TELEGRAM_WEBHOOK_SECRET` in `.env`, then register the webhook manually:

```bash
python -m app.alarms.telegram.setup https://your-public-url.example.com
```

## Password reset

Run in the backend directory with the venv active:

```bash
python -m app.core.reset_password <email> <new-password>
```

Or via Docker:

```bash
docker compose exec api python -m app.core.reset_password <email> <new-password>
```

## License

MIT — see [LICENSE](LICENSE).
