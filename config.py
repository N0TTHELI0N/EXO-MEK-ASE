import os


# ---------- Discord ----------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ---------- Gemini ----------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ---------- Dashboard OAuth2 ----------
DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DASHBOARD_SECRET = os.getenv("DASHBOARD_SECRET", "change-me")

# Public URL of the web dashboard (used by /help). Set via env DASHBOARD_BASE_URL.
DASHBOARD_BASE_URL = os.getenv(
    "DASHBOARD_BASE_URL", "https://exo-mek-dashboard.onrender.com"
).rstrip("/")

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
