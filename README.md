# Exo-Mek ASA - ARK Discord Bot

Advanced admin bot for ARK servers hosted on Nitrado.

## Architecture — two independent services

This repository is split into two services that share **no code at runtime**;
they communicate only through one central PostgreSQL database and a shared
Fernet key.

| Service | Folder | Contents | Koyeb Procfile |
|---|---|---|---|
| **Bot Service** | repo root | `cogs/`, Discord gateway, RCON, Nitrado client, `guild_settings.py`, `shop_db.py` | `gunicorn --config gunicorn.conf.py wsgi:application` |
| **Dashboard Service** | `dashboard-service/` | Flask views, `templates/`, `static/`, `translations.py` | `gunicorn --config gunicorn.conf.py wsgi:application` |

- The Bot Service serves only `/` and `/health` (a dependency-free WSGI status
  page) — it no longer serves the dashboard.
- The Dashboard Service runs no Discord bot and needs no `discord.py`.
- `dashboard-service/core/` holds a byte-identical copy of the shared data layer
  (`guild_settings.py`, `shop_db.py`, `nitrado.py`, `sftp_client.py`,
  `bot_i18n.py`, `commands_manifest.py`, `command_defaults.py`, `config.py`,
  `security.py`). Keep both copies in sync when changing the DB schema.

### Shared state contract

Both services must be configured with **identical** values for:

- `DATABASE_URL` — the single source of truth (one central PostgreSQL)
- `ENCRYPTION_KEY` — same Fernet key, so the dashboard decrypts what the bot
  encrypted (Nitrado/API secrets)
- `LICENSE_SIGN_KEY` — the dashboard validates licenses the bot issued
  (falls back to `ENCRYPTION_KEY` when unset)
- `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` — same OAuth2 app
- `NITRADO_API_TOKEN` / `NITRADO_USER_ID` / `NITRADO_SERVICE_ID`

Bot → Dashboard: `DASHBOARD_BASE_URL` (used by `/help`).
Dashboard → Bot: `BOT_SERVICE_URL`.

See `.env.example` (bot) and `dashboard-service/.env.example` (dashboard).

## Features

- **Server Management** - Nitrado API commands, server status, restart/stop
- **Moderation** - Ban, tempban, warn, wipe players/tribes
- **Shop System** - Buy dinos with points, manage shop
- **Reserved Slots** - PSN linking, auto-restart with slot update
- **Player Log** - Per-player activity threads from in-game log (non-admin)
- **Leaderboard** - Tribe points and rankings
- **Server Backup** - Create, restore backups via Nitrado Cloud Backup API
- **AutoMod** - Profanity filter, spam detection, custom words
- **Dashboard** - Web panel for all settings (separate service)

## Requirements

- Python 3.11+
- PostgreSQL database
- Nitrado server with API access
- Discord Bot Token

## Environment Variables

See `.env.example` for all required variables.

## Deployment

### Koyeb — Bot Service
- Root directory: repo root · Build: `pip install -r requirements.txt`
- Health check path: `/health` · Instance: **paid** (the bot must stay awake)

### Koyeb — Dashboard Service
- Root directory: `dashboard-service/` · Build: `pip install -r requirements.txt`
- Health check path: `/health`

### Local
```bash
# bot
pip install -r requirements.txt
python run.py

# dashboard (separate shell)
pip install -r dashboard-service/requirements.txt
cd dashboard-service && python app.py
```

## License

Private - All rights reserved.
