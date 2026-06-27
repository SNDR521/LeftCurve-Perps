# LeftCurve — Setup & Installation Manual

Self-hosted perpetuals trading journal for Bybit and Hyperliquid.

> For a one-page summary and quick-start commands, see the [README](../README.md).
> This document is the full reference manual.

---

## Table of Contents

1. [What it is](#1-what-it-is)
2. [Prerequisites](#2-prerequisites)
3. [Quick start — Docker (recommended)](#3-quick-start--docker-recommended)
4. [Run locally without Docker (dev)](#4-run-locally-without-docker-dev)
5. [Deploying on a VPS](#5-deploying-on-a-vps)
6. [Configuration reference](#6-configuration-reference)
7. [Connecting an exchange](#7-connecting-an-exchange)
8. [Telegram alarms (optional)](#8-telegram-alarms-optional)
9. [News](#9-news)
10. [Customization](#10-customization)
11. [Backups & data](#11-backups--data)
12. [Password reset](#12-password-reset)
13. [Updating](#13-updating)
14. [Troubleshooting](#14-troubleshooting)
15. [License](#15-license)

---

## 1. What it is

LeftCurve is a self-hosted, single-user trading journal built specifically for perpetuals futures. It connects to Bybit and Hyperliquid, imports your trade history automatically, and gives you a structured environment to review, journal, and improve your trading.

**Features:**

- **Auto-import** — Bybit via a read-only API key; Hyperliquid via wallet address only (no key required)
- **Live cockpit** — real-time mark prices, open positions, unrealised P&L, and funding
- **Analytics** — funding costs, fees, leverage, MFE/MAE, win rate, streaks, equity curve
- **Trade journal** — per-trade notes, screenshots, and lightweight-charts price replay
- **Daily plan, playbooks, and reviews** — structured pre-session plan, saved playbooks, weekly/monthly review templates
- **Alarms** — price, position, and plan alarms with optional Telegram delivery
- **News** — market news feed (FinancialJuice Squawk works without any key; Finnhub Equity & Crypto tabs require a free API key)
- **Customization** — ticker bar with Bybit + Yahoo symbol search, accent colour, density, default timeframe, default landing page

LeftCurve is single-user and designed to be self-hosted. No cloud accounts, no subscriptions.

---

## 2. Prerequisites

### Option A — Docker (simplest, recommended)

- **Docker** (Desktop on Windows/macOS, Engine on Linux) with the **Compose** plugin (v2, `docker compose`)
- **Git**

That is all. Docker handles Python, Node, Nginx, and the database.

### Option B — Manual / dev

- **Python 3.12+** (the Docker image is `python:3.12-slim`; 3.11 may work but is untested)
- **Node 20+** (the Docker image is `node:20-alpine`)
- **Git**
- A shell that can run `pip`, `npm`, and `alembic`

---

## 3. Quick start — Docker (recommended)

Works on your local machine or a VPS. The entire stack — API, database migrations, and the React frontend served by Nginx — starts with one command.

### Step 1 — Clone the repo

```bash
git clone https://github.com/SNDR521/LeftCurve-Perps.git
cd LeftCurve-Perps
```

### Step 2 — Create your environment file

```bash
cp backend/.env.example backend/.env
```

### Step 3 — Generate and set secrets

`SECRET_KEY` and `SESSION_SECRET` are the only required variables. Generate two separate random values:

**Linux / macOS / Git Bash:**

```bash
openssl rand -hex 32
openssl rand -hex 32
```

**Windows PowerShell:**

```powershell
[System.Convert]::ToBase64String((1..32 | ForEach-Object { [byte](Get-Random -Max 256) }))
```

Or install OpenSSL for Windows and use the same `openssl rand -hex 32` command.

Open `backend/.env` and replace the placeholder values:

```dotenv
SECRET_KEY=<first-generated-value>
SESSION_SECRET=<second-generated-value>
```

### Step 4 — Build and start

```bash
docker compose up --build
```

The first build takes a few minutes (downloads Python and Node images, installs dependencies). On every startup the entrypoint automatically runs `alembic upgrade head` to apply any pending database migrations before the API starts. You do not need to run migrations manually.

### Step 5 — Open the app

```
http://localhost:3000
```

The first run displays a setup screen. Create your account there. From then on, that screen is gone and you log in normally.

> **Port 3000** is the web (Nginx/frontend) container. The API is also exposed at **port 8000** for direct access or tooling.

---

## 4. Run locally without Docker (dev)

Use this path when you want hot-reloading or are working on the code. Run the backend and frontend in two separate terminals.

### Backend

```bash
cd backend
```

**Create and activate a virtual environment:**

Windows:
```powershell
python -m venv venv
venv\Scripts\activate
```

Linux / macOS:
```bash
python -m venv venv
source venv/bin/activate
```

**Install dependencies:**

```bash
pip install -r requirements.txt
```

**Create your env file (first time only):**

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY and SESSION_SECRET
```

> For purely local dev the app will boot without a `.env` because `config.py` has fallback defaults (`secret_key = "change-me"`, `session_secret = "dev-session-secret-change-me"`). Do **not** use those defaults for anything exposed beyond your local machine.

**Apply database migrations:**

```bash
alembic upgrade head
```

This creates `backend/trades.db` (SQLite) on first run.

**Start the API:**

```bash
uvicorn app.main:app --reload --port 8000
```

`--reload` watches for file changes and restarts automatically. Remove it for a production-like run.

### Frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Vite starts on **http://localhost:5173** and proxies all `/api/*` requests to `http://localhost:8000`. Open that URL in your browser. The first run shows the account setup screen.

### Build for production (frontend only)

```bash
npm run build
```

The compiled bundle lands in `frontend/dist/` and can be served by any static host or Nginx. The Docker image does this automatically.

---

## 5. Deploying on a VPS

A single-user LeftCurve instance is very light. A Hetzner CX22 or DigitalOcean Droplet with 1–2 GB RAM and 20 GB disk is more than sufficient.

### 5.1 — Provision the server

Recommended: Ubuntu 22.04 LTS or 24.04. Any Debian/Ubuntu variant with Docker support works.

### 5.2 — Install Docker

Official convenience script (run as root or with sudo):

```bash
curl -fsSL https://get.docker.com | sh
```

Verify:

```bash
docker compose version
```

Full installation docs: https://docs.docker.com/engine/install/ubuntu/

### 5.3 — Clone and configure

```bash
git clone https://github.com/SNDR521/LeftCurve-Perps.git
cd LeftCurve-Perps
cp backend/.env.example backend/.env
```

Edit `backend/.env`. At minimum set strong values for `SECRET_KEY` and `SESSION_SECRET` (see Section 3, Step 3). If you have a domain, also set:

```dotenv
CORS_ORIGINS=https://yourdomain.com
FRONTEND_URL=https://yourdomain.com
```

### 5.4 — Start in detached mode

```bash
docker compose up -d --build
```

The `-d` flag runs containers in the background. Check logs with:

```bash
docker compose logs -f
```

### 5.5 — Persistence

Data survives container restarts and image rebuilds via Docker named volumes:

| Volume | Contents |
|--------|----------|
| `db_data` | SQLite database (`leftcurve.db`) |
| `screenshots` | Trade screenshot images |

These volumes are created automatically by Docker Compose and are **not** deleted by `docker compose down` unless you add the `-v` flag. Never use `docker compose down -v` in production.

### 5.6 — HTTPS and a custom domain (recommended)

Expose LeftCurve on a proper domain with automatic TLS using **Caddy**. Caddy auto-provisions a Let's Encrypt certificate.

**Install Caddy** (Ubuntu):

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

**Caddyfile** (`/etc/caddy/Caddyfile`):

```
yourdomain.com {
    reverse_proxy localhost:3000
}
```

Caddy handles TLS automatically. Restart Caddy after editing:

```bash
sudo systemctl reload caddy
```

Alternatively, use **Nginx** or **Traefik** if you prefer.

### 5.7 — Firewall

Allow only the ports you actually need:

```bash
# UFW example
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (Caddy redirects to HTTPS)
ufw allow 443/tcp   # HTTPS
ufw enable
```

Do **not** expose port 3000 or 8000 publicly when running behind a reverse proxy.

### 5.8 — Updating

```bash
cd LeftCurve-Perps
git pull
docker compose up -d --build
```

The entrypoint runs `alembic upgrade head` on startup, so migrations are applied automatically before the API accepts traffic.

---

## 6. Configuration reference

All variables are read from `backend/.env` (or from the environment). Sensitive values should never be committed to version control.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | **Yes** | `change-me` | JWT signing key. Generate with `openssl rand -hex 32`. Must be long and random. |
| `SESSION_SECRET` | **Yes** | `dev-session-secret-change-me` | Session cookie signing key. Generate separately from `SECRET_KEY`. |
| `DATABASE_URL` | No | `sqlite:///./trades.db` | Database connection string. Default is a local SQLite file. For Postgres: `postgresql+psycopg://user:pass@host:5432/leftcurve`. In Docker, the compose file overrides this to `sqlite:////app/data/leftcurve.db` (inside the persistent `db_data` volume). |
| `CORS_ORIGINS` | No | `http://localhost:5173,http://localhost:3000` | Comma-separated list of allowed origins. When hosting behind a domain, set to `https://yourdomain.com`. |
| `FRONTEND_URL` | No | `http://localhost:5173` | Base URL of the frontend. Used to construct redirect links. Update when running behind a reverse proxy. |
| `FINNHUB_API_KEY` | No | _(empty)_ | Free key from [finnhub.io](https://finnhub.io). Enables the Equity and Crypto news tabs. The Squawk (FinancialJuice) tab works without it. |
| `TELEGRAM_BOT_TOKEN` | No | _(empty)_ | Bot token from @BotFather. Can also be set inside the app via Settings → Telegram. |
| `TELEGRAM_BOT_USERNAME` | No | _(empty)_ | Bot username without the `@`. Used to build `t.me/<username>?start=<code>` deep-links. |
| `TELEGRAM_WEBHOOK_SECRET` | No | _(empty)_ | Random hex string used to secure the inbound Telegram webhook path. |

### Using Postgres instead of SQLite

Uncomment the `db` service in `docker-compose.yml`, uncomment `depends_on` in the `api` service, and set in `backend/.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://leftcurve:leftcurve@db:5432/leftcurve
```

Then start with the postgres profile:

```bash
docker compose --profile postgres up -d --build
```

---

## 7. Connecting an exchange

Navigate to **Settings → Exchange Accounts** (or the Accounts page) after logging in.

### Bybit

1. Log in to Bybit and go to **API Management**.
2. Create a new API key. Set the permissions to **read-only**. The key needs the **Positions** read scope to sync closed P&L history. Do **not** grant Trade or Withdraw permissions.
3. Copy the API Key and API Secret.
4. In LeftCurve: select **BYBIT**, give the account a label, paste the key and secret, and click **Add account**.
5. Click **Sync** to start the initial import.

The first sync backfills your full available history (Bybit retains approximately 2 years of raw fill data). Progress is shown in-app. Depending on trade volume this may take a few minutes.

> Note on entry times: closed-trade entry timestamps are reconstructed from execution history. Trades older than Bybit's fill retention window may display "entry unverified" — this is expected behaviour, not a bug.

### Hyperliquid

1. Copy your Hyperliquid wallet address (the `0x…` address).
2. In LeftCurve: select **HYPERLIQUID**, give the account a label, paste the wallet address, and click **Add account**.
3. Click **Sync**.

No API key is needed. Hyperliquid's API is fully public for read operations given an address.

### Keeping data in sync

After the initial import, LeftCurve auto-syncs your active accounts every few minutes in the background. To pull the latest fills on demand:

- **Dashboard → Sync button** (top-right): syncs the account selected in the sidebar, or all accounts when "All Accounts" is selected, then refreshes the dashboard when it finishes.
- **Accounts page → per-account Sync button**: syncs a single account and shows detailed progress.

---

## 8. Telegram alarms (optional)

Telegram delivery lets alarm fires reach you as a DM from your bot. You can also interact with the bot using commands like `/alarms`, `/mute`, and `/snooze`.

### Setup

1. Open Telegram and start a chat with **@BotFather**. Send `/newbot`, choose a name and username, and copy the bot token.
2. In LeftCurve, go to **Settings → Telegram**. Paste the token and click **Activate**. LeftCurve registers the webhook automatically.
3. Each user clicks **Connect Telegram** in Settings. A one-time deep-link opens the bot in Telegram; press **Start** to link your account.

### Alternative — env-var method (for local dev or non-public servers)

If the server is not publicly reachable (e.g. behind NAT), set the variables in `backend/.env`:

```dotenv
TELEGRAM_BOT_TOKEN=123456789:AAH...
TELEGRAM_BOT_USERNAME=mybotname
TELEGRAM_WEBHOOK_SECRET=<random-hex>
```

Then register the webhook manually from inside the backend directory with the venv active:

```bash
python -m app.alarms.telegram.setup https://your-public-url.example.com
```

---

## 9. News

The News section has three tabs:

| Tab | Data source | API key required? |
|-----|------------|-------------------|
| Squawk | FinancialJuice live audio squawk | No |
| Equity | Finnhub | Yes — `FINNHUB_API_KEY` |
| Crypto | Finnhub | Yes — `FINNHUB_API_KEY` |

Get a free Finnhub key at [finnhub.io](https://finnhub.io) (free tier is sufficient for personal use), then add it to `backend/.env`:

```dotenv
FINNHUB_API_KEY=your_key_here
```

Restart the API after changing `.env`:

```bash
# Docker:
docker compose restart api

# Manual:
# Stop uvicorn and restart it
```

---

## 10. Customization

Go to **Settings → Appearance** to adjust:

- **Ticker bar** — enable/disable the scrolling price ticker; search and add Bybit perpetual symbols or Yahoo Finance symbols
- **Accent colour** — change the UI highlight colour
- **Density** — compact or comfortable spacing
- **Default timeframe** — the chart timeframe shown when first opening a trade
- **Default landing page** — which page opens after login

All settings are persisted per user in the database.

---

## 11. Backups & data

### SQLite (default)

**Docker:** the database file is stored inside the `db_data` Docker volume at `/app/data/leftcurve.db` inside the container. To back it up:

```bash
# Copy the file out of the volume to the host
docker run --rm \
  -v leftcurve-perps_db_data:/data \
  -v $(pwd):/backup \
  alpine cp /data/leftcurve.db /backup/leftcurve.db.bak
```

Replace `leftcurve-perps_db_data` with the actual volume name (verify with `docker volume ls`).

**Manual install:** the database is at `backend/trades.db` (the path configured in `config.py` defaults). Copy that file to back it up.

Screenshot images live in the `screenshots` volume (Docker) or `backend/screenshots/` (manual). Back these up separately if you want to retain trade screenshots.

### Postgres

Use `pg_dump`:

```bash
pg_dump postgresql+psycopg://leftcurve:leftcurve@localhost:5432/leftcurve > backup.sql
```

Or from inside the Docker container:

```bash
docker compose exec db pg_dump -U leftcurve leftcurve > backup.sql
```

---

## 12. Password reset

If you cannot log in, reset your password from the command line.

**Manual install** (backend directory, venv active):

```bash
python -m app.core.reset_password you@example.com newpassword123
```

**Docker:**

```bash
docker compose exec api python -m app.core.reset_password you@example.com newpassword123
```

The service name `api` matches the service defined in `docker-compose.yml`. The script prints `Password reset for you@example.com` on success.

---

## 13. Updating

### Docker

```bash
cd LeftCurve-Perps
git pull
docker compose up -d --build
```

Database migrations are applied automatically on startup. No manual migration step is needed.

### Manual install

```bash
cd LeftCurve-Perps
git pull

# Backend
cd backend
source venv/bin/activate          # Linux/macOS
# or: venv\Scripts\activate       # Windows
pip install -r requirements.txt   # pick up any new deps
alembic upgrade head              # apply migrations
# restart uvicorn

# Frontend
cd ../frontend
npm install                       # pick up any new deps
npm run build                     # or just restart `npm run dev`
```

---

## 14. Troubleshooting

### News tabs are empty

- **Squawk tab:** runs without any key. If it shows nothing, check your browser console for WebSocket errors.
- **Equity / Crypto tabs:** require `FINNHUB_API_KEY`. Set it in `backend/.env` and restart the API.

### Port already in use

Docker will fail to start if port 3000 or 8000 is already bound on your machine. Find the conflicting process:

```bash
# Linux/macOS
lsof -i :3000
lsof -i :8000

# Windows PowerShell
netstat -ano | findstr :3000
netstat -ano | findstr :8000
```

Either stop the conflicting process or edit `docker-compose.yml` to map a different host port (e.g., `"3001:80"` for the web service).

### Setup screen not appearing on first run

The setup screen only shows when no user accounts exist in the database. If the database was not initialised (migrations did not run), the API may be returning errors instead. Check logs:

```bash
docker compose logs api
```

If you see migration errors, the `alembic upgrade head` step failed. Common causes: the `db_data` volume does not have write permissions, or `DATABASE_URL` points to a Postgres instance that is not yet ready. In the Docker setup the entrypoint always runs migrations; if it crashed before finishing, restart:

```bash
docker compose restart api
```

### "entry unverified" on trades

This is expected. Bybit's API only retains raw fill history for approximately 2 years. Trades older than that are imported from the closed P&L endpoint, which does not include fill-level detail. The entry timestamp is estimated and marked as unverified. The P&L data itself is accurate.

### Re-syncing an account

Click **Sync** on any account in Settings → Exchange Accounts at any time. The sync is incremental and will only fetch data newer than the last successful sync cursor. If a sync appears stalled (no update for 60+ seconds), the in-app UI will flag it; click **Resume sync** to restart from the last cursor position.

### API is up but the frontend shows a blank page

Nginx serves the compiled bundle from `frontend/dist/`. If you ran the frontend build but forgot to rebuild the Docker image, Nginx may be serving a stale or empty dist. Rebuild:

```bash
docker compose up -d --build
```

In dev mode (`npm run dev`) this cannot happen — Vite serves files directly from `src/`.

---

## 15. License

MIT — see [LICENSE](../LICENSE).
