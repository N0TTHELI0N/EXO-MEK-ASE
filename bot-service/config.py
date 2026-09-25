import os


# ---------- Discord ----------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ---------- Dashboard OAuth2 ----------
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "change-me")

# ────────────────────────────────────────────────────────────
#  Service topology (Bot Service <-> Dashboard Service)
# ────────────────────────────────────────────────────────────
#  The Flask dashboard is an INDEPENDENT service (dashboard-service/) with its
#  own repo/container/URL. The bot only needs to know where it lives so that
#  /help can link to it.
#
#  Set DASHBOARD_BASE_URL to the dashboard service's public URL, e.g.
#      https://mersad-dashboard.onrender.com
#  Leave it empty to hide the link (cogs/help.py already guards on this).
#
#  Koyeb exposes KOYEB_PUBLIC_DOMAIN for the service it is deploying, which is
#  the BOT's own domain — not the dashboard's — so it is only used as a
#  last-resort guess, never as the primary source.
_DASHBOARD_URL = os.getenv("DASHBOARD_BASE_URL", "").strip().rstrip("/")

if not _DASHBOARD_URL:
    # Optional: a service that also injects the sibling dashboard domain.
    _peer = os.getenv("DASHBOARD_PUBLIC_DOMAIN", "").strip()
    if _peer:
        _DASHBOARD_URL = f"https://{_peer}".rstrip("/")

DASHBOARD_BASE_URL = _DASHBOARD_URL

# Reverse direction: where the dashboard can find the bot. Consumed by the
# Dashboard Service (see dashboard-service/.env.example).
BOT_SERVICE_URL = os.getenv("BOT_SERVICE_URL", "").strip().rstrip("/")
if not BOT_SERVICE_URL:
    _self_domain = os.getenv("KOYEB_PUBLIC_DOMAIN", "").strip()
    if _self_domain:
        BOT_SERVICE_URL = f"https://{_self_domain}".rstrip("/")
else:
    # Lets the dashboard discover this bot's URL without extra configuration.
    os.environ.setdefault("DASHBOARD_BASE_URL", DASHBOARD_BASE_URL)

BOT_INVITE_URL = os.getenv(
    "BOT_INVITE_URL",
    "https://discord.com/oauth2/authorize"
    f"?client_id={DISCORD_CLIENT_ID}&scope=bot%20applications.commands"
    "&permissions=268443647",
)

# ---------- Logging channel ----------
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "1533171396547575859"))
AUTOMOD_LOG_CHANNEL_ID = int(os.getenv("AUTOMOD_LOG_CHANNEL_ID", "1533171396547575859"))
ADMIN_LOG_CHANNEL_ID = int(os.getenv("ADMIN_LOG_CHANNEL_ID", "1533171396547575859"))
TRIBE_LOG_CHANNEL_ID = int(os.getenv("TRIBE_LOG_CHANNEL_ID", "1533171396547575859"))
WHITELIST_LOG_CHANNEL_ID = int(os.getenv("WHITELIST_LOG_CHANNEL_ID", "1533171396547575859"))
TICKET_LOG_CHANNEL_ID = int(os.getenv("TICKET_LOG_CHANNEL_ID", "1533171396547575859"))
SERVER_LOG_CHANNEL_ID = int(os.getenv("SERVER_LOG_CHANNEL_ID", "1533171396547575859"))

# ---------- Database ----------
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ---------- Nitrado ----------
NITRADO_API_TOKEN = os.getenv("NITRADO_API_TOKEN", "")
NITRADO_USER_ID = os.getenv("NITRADO_USER_ID", "")
NITRADO_SERVICE_ID = os.getenv("NITRADO_SERVICE_ID", "")

# ---------- Bot Owner ----------
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "852876663617572884"))

# ---------- TopServers ----------
TOPSERVERS_API_KEY = os.getenv("TOPSERVERS_API_KEY", "")

# ---------- PSN (About Me verification / PSNAWP) ----------
PSN_AWP_TOKEN = os.getenv("PSN_AWP_TOKEN", "")
