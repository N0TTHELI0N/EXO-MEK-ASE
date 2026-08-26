# rcon_helper.py - Shared RCON client for all cogs
# Reads per-guild RCON config from guild_settings

from rcon import Client as RconClient
import guild_settings


def send_rcon(guild_id: int, command: str) -> str | None:
    """Send an RCON command to the guild's ARK server. Returns response or None."""
    cfg = guild_settings.get_rcon_config(guild_id)
    host = cfg.get("host")
    password = cfg.get("password")
    port = cfg.get("port", 29015)

    if not host or not password:
        print(f"RCON not configured for guild {guild_id}")
        return None

    try:
        with RconClient(host, port, passwd=password) as client:
            return client.run(command)
    except Exception as e:
        safe_host = host.split(':')[0] if host else "unknown"
        print(f"RCON error (guild {guild_id}, host={safe_host}): {type(e).__name__}")
        return None
