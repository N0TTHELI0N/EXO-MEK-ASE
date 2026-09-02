import re
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks
from discord import app_commands

import guild_settings
import nitrado
import bot_i18n
import config
from security import sanitize_rcon_name, sanitize_rcon_input


IP_PARSE_INTERVAL = 60  # seconds

# ARK log lines commonly include connection attempts like:
#   [2024.05.01-12.00.00:000][ 0]Warning: [Bonjour] ...
#   Command 'GetSteamAuthTicket' ...
# Connection / Steam join lines:
#   ... /192.168.1.1:port  connecting ...
#   log: [Timestamp][ 0]Log: Steam Authenticated: 01234567890123456, 192.168.1.1:27000 ...
# Robust-but-tolerant: capture an IPv4 that appears in a join/auth context.
_IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")
_JOIN_MARKERS = ("steam auth", "authenticated", "connecting", "connection", "joined", "login",
                 "uuid", "player", "loginid", "netconnection")

# Admin-action keywords to flag in log categories (for abuse review).
ABUSE_KEYWORDS = ["ban", "kick", "wipe", "giveitem", "grant", "destroy", "set", "kill",
                  "delete", "remove", "cheat", "force", "spawn", "fog", "addpoints"]


def _log_admin(guild_id, sub_type, user, target=None, details=None):
    guild_settings.log_admin_action(
        guild_id, user.id if user else None, str(user) if user else None,
        sub_type, target, details,
    )


async def _asyncio_to_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


class AntiAbuse(commands.Cog):
    """Admin-abuse auditing + automatic IP harvesting from server logs."""

    def __init__(self, bot):
        self.bot = bot
        self._last_log_pos = {}
        self.ip_monitor.start()

    def cog_unload(self):
        self.ip_monitor.cancel()

    # ── Background: harvest IPs from ARK server logs ──────────
    @tasks.loop(seconds=IP_PARSE_INTERVAL)
    async def ip_monitor(self):
        for guild in self.bot.guilds:
            if not guild_settings.get_bool_setting(guild.id, "anti_abuse_ip_auto", False):
                continue
            client = nitrado.get_client(guild.id)
            if client is None:
                continue
            try:
                raw = await _asyncio_to_thread(client.get_logs, 300)
            except Exception:
                continue
            lines = (raw or "").splitlines()
            # Only process newly-seen lines (naive cursor).
            last = self._last_log_pos.get(guild.id)
            start = 0
            if last is not None:
                try:
                    start = lines.index(last) + 1
                except ValueError:
                    start = 0
            new_lines = lines[start:]
            if lines:
                self._last_log_pos[guild.id] = lines[-1].strip()

            for line in new_lines:
                text = (line or "").strip()
                low = text.lower()
                if not any(m in low for m in _JOIN_MARKERS):
                    continue
                match = _IP_RE.search(text)
                if not match:
                    continue
                ip = match.group(1)
                # Try to extract a player-ish name from the same line.
                player = self._guess_player(text)
                if not player:
                    continue
                guild_settings.add_ip_record(guild.id, player, ip, source="log")
                # Auto alt-detection: check whether this IP is already linked to a
                # different tracked player. If so, this looks like an alt joining.
                alts = guild_settings.find_alts(guild.id, player)
                for alt in alts:
                    if alt != player:
                        await self._notify_alt(guild, player, ip, alt)

    async def _notify_alt(self, guild, player, ip, alt):
        """Push an alt-account alert to the configured anti-abuse log channel."""
        try:
            ch_id = guild_settings.get_setting(guild.id, "anti_abuse_log_channel_id")
            if ch_id:
                ch = guild.get_channel(int(ch_id))
                if ch:
                    embed = discord.Embed(
                        title="🚨 Possible Alt Account Detected",
                        description=(
                            f"**{player}** joined from IP `{ip}` which is also linked to "
                            f"**{alt}**.\n\nPossibly the same person playing on an alt account."
                        ),
                        color=discord.Color.yellow(),
                    )
                    embed.set_footer(text="Anti-Abuse auto-detection")
                    await ch.send(embed=embed)
        except Exception as e:
            print(f"[AntiAbuse] Alt notify error: {e}")

    @ip_monitor.before_loop
    async def before_ip_monitor(self):
        await self.bot.wait_until_ready()

    @staticmethod
    def _guess_player(line: str):
        # Strip timestamps/prefixes, look for a quoted name or a name before an IP/port.
        candidate = None
        q = re.search(r"Player['\" ]+([^'\"]+)", line, re.I)
        if q:
            candidate = q.group(1).strip()
        if not candidate:
            q = re.search(r"'([A-Za-z0-9_.\-\s]{2,30})'", line)
            if q:
                candidate = q.group(1).strip()
        if not candidate:
            q = re.search(r"\[\s*(\d{1,3}(?:\.\d{1,3}){3})[^\]]*\](.+)", line)
            if q:
                candidate = q.group(2).strip().split(":")[0].strip()
        return sanitize_rcon_name(candidate)[:60] if candidate else None

    # ============================================================
    #  COMMANDS
    # ============================================================

    @app_commands.command(name="anti-abuse-log", description="Show the anti-abuse audit log of admin actions")
    @app_commands.describe(limit="Number of entries to show")
    async def anti_abuse_log(self, interaction: discord.Interaction, limit: int = 20):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        logs = guild_settings.get_admin_action_logs(interaction.guild_id, limit=min(max(limit, 1), 50))
        if not logs:
            return await interaction.response.send_message("No admin actions logged yet.", ephemeral=True)

        lines = []
        for lg in logs:
            actor = lg["admin_name"] or f"<@{lg['admin_user_id']}>"
            target = lg["target"] or ""
            ts = lg["created_at"].strftime("%Y-%m-%d %H:%M") if lg["created_at"] else "?"
            lines.append(f"`{ts}` **{lg['action']}** by {actor} {f'on **{target}**' if target else ''}")
        embed = discord.Embed(title="🛡️ Anti-Abuse Audit Log", description="\n".join(lines[:25]), color=discord.Color.dark_red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="anti-abuse-set-ip-auto", description="Enable/disable automatic IP harvesting from server logs")
    @app_commands.describe(enabled="Enable or disable")
    async def anti_abuse_set_ip_auto(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_setting(interaction.guild_id, "anti_abuse_ip_auto", enabled)
        await interaction.response.send_message(
            f"📡 Automatic IP harvesting **{'enabled' if enabled else 'disabled'}.**",
            ephemeral=True,
        )

    @app_commands.command(name="anti-abuse-status", description="Show anti-abuse system status")
    async def anti_abuse_status(self, interaction: discord.Interaction):
        auto = guild_settings.get_bool_setting(interaction.guild_id, "anti_abuse_ip_auto", False)
        count = guild_settings.get_admin_action_count(interaction.guild_id)
        ip_bans = len(guild_settings.get_ip_bans(interaction.guild_id))
        ip_records = len(guild_settings.get_ip_records(interaction.guild_id))
        lines = [
            f"**Auto IP harvesting:** {'✅ On' if auto else '❌ Off'}",
            f"**Admin actions logged:** {count}",
            f"**IP records:** {ip_records}",
            f"**IP bans:** {ip_bans}",
        ]
        embed = discord.Embed(title="🛡️ Anti-Abuse", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(AntiAbuse(bot))
