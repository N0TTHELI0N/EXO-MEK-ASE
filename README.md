# Mersad — ARK Discord Bot

Advanced admin bot for ARK: Survival Evolved servers hosted on Nitrado.
Deployed on **Render** as two independent web services.

## Architecture — two services, two folders

```
Mersaad - bot/
├── bot-service/          Discord bot, cogs, RCON, Nitrado, DB layer
├── dashboard-service/    Flask dashboard, templates, static, web routes
├── .gitignore
└── README.md
```

Each folder is a self-contained, independently deployable project with its own
`requirements.txt`, `Procfile`, `build.sh`, `gunicorn.conf.py`, `wsgi.py`,
`.python-version`, `.env` and `.env.example`. They share **no code at runtime**
and communicate only through one central PostgreSQL database and a shared
Fernet key.

| Service | Root Directory | Contents | Start command |
|---|---|---|---|
| **Bot** | `bot-service` | `cogs/` (19), Discord gateway, RCON, Nitrado client, `guild_settings.py`, `shop_db.py` | `gunicorn --config gunicorn.conf.py wsgi:application` |
| **Dashboard** | `dashboard-service` | Flask views, `templates/`, `static/`, `translations.py` | `gunicorn --config gunicorn.conf.py wsgi:application` |

- The **Bot** service serves only `/` and `/health` (a dependency-free WSGI
  status page). It no longer serves the dashboard and does not need Flask.
- The **Dashboard** service runs no Discord bot and does not need `discord.py`.
- `dashboard-service/core/` holds a **byte-identical** copy of the shared data
  layer (`config.py`, `security.py`, `bot_i18n.py`, `commands_manifest.py`,
  `command_defaults.py`, `guild_settings.py`, `shop_db.py`, `nitrado.py`,
  `sftp_client.py`). After changing any of those in `bot-service/`, copy it
  into `dashboard-service/core/` and keep the SHA-256 identical — they are two
  copies of one contract, not two implementations.

### Shared state contract

Both services must be configured with **identical** values for:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | The single source of truth (one central PostgreSQL) |
| `ENCRYPTION_KEY` | Same Fernet key, so the dashboard decrypts what the bot encrypted (Nitrado/API secrets) |
| `LICENSE_SIGN_KEY` | The dashboard validates licenses the bot issued (falls back to `ENCRYPTION_KEY` when unset) |
| `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` | Same OAuth2 application |
| `NITRADO_API_TOKEN` / `NITRADO_USER_ID` / `NITRADO_SERVICE_ID` | Same Nitrado account and server |

Service-to-service URLs (one direction each):

- `DASHBOARD_BASE_URL` — **set on the Bot**; used by `/help` and `/setup` to link out.
- `BOT_SERVICE_URL` — **set on the Dashboard**.

See `bot-service/.env.example` and `dashboard-service/.env.example` for the
complete, commented list.

## Features

- **Server Management** — Nitrado API commands, status, restart/stop
- **Moderation** — ban, tempban, warn, wipe players/records
- **Shop System** — buy dinos with points, manage the shop
- **Reserved Slots** — PSN linking, auto-restart on slot update
- **Player Log Monitor** — per-player activity threads from the in-game log
- **Leaderboard** — tribe points and rankings
- **Backups** — create/restore via the Nitrado Cloud Backup API
- **AutoMod** — profanity filter, spam detection, custom word lists
- **Dashboard** — web panel for every setting (separate service)

## Requirements

- Python 3.11.9 (pinned by `.python-version` in each service folder)
- PostgreSQL
- Nitrado server with API access
- A Discord bot token and an OAuth2 application

## Deployment — Render

Create **two Web Services** from the same repository, same branch (`main`),
same region. Set the **Root Directory** per service, then paste the
environment variables for that service before the first deploy.

### 1. Bot Service

| Setting | Value |
|---|---|
| Root Directory | `bot-service` |
| Build Command | `bash build.sh` |
| Start Command | `gunicorn --config gunicorn.conf.py wsgi:application` |
| Health Check Path | `/health` |
| Instance Type | **Starter (paid)** — see below |
| Auto-Deploy | `No` |
| Runtime | Python 3.11.9 (auto-detected from `.python-version`) |

> **Why paid is mandatory.** Render's free tier idles the container out after
> ~15 minutes. Waking up takes roughly a minute, and the Discord gateway
> connection is gone by then, so the bot re-syncs every slash command on each
> wake and spams the log. A paid instance never idles, so there is no
> reconnect churn.
>
> **Never add a second worker.** `gunicorn.conf.py` pins `workers = 1`; the
> Discord client is started once inside the worker via `post_worker_init`.
> Two workers = two logins to the same bot token.

