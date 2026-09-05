import re
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord import app_commands

import guild_settings
import nitrado
import bot_i18n
import config
from security import sanitize_rcon_name, sanitize_rcon_input


async def _asyncio_to_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def _log(guild_id, log_type, sub_type, user, player, cmd=None, details=None):
    guild_settings.log_admin_action(
        guild_id, user.id if user else None, str(user) if user else None,
        sub_type, player, details,
    )


def _fmt_seconds(seconds):
    seconds = int(seconds or 0)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


class PlayerOps(commands.Cog):
    """Advanced player info, alt detection, and IP-based moderation."""

    def __init__(self, bot):
        self.bot = bot

    # ============================================================
    #  ADVANCED PLAYER INFO
    # ============================================================

    @app_commands.command(name="player-info", description="Advanced info about an in-game player (online status, tribe, punishment history, IPs)")
    @app_commands.describe(player="In-game player name", discord_user="Optional Discord user to include account details")
    async def player_info(self, interaction: discord.Interaction, player: str, discord_user: discord.User = None):
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id

        # In-game online status via Nitrado
        client = nitrado.get_client(guild_id)
        online = None
        player_obj = None
        if client:
            try:
                players = await _asyncio_to_thread(client.get_player_list)
                player_obj = next((p for p in players if (p.get("name") or "").lower() == player.lower()), None)
                online = bool(player_obj and player_obj.get("online"))
            except Exception:
                online = None

        # Tribe
        tribe = guild_settings.get_player_tribe(guild_id, player)

        # Punishment history
        punishments = guild_settings.get_punishments(guild_id, player)
        has_any = guild_settings.is_blacklisted(guild_id, player) or punishments

        # Warnings
        warn_count = guild_settings.get_active_warning_count(guild_id, player)

        # Recorded IPs
        ips = guild_settings.get_player_ips(guild_id, player_name=player)

        embed = discord.Embed(title=f"🧍 {player}", color=discord.Color.blurple())
        if online is True:
            status = bot_i18n.t(guild_id, "player_online")
        elif online is False:
            status = bot_i18n.t(guild_id, "player_offline")
        else:
            status = bot_i18n.t(guild_id, "player_unknown")
        embed.add_field(name=bot_i18n.t(guild_id, "field_in_game_status"), value=f"{status}", inline=True)
        embed.add_field(name=bot_i18n.t(guild_id, "field_tribe"), value=tribe or bot_i18n.t(guild_id, "none_value"), inline=True)
        embed.add_field(name=bot_i18n.t(guild_id, "field_active_warnings"), value=str(warn_count), inline=True)

        if player_obj:
            embed.add_field(name=bot_i18n.t(guild_id, "field_player_id"), value=str(player_obj.get("id", "?")), inline=True)
            embed.add_field(name=bot_i18n.t(guild_id, "field_ping"), value=f"{player_obj.get('ping', 0)}ms", inline=True)

        if punishments:
            recent = "\n".join(
                f"#{r[0]} {r[4]} ({'✅' if r[10] else '⏳'}{' 🚫' if r[11] else ''})"
                for r in punishments[:8]
            )
            embed.add_field(name=bot_i18n.t(guild_id, "field_punishments", count=len(punishments)), value=recent or bot_i18n.t(guild_id, "none_value"), inline=False)

        if ips:
            ip_list = "\n".join(f"{r['ip']} • {r['source']}" for r in ips[:8])
            embed.add_field(name=bot_i18n.t(guild_id, "field_recorded_ips"), value=ip_list or bot_i18n.t(guild_id, "none_value"), inline=False)

        if discord_user:
            embed.add_field(name=bot_i18n.t(guild_id, "field_discord_account"), value=f"{discord_user.mention} (`{discord_user.id}`)", inline=False)

        embed.set_footer(text=bot_i18n.t(guild_id, "footer_premium_license"))
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ============================================================
    #  ALT DETECTION
    # ============================================================

    @app_commands.command(name="check-alts", description="Detect possible alt accounts sharing an IP with a player")
    @app_commands.describe(player="In-game player name")
    async def check_alts(self, interaction: discord.Interaction, player: str):
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        alts = guild_settings.find_alts(interaction.guild_id, player)
        if not alts:
            return await interaction.response.send_message(
                bot_i18n.t(interaction.guild_id, "no_alts_detected", player=player),
                ephemeral=True,
            )

        lines = [bot_i18n.t(interaction.guild_id, "alts_detected", player=player)]
        for name in alts:
            banned = bot_i18n.t(interaction.guild_id, "alt_banned") if (guild_settings.is_blacklisted(interaction.guild_id, name) or guild_settings.get_punishments(interaction.guild_id, name)) else bot_i18n.t(interaction.guild_id, "alt_clean")
            lines.append(f"• **{name}** — {banned}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ============================================================
    #  IP BAN / UNBAN
    # ============================================================

    @app_commands.command(name="ip-ban", description="Ban an IP address (records it + bans the linked account, kicks player)")
    @app_commands.describe(ip="IP address to ban", player="Linked player name (optional)", reason="Reason")
    async def ip_ban(self, interaction: discord.Interaction, ip: str, player: str = None, reason: str = "IP ban"):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        ip = ip.strip()
        added = guild_settings.add_ip_ban(interaction.guild_id, ip, reason, interaction.user.id, player_name=player)
        msg = bot_i18n.t(interaction.guild_id, "ip_banned", ip=ip) if added else bot_i18n.t(interaction.guild_id, "ip_already_banned", ip=ip)

        # If a linked player name is given, also kick + ban their account via RCON
        if player:
            safe = sanitize_rcon_name(player)
            kick = await _asyncio_to_thread(nitrado.send_rcon, interaction.guild_id, f"KickPlayer {safe}")
            ban = await _asyncio_to_thread(nitrado.send_rcon, interaction.guild_id, f"Ban {safe}")
            guild_settings.add_punishment(interaction.guild_id, player, "ban", f"IP ban: {reason}", interaction.user.id)
            if kick or ban is not None:
                msg += bot_i18n.t(interaction.guild_id, "ip_linked_account_kicked", player=player)

        _log(interaction.guild_id, "ip_ban", "ip_ban", interaction.user, player, details={"ip": ip, "reason": reason})
        await interaction.followup.send(msg)

    @app_commands.command(name="ip-unban", description="Unban an IP address")
    @app_commands.describe(ip="IP address to unban")
    async def ip_unban(self, interaction: discord.Interaction, ip: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        ip = ip.strip()
        removed = False
        for ban in guild_settings.get_ip_bans(interaction.guild_id):
            if ban["ip"] == ip:
                removed = guild_settings.remove_ip_ban(ban["id"], interaction.guild_id) or removed
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "ip_unbanned", ip=ip) if removed else bot_i18n.t(interaction.guild_id, "ip_not_banned", ip=ip), ephemeral=True,
        )

    @app_commands.command(name="ip-ban-list", description="List all banned IP addresses")
    async def ip_ban_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        bans = guild_settings.get_ip_bans(interaction.guild_id)
        if not bans:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "no_ip_bans"), ephemeral=True)
        lines = []
        for b in bans:
            pname = f" ({b['player_name']})" if b.get("player_name") else ""
            lines.append(f"#{b['id']} `{b['ip']}`{pname} • {b['reason'] or ''}")
        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "banned_ips_title"), description="\n".join(lines[:20]), color=discord.Color.dark_red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add-ip", description="Manually record a player's IP address for alt detection")
    @app_commands.describe(player="In-game player name", ip="IP address", player_id="Optional Steam/player ID")
    async def add_ip(self, interaction: discord.Interaction, player: str, ip: str, player_id: str = None):
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.add_ip_record(interaction.guild_id, player.strip(), ip.strip(), player_id=player_id, source="manual")
        _log(interaction.guild_id, "ip", "add_ip", interaction.user, player, details={"ip": ip})
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "ip_recorded", ip=ip, player=player), ephemeral=True)


async def setup(bot):
    await bot.add_cog(PlayerOps(bot))
