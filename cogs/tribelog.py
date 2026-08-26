import os
import re
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone
import guild_settings
import config
import bot_i18n


TRIBE_LOG_PATTERN = re.compile(r"Tribe called '(.+?)' added a member")

ALLOWED_TRIBELOG_COLUMNS = {"enabled", "channel_id", "log_source", "log_path", "nitrado_token", "nitrado_user_id", "nitrado_service_id"}


def _init_tribelog_db():
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_log_config (
                    guild_id        BIGINT PRIMARY KEY,
                    enabled         BOOLEAN DEFAULT FALSE,
                    channel_id      BIGINT,
                    log_source      TEXT DEFAULT 'file',
                    log_path        TEXT DEFAULT '',
                    nitrado_token   TEXT DEFAULT '',
                    nitrado_user_id TEXT DEFAULT '',
                    nitrado_service_id TEXT DEFAULT ''
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS known_tribes (
                    guild_id    BIGINT NOT NULL,
                    tribe_name  TEXT NOT NULL,
                    tribe_game_id TEXT DEFAULT '',
                    PRIMARY KEY (guild_id, tribe_name)
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _get_tribelog_config(guild_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT enabled, channel_id, log_source, log_path FROM tribe_log_config WHERE guild_id = %s", (guild_id,))
            row = cur.fetchone()
            if row:
                return {"enabled": row[0], "channel_id": row[1], "log_source": row[2], "log_path": row[3]}
            return None
    finally:
        conn.close()


def _update_tribelog_config(guild_id: int, **kwargs):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tribe_log_config (guild_id) VALUES (%s)
                ON CONFLICT (guild_id) DO NOTHING
            """, (guild_id,))
            for key, val in kwargs.items():
                if key not in ALLOWED_TRIBELOG_COLUMNS:
                    raise ValueError(f"Invalid column: {key}")
                cur.execute(f"UPDATE tribe_log_config SET {key} = %s WHERE guild_id = %s", (val, guild_id))
        conn.commit()
    finally:
        conn.close()


def _get_known_tribes(guild_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tribe_name FROM known_tribes WHERE guild_id = %s", (guild_id,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _add_known_tribe(guild_id: int, tribe_name: str):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO known_tribes (guild_id, tribe_name) VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (guild_id, tribe_name))
        conn.commit()
    finally:
        conn.close()


async def tribe_autocomplete(interaction: discord.Interaction, current: str):
    tribes = _get_known_tribes(interaction.guild_id)
    return [
        app_commands.Choice(name=t, value=t)
        for t in tribes if current.lower() in t.lower()
    ][:25]


# ── Cog ─────────────────────────────────────────────────────

class Tribelog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _init_tribelog_db()
        self.known_tribes_cache: dict[int, set[str]] = {}
        self._load_cache()

    def _load_cache(self):
        conn = guild_settings.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT guild_id, tribe_name FROM known_tribes")
                for gid, name in cur.fetchall():
                    self.known_tribes_cache.setdefault(gid, set()).add(name)
        finally:
            conn.close()

    # ── /set-tribelog-enabled ────────────────────────────────
    @app_commands.command(name="set-tribelog-enabled", description="Enable or disable tribe log monitoring (Admin only)")
    @app_commands.describe(enabled="Enable or disable")
    async def set_tribelog_enabled(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        _update_tribelog_config(interaction.guild_id, enabled=enabled)
        status = "enabled" if enabled else "disabled"
        await interaction.response.send_message(f"✅ Tribe log monitoring **{status}**.", ephemeral=True)

    # ── /set-tribe-log-channel ───────────────────────────────
    @app_commands.command(name="set-tribe-log-channel", description="Set the channel for tribe log alerts (Admin only)")
    @app_commands.describe(channel="Channel for tribe log messages")
    async def set_tribe_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        _update_tribelog_config(interaction.guild_id, channel_id=channel.id)
        await interaction.response.send_message(f"✅ Tribe log channel set to {channel.mention}", ephemeral=True)

    # ── /set-tribe-log-source ────────────────────────────────
    @app_commands.command(name="set-tribe-log-source", description="Configure tribe log source (Admin only)")
    @app_commands.describe(source="Source type: file or nitrado", log_path="Log file path (if file source)")
    @app_commands.choices(source=[
        app_commands.Choice(name="Local File", value="file"),
        app_commands.Choice(name="Nitrado API", value="nitrado"),
    ])
    async def set_tribe_log_source(self, interaction: discord.Interaction, source: app_commands.Choice[str], log_path: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        _update_tribelog_config(interaction.guild_id, log_source=source.value, log_path=log_path)
        await interaction.response.send_message(f"✅ Tribe log source set to **{source.value}**.", ephemeral=True)

    # ── /set-tribe-log-config ────────────────────────────────
    @app_commands.command(name="set-tribe-log-config", description="Set Nitrado credentials for tribe log (Admin only)")
    @app_commands.describe(api_token="Nitrado API token", user_id="User ID", service_id="Service ID")
    async def set_tribe_log_config(self, interaction: discord.Interaction, api_token: str = "", user_id: str = "", service_id: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        kwargs = {}
        if api_token:
            kwargs["nitrado_token"] = api_token
        if user_id:
            kwargs["nitrado_user_id"] = user_id
        if service_id:
            kwargs["nitrado_service_id"] = service_id
        _update_tribelog_config(interaction.guild_id, **kwargs)
        await interaction.response.send_message("✅ Tribe log Nitrado config saved.", ephemeral=True)

    # ── /add-tribe-name ──────────────────────────────────────
    @app_commands.command(name="add-tribe-name", description="Add a tribe name to monitor (Admin only)")
    @app_commands.describe(tribe_name="Tribe name")
    async def add_tribe_name(self, interaction: discord.Interaction, tribe_name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        _add_known_tribe(interaction.guild_id, tribe_name)
        self.known_tribes_cache.setdefault(interaction.guild_id, set()).add(tribe_name)
        await interaction.response.send_message(f"✅ **{tribe_name}** added to monitoring list.", ephemeral=True)

    # ── /view-tribelog ───────────────────────────────────────
    @app_commands.command(name="view-tribelog", description="View monitored tribes and log config")
    @app_commands.describe(tribe_name="Look up a specific tribe")
    @app_commands.autocomplete(tribe_name=tribe_autocomplete)
    async def view_tribelog(self, interaction: discord.Interaction, tribe_name: str = ""):
        config_data = _get_tribelog_config(interaction.guild_id) or {}
        tribes = _get_known_tribes(interaction.guild_id)

        lines = [
            f"**Enabled:** {config_data.get('enabled', False)}",
            f"**Channel:** <#{config_data.get('channel_id', 0)}>" if config_data.get("channel_id") else "**Channel:** Not set",
            f"**Source:** {config_data.get('log_source', 'file')}",
            f"**Monitored tribes ({len(tribes)}):**",
        ]
        for t in tribes:
            lines.append(f"  • {t}")

        if tribe_name:
            lines.append(f"\n**Tribe '{tribe_name}' status:** Monitored")

        embed = discord.Embed(title="📋 Tribe Log Config", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Tribelog(bot))