### 2. Dashboard Service

| Setting | Value |
|---|---|
| Root Directory | `dashboard-service` |
| Build Command | `bash build.sh` |
| Start Command | `gunicorn --config gunicorn.conf.py wsgi:application` |
| Health Check Path | `/health` |
| Instance Type | `Starter` (or `Free` — a dashboard only needs to wake on request) |
| Auto-Deploy | `No` |
| Region | Same as the Bot service |

### 3. Environment variables

**On the Bot service** — add:

```
DISCORD_TOKEN=
DATABASE_URL=
ENCRYPTION_KEY=
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
BOT_OWNER_ID=
DASHBOARD_BASE_URL=https://<dashboard>.onrender.com
NITRADO_API_TOKEN=
NITRADO_USER_ID=
NITRADO_SERVICE_ID=
LOG_CHANNEL_ID=
AUTOMOD_LOG_CHANNEL_ID=
ADMIN_LOG_CHANNEL_ID=
TRIBE_LOG_CHANNEL_ID=
WHITELIST_LOG_CHANNEL_ID=
TICKET_LOG_CHANNEL_ID=
SERVER_LOG_CHANNEL_ID=
PSN_AWP_TOKEN=
TOPSERVERS_API_KEY=
```

**On the Dashboard service** — add:

```
DATABASE_URL=
ENCRYPTION_KEY=
LICENSE_SIGN_KEY=
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DISCORD_REDIRECT_URI=https://<dashboard>.onrender.com/callback
DASHBOARD_SECRET=
BOT_OWNER_ID=
BOT_SERVICE_URL=https://<bot>.onrender.com
NITRADO_API_TOKEN=
NITRADO_USER_ID=
NITRADO_SERVICE_ID=
LOG_CHANNEL_ID=
AUTOMOD_LOG_CHANNEL_ID=
ADMIN_LOG_CHANNEL_ID=
TRIBE_LOG_CHANNEL_ID=
WHITELIST_LOG_CHANNEL_ID=
TICKET_LOG_CHANNEL_ID=
SERVER_LOG_CHANNEL_ID=
```

Generate the two secrets with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_hex(32))"
```

The first is `ENCRYPTION_KEY` (a Fernet key), the second is `DASHBOARD_SECRET`.
`DASHBOARD_SECRET` must be a *different*, unique value — not a copy of the
Fernet key.

### 4. Never set these by hand

| Variable | Why |
|---|---|
| `PORT` | Render injects it. Setting it manually breaks the socket binding. |
| `WEB_CONCURRENCY` | Read only as `threads`; `workers` is pinned to 1. |
| `RENDER_EXTERNAL_HOSTNAME` | Injected by Render; used only as a fallback guess. |
| `DISCORD_TOKEN` on the Dashboard | Never used there. |
| `DISCORD_REDIRECT_URI` on the Bot | Dashboard-only — it builds the OAuth link. |
| `GUNICORN_CMD_ARGS` | Conflicts with `gunicorn.conf.py`. |

### 5. Register the OAuth2 redirect

In the [Discord Developer Portal](https://discord.com/developers/applications)
→ your application → **OAuth2 → Redirects**, add:

```
https://<dashboard>.onrender.com/callback
```

Without this, the dashboard's login button fails immediately.

### 6. Verify

```bash
curl https://<dashboard>.onrender.com/health          # {"status":"ok","service":"mersad-dashboard",...}
curl https://<dashboard>.onrender.com/api/service-info
curl https://<bot>.onrender.com/health                 # {"status":"ok","service":"mersad-bot",...}
```

In the Bot's **startup** logs (not the build log) you should see, in order:

```
[Bot] Starting Discord bot thread...
[Bot] Logged in as ... (ID: ...)
Synced N slash commands.
```

`Starting Discord bot thread...` must appear **exactly once** — twice means two
workers. Then in Discord: `/help` should show the dashboard link, and `/setup`
should open it.

## Local development

```bash
# bot  (terminal 1)
cd bot-service
pip install -r requirements.txt
python run.py

# dashboard  (terminal 2)
cd dashboard-service
pip install -r requirements.txt
python app.py
```

Each service loads the `.env` in its own folder. Real environment variables
always take precedence, so nothing is needed on Render.

## License

Private — all rights reserved.
