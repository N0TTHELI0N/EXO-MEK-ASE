"""
command_defaults.py - Curated "current" display for commands.

Used by the dashboard's Customize Text -> Command Embeds live preview so it
shows what a command currently displays (title / color) before any override is
written. Descriptions come from commands_manifest.

Keep in sync with the actual embeds built in cogs/.
"""

# Default embed colors that mirror each cog's embed construction.
DEFAULT_EMBED_COLOR = "#5865F2"  # discord.Color.blurple()

# command name -> {"title": str, "color": hex, "plain": str}
# Only embed-based commands with a recognizable static title are listed.
# Everything else falls back to default color + manifest description.
DEFAULTS = {
    "help": {"title": "📖 Command Help", "color": DEFAULT_EMBED_COLOR},
    "automod-list-words": {"title": "🔍 Automod Custom Words", "color": DEFAULT_EMBED_COLOR},
    "chat-bridge-status": {"title": "💬 Chat Bridge", "color": DEFAULT_EMBED_COLOR},
    "auto-chat-list": {"title": "In-Game Chat Triggers", "color": "#C0392B"},  # dark_red
    "auto-chat-clear": {"title": "In-Game Chat Triggers", "color": "#C0392B"},
    "custom-list": {"title": "⚙️ Custom Commands", "color": DEFAULT_EMBED_COLOR},
    "ark-command": {"title": "⚙️ Custom Commands", "color": DEFAULT_EMBED_COLOR},
    "leaderboard": {"title": "🏆 Leaderboard", "color": DEFAULT_EMBED_COLOR},
    "backup-list": {"title": "📦 Nitrado Backups", "color": DEFAULT_EMBED_COLOR},
    "top-players": {"title": "🏆 Top Players", "color": DEFAULT_EMBED_COLOR},
    "server-status": {"title": "🖥️ Server Status", "color": DEFAULT_EMBED_COLOR},
    "warnings": {"title": "Warnings for <player>", "color": "#FFA500"},  # orange
    "punishment-history": {"title": "Punishment History: <player>", "color": "#E74C3C"},  # red
    "blacklist-list": {"title": "Blacklisted Players", "color": "#992D22"},  # dark_red
    "set-tribe-log-config": {"title": "📜 Tribe Log Config", "color": DEFAULT_EMBED_COLOR},
    "view-tribelog": {"title": "📜 Tribe Log", "color": DEFAULT_EMBED_COLOR},
    "whitelist": {"title": "📜 Whitelist", "color": DEFAULT_EMBED_COLOR},
    "wl-list": {"title": "📜 Whitelist", "color": DEFAULT_EMBED_COLOR},
    "view-command-permissions": {"title": "🔑 Command Permissions", "color": DEFAULT_EMBED_COLOR},
    "view-guilds": {"title": "🏛️ Guilds", "color": DEFAULT_EMBED_COLOR},
}


def get_command_default(command_name: str) -> dict:
    """Return {title, color} for a command's current/default embed display."""
    return DEFAULTS.get(command_name, {"title": "", "color": DEFAULT_EMBED_COLOR})


def get_command_default_description(command_name: str) -> str:
    """Return the command's built-in description from commands_manifest."""
    import commands_manifest
    for name, _cat, desc in commands_manifest.COMMANDS:
        if name == command_name:
            return desc
    return ""