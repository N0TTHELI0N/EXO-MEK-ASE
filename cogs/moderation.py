import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
import aiohttp
import guild_settings
import bot_i18n
import config
import nitrado
from security import sanitize_rcon_name, sanitize_rcon_input


# ============================================================
#  HELPERS
# ============================================================

def get_conn():
    return guild_settings.get_conn()


async def _send_rcon(guild_id: int, command: str) -> str | None:
    return nitrado.send_rcon(guild_id, command)


def _get_nitrado_headers(guild_id: int):
    cfg = guild_settings.get_nitrado_config(guild_id)
    token = cfg.get("api_token") or config.NITRADO_API_TOKEN
    user_id = cfg.get("user_id") or config.NITRADO_USER_ID
    service_id = cfg.get("service_id") or config.NITRADO_SERVICE_ID
    if not token:
        return None, None
    return {"Authorization": f"Bearer {token}"}, service_id


def _log(guild_id, log_type, sub_type, user, player, cmd=None, details=None):
    guild_settings.log_action(
        guild_id, log_type,
        user_id=user.id if user else None,
        user_name=str(user) if user else None,
        player_name=player,
        command=cmd,
        sub_type=sub_type,
        details=details,
    )


async def _save_evidence(interaction, punishment_id):
    """Save attached files as evidence."""
    for attachment in interaction.message.attachments if interaction.message else []:
        ext = os.path.splitext(attachment.filename)[1]
        fname = f"{punishment_id}_{attachment.filename}"
        evidence_dir = os.path.join("evidence", str(interaction.guild_id), str(punishment_id))
        os.makedirs(evidence_dir, exist_ok=True)
        fpath = os.path.join(evidence_dir, fname)
        await attachment.save(fpath)
        guild_settings.add_evidence(
            punishment_id, interaction.guild_id,
            fname, attachment.filename, attachment.size, interaction.user.id,
        )


# ============================================================
#  COG
# ============================================================

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_tempbans.start()
        self.cleanup_warnings.start()

    def cog_unload(self):
        self.check_tempbans.cancel()
        self.cleanup_warnings.cancel()

    # ── Background: auto-unban expired tempbans ──────────────
    @tasks.loop(minutes=5)
    async def check_tempbans(self):
        expired = guild_settings.get_expired_tempbans()
        for pid, guild_id, player_name, player_id in expired:
            safe_name = sanitize_rcon_name(player_name)
            result = await _send_rcon(guild_id, f"UnBan {safe_name}")
            if result is not None:
                guild_settings.mark_action_done(pid)
                guild = self.bot.get_guild(guild_id)
                if guild:
                    log_ch = guild_settings.get_setting(guild_id, "punishment_log_channel_id")
                    if log_ch:
                        ch = guild.get_channel(log_ch)
                        if ch:
                            await ch.send(f"✅ **{player_name}** automatically unbanned (tempban expired).")
                _log(guild_id, "punishment", "tempban_unban", None, player_name)

    @check_tempbans.before_loop
    async def before_tempbans(self):
        await self.bot.wait_until_ready()

    # ── Background: cleanup expired warnings ─────────────────
    @tasks.loop(minutes=10)
    async def cleanup_warnings(self):
        guild_settings.cleanup_expired_warnings()

    @cleanup_warnings.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ============================================================
    #  WARNINGS
    # ============================================================

    @app_commands.command(name="warn", description="Warn a player")
    @app_commands.describe(player="Player name", reason="Reason for warning")
    async def warn(self, interaction: discord.Interaction, player: str, reason: str):
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        warning_id = guild_settings.add_warning(interaction.guild_id, player, reason, interaction.user.id)
        count = guild_settings.get_active_warning_count(interaction.guild_id, player)
        _log(interaction.guild_id, "punishment", "warn", interaction.user, player, details={"reason": reason, "warning_count": count})

        threshold = guild_settings.get_setting(interaction.guild_id, "warning_threshold", 3)
        auto_punishment = guild_settings.get_setting(interaction.guild_id, "warning_punishment", "ban")

        msg = f"⚠️ **{player}** warned. Reason: {reason}\nActive warnings: **{count}/{threshold}**"

        if count >= threshold:
            punishment_result = await self._execute_auto_punishment(interaction, player, auto_punishment)
            if punishment_result:
                msg += f"\n{punishment_result}"

        await interaction.response.send_message(msg)

    @app_commands.command(name="tempwarn", description="Give a temporary warning that expires")
    @app_commands.describe(player="Player name", reason="Reason", duration_hours="Hours until expiry")
    async def tempwarn(self, interaction: discord.Interaction, player: str, reason: str, duration_hours: int = 72):
        if not interaction.user.guild_permissions.moderate_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        warning_id = guild_settings.add_warning(interaction.guild_id, player, reason, interaction.user.id, expires_at=expires_at)
        count = guild_settings.get_active_warning_count(interaction.guild_id, player)
        _log(interaction.guild_id, "punishment", "warn", interaction.user, player, details={"reason": reason, "expires_hours": duration_hours, "warning_count": count})

        threshold = guild_settings.get_setting(interaction.guild_id, "warning_threshold", 3)
        msg = f"⚠️ **{player}** temp-warned for **{duration_hours}h**. Reason: {reason}\nActive warnings: **{count}/{threshold}**"

        if count >= threshold:
            auto_punishment = guild_settings.get_setting(interaction.guild_id, "warning_punishment", "ban")
            punishment_result = await self._execute_auto_punishment(interaction, player, auto_punishment)
            if punishment_result:
                msg += f"\n{punishment_result}"

        await interaction.response.send_message(msg)

    @app_commands.command(name="warnings", description="View warnings for a player")
    @app_commands.describe(player="Player name")
    async def warnings(self, interaction: discord.Interaction, player: str):
        rows = guild_settings.get_warnings(interaction.guild_id, player)
        if not rows:
            return await interaction.response.send_message(f"No warnings found for **{player}**.", ephemeral=True)

        lines = []
        for wid, reason, warned_by, warned_at, expires_at, active in rows:
            status = "✅ Active" if active else "❌ Expired/Cleared"
            exp = f" (expires {expires_at.strftime('%Y-%m-%d %H:%M')})" if expires_at else ""
            lines.append(f"#{wid} | {status}{exp} | {reason} | <@{warned_by}> | {warned_at.strftime('%Y-%m-%d %H:%M')}")

        embed = discord.Embed(title=f"Warnings for {player}", description="\n".join(lines[:20]), color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="clear-warnings", description="Clear all warnings for a player")
    @app_commands.describe(player="Player name")
    async def clear_warnings(self, interaction: discord.Interaction, player: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.clear_warnings(interaction.guild_id, player)
        _log(interaction.guild_id, "punishment", "warn", interaction.user, player, details={"action": "clear_all"})
        await interaction.response.send_message(f"✅ All warnings cleared for **{player}**.")

    @app_commands.command(name="remove-warning", description="Remove a specific warning by ID")
    @app_commands.describe(warning_id="Warning ID from /warnings")
    async def remove_warning(self, interaction: discord.Interaction, warning_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.remove_warning(warning_id)
        await interaction.response.send_message(f"✅ Warning #{warning_id} removed.")

    # ============================================================
    #  PUNISHMENTS
    # ============================================================

    @app_commands.command(name="punish-ban", description="Ban a player with optional evidence")
    @app_commands.describe(player="Player name", reason="Reason", scope="Ban player only or whole tribe")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Player only", value="player"),
        app_commands.Choice(name="Whole tribe", value="tribe"),
    ])
    async def punish_ban(self, interaction: discord.Interaction, player: str, reason: str,
                         scope: app_commands.Choice[str] = None):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer()
        scope_val = scope.value if scope else "player"
        players = await self._get_scope_players(interaction.guild_id, player, scope_val)

        results = []
        for p_name, p_id in players:
            safe_name = sanitize_rcon_name(p_name)
            result = await _send_rcon(interaction.guild_id, f"Ban {safe_name}")
            punishment_id = guild_settings.add_punishment(
                interaction.guild_id, p_name, "ban", reason, interaction.user.id,
                scope=scope_val, player_id=p_id, tribe_name=player if scope_val == "tribe" else None,
            )
            if interaction.message and interaction.message.attachments:
                await _save_evidence(interaction, punishment_id)
            _log(interaction.guild_id, "punishment", "ban", interaction.user, p_name, details={"reason": reason, "scope": scope_val})
            results.append(f"🔨 **{p_name}** banned." if result else f"❌ Failed to ban **{p_name}** (command error)")

        await interaction.followup.send("\n".join(results))

    @app_commands.command(name="punish-tempban", description="Temporarily ban a player")
    @app_commands.describe(player="Player name", duration_hours="Ban duration in hours", reason="Reason", scope="Player or whole tribe")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Player only", value="player"),
        app_commands.Choice(name="Whole tribe", value="tribe"),
    ])
    async def punish_tempban(self, interaction: discord.Interaction, player: str, duration_hours: int,
                             reason: str, scope: app_commands.Choice[str] = None):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer()
        scope_val = scope.value if scope else "player"
        players = await self._get_scope_players(interaction.guild_id, player, scope_val)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=duration_hours)

        results = []
        for p_name, p_id in players:
            safe_name = sanitize_rcon_name(p_name)
            result = await _send_rcon(interaction.guild_id, f"Ban {safe_name}")
            punishment_id = guild_settings.add_punishment(
                interaction.guild_id, p_name, "tempban", reason, interaction.user.id,
                scope=scope_val, player_id=p_id, tribe_name=player if scope_val == "tribe" else None,
                expires_at=expires_at,
            )
            if interaction.message and interaction.message.attachments:
                await _save_evidence(interaction, punishment_id)
            if result:
                guild_settings.mark_punishment_executed(punishment_id)
            _log(interaction.guild_id, "punishment", "tempban", interaction.user, p_name, details={"reason": reason, "hours": duration_hours, "scope": scope_val})
            results.append(f"🔨 **{p_name}** temp-banned for **{duration_hours}h**." if result else f"❌ Failed to ban **{p_name}**")

        await interaction.followup.send("\n".join(results))

    @app_commands.command(name="punish-wipe", description="Wipe a player's structures, dinos, or both")
    @app_commands.describe(player="Player name", wipe_type="What to wipe", reason="Reason", scope="Player or whole tribe")
    @app_commands.choices(
        wipe_type=[
            app_commands.Choice(name="Structures only", value="wipe_structures"),
            app_commands.Choice(name="Dinos only", value="wipe_dinos"),
            app_commands.Choice(name="Both", value="wipe_both"),
        ],
        scope=[
            app_commands.Choice(name="Player only", value="player"),
            app_commands.Choice(name="Whole tribe", value="tribe"),
        ],
    )
    async def punish_wipe(self, interaction: discord.Interaction, player: str,
                          wipe_type: app_commands.Choice[str], reason: str,
                          scope: app_commands.Choice[str] = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer()
        scope_val = scope.value if scope else "player"
        players = await self._get_scope_players(interaction.guild_id, player, scope_val)
        wipe_val = wipe_type.value

        results = []
        for p_name, p_id in players:
            safe_name = sanitize_rcon_name(p_name)
            if wipe_val in ("wipe_dinos", "wipe_both"):
                await _send_rcon(interaction.guild_id, f"DestroyAllDinos {safe_name}")
            if wipe_val in ("wipe_structures", "wipe_both"):
                await _send_rcon(interaction.guild_id, f"BanPlayer {safe_name}")
                await _send_rcon(interaction.guild_id, f"UnBanPlayer {safe_name}")

            punishment_id = guild_settings.add_punishment(
                interaction.guild_id, p_name, wipe_val, reason, interaction.user.id,
                scope=scope_val, player_id=p_id, tribe_name=player if scope_val == "tribe" else None,
            )
            if interaction.message and interaction.message.attachments:
                await _save_evidence(interaction, punishment_id)
            _log(interaction.guild_id, "punishment", wipe_val, interaction.user, p_name, details={"reason": reason, "scope": scope_val})
            results.append(f"🗑️ **{p_name}** {wipe_val.replace('_', ' ')} done.")

        await interaction.followup.send("\n".join(results))

    @app_commands.command(name="punishment-history", description="View punishment history for a player")
    @app_commands.describe(player="Player name")
    async def punishment_history(self, interaction: discord.Interaction, player: str):
        rows = guild_settings.get_punishments(interaction.guild_id, player)
        if not rows:
            return await interaction.response.send_message(f"No punishments found for **{player}**.", ephemeral=True)

        lines = []
        for r in rows:
            pid, pname, pid_val, tribe, ptype, reason, issued_by, scp, issued_at, exp, executed, appealed = r
            status = "✅ Executed" if executed else "⏳ Pending"
            if appealed:
                status = "🚫 Appealed"
            exp_str = f" (expires {exp.strftime('%Y-%m-%d %H:%M')})" if exp else ""
            lines.append(f"#{pid} | {ptype} | {status}{exp_str} | {reason} | <@{issued_by}> | {issued_at.strftime('%Y-%m-%d %H:%M')}")

        embed = discord.Embed(title=f"Punishment History: {player}", description="\n".join(lines[:20]), color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ============================================================
    #  BLACKLIST
    # ============================================================

    @app_commands.command(name="blacklist", description="Permanently blacklist a player (also bans them on the server)")
    @app_commands.describe(player="Player name", reason="Reason", tribe="Whole tribe (optional)")
    async def blacklist(self, interaction: discord.Interaction, player: str, reason: str, tribe: str = None):
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer()
        targets = [(player, None)]
        if tribe:
            members = guild_settings.get_tribe_members(interaction.guild_id, tribe)
            targets = [(m[0], m[1]) for m in members] or [(player, None)]

        results = []
        for p_name, p_id in targets:
            safe_name = sanitize_rcon_name(p_name)
            if not guild_settings.is_blacklisted(interaction.guild_id, p_name):
                await _send_rcon(interaction.guild_id, f"Ban {safe_name}")
                guild_settings.add_blacklist(
                    interaction.guild_id, p_name, reason, interaction.user.id,
                    player_id=p_id, tribe_name=tribe or None,
                    scope="tribe" if tribe else "player",
                )
                if interaction.message and interaction.message.attachments:
                    pid = guild_settings.add_punishment(
                        interaction.guild_id, p_name, "ban", reason, interaction.user.id,
                        scope="tribe" if tribe else "player", player_id=p_id, tribe_name=tribe or None,
                    )
                    await _save_evidence(interaction, pid)
                _log(interaction.guild_id, "punishment", "blacklist", interaction.user, p_name,
                     details={"reason": reason, "scope": "tribe" if tribe else "player"})
                results.append(f"⛔ **{p_name}** blacklisted.")
            else:
                results.append(f"ℹ️ **{p_name}** is already blacklisted.")

        await interaction.followup.send("\n".join(results))

    @app_commands.command(name="unblacklist", description="Remove a player from the blacklist and unban them")
    @app_commands.describe(player="Player name")
    async def unblacklist(self, interaction: discord.Interaction, player: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        rows = guild_settings.get_blacklists(interaction.guild_id, player)
        safe_name = sanitize_rcon_name(player)
        result = await _send_rcon(interaction.guild_id, f"UnBan {safe_name}")
        removed = 0
        for row in rows:
            if guild_settings.remove_blacklist(row[0], interaction.guild_id):
                removed += 1
        _log(interaction.guild_id, "punishment", "unblacklist", interaction.user, player)
        msg = f"✅ **{player}** removed from blacklist ({removed} record{'s' if removed != 1 else ''})."
        if result is None:
            msg += "\n`UnBan` failed (server not reachable / not configured) — record still removed."
        await interaction.response.send_message(msg)

    @app_commands.command(name="blacklist-list", description="List all blacklisted players")
    async def blacklist_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        rows = guild_settings.get_blacklists(interaction.guild_id)
        if not rows:
            return await interaction.response.send_message("No players are blacklisted.", ephemeral=True)

        lines = []
        for r in rows:
            bid, pname, pid, tribe, reason, issued_by, scp, issued_at = r
            tribe_str = f" (tribe: {tribe})" if tribe else ""
            lines.append(f"#{bid} | {pname}{tribe_str} | {reason} | by <@{issued_by}> | {issued_at.strftime('%Y-%m-%d %H:%M')}")

        embed = discord.Embed(title="Blacklisted Players", description="\n".join(lines[:20]), color=discord.Color.dark_red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ============================================================
    #  SETTINGS
    # ============================================================

    @app_commands.command(name="set-warning-threshold", description="Set how many warnings trigger auto-punishment")
    @app_commands.describe(count="Number of warnings (default 3)")
    async def set_warning_threshold(self, interaction: discord.Interaction, count: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_setting(interaction.guild_id, "warning_threshold", count)
        await interaction.response.send_message(f"✅ Warning threshold set to **{count}**.")

    @app_commands.command(name="set-warning-punishment", description="Set auto-punishment type when threshold reached")
    @app_commands.choices(punishment_type=[
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Temp Ban", value="tempban"),
        app_commands.Choice(name="Wipe Structures", value="wipe_structures"),
        app_commands.Choice(name="Wipe Dinos", value="wipe_dinos"),
        app_commands.Choice(name="Wipe Both", value="wipe_both"),
    ])
    async def set_warning_punishment(self, interaction: discord.Interaction, punishment_type: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_setting(interaction.guild_id, "warning_punishment", punishment_type.value)
        await interaction.response.send_message(f"✅ Auto-punishment set to **{punishment_type.name}**.")

    @app_commands.command(name="set-warning-tempban-duration", description="Set tempban duration for auto-punishment")
    @app_commands.describe(hours="Duration in hours")
    async def set_warning_tempban_duration(self, interaction: discord.Interaction, hours: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_setting(interaction.guild_id, "warning_tempban_hours", hours)
        await interaction.response.send_message(f"✅ Auto-tempban duration set to **{hours}h**.")

    @app_commands.command(name="set-warning-default-expiry", description="Set default expiry for tempwarn")
    @app_commands.describe(hours="Default expiry in hours (default 72)")
    async def set_warning_default_expiry(self, interaction: discord.Interaction, hours: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_setting(interaction.guild_id, "warning_default_expiry_hours", hours)
        await interaction.response.send_message(f"✅ Default tempwarn expiry set to **{hours}h**.")

    @app_commands.command(name="set-punishment-log", description="Set channel for punishment log messages")
    @app_commands.describe(channel="Channel for punishment logs")
    async def set_punishment_log(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_setting(interaction.guild_id, "punishment_log_channel_id", channel.id)
        await interaction.response.send_message(f"✅ Punishment log channel set to {channel.mention}")

    @app_commands.command(name="add-tribe-member", description="Manually add a player to a tribe")
    @app_commands.describe(player="Player name", tribe="Tribe name")
    async def add_tribe_member(self, interaction: discord.Interaction, player: str, tribe: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.add_tribe_member(interaction.guild_id, tribe, player)
        _log(interaction.guild_id, "tribe", "member_added", interaction.user, player, details={"tribe": tribe})
        await interaction.response.send_message(f"✅ **{player}** added to tribe **{tribe}**.")

    # ============================================================
    #  SERVER MANAGEMENT
    # ============================================================

    @app_commands.command(name="server-status", description="Show server status (players, ping, etc.)")
    async def server_status(self, interaction: discord.Interaction):
        await interaction.response.defer()

        headers, service_id = _get_nitrado_headers(interaction.guild_id)
        if not headers or not service_id:
            return await interaction.followup.send("❌ Nitrado API not configured. Use `/set-nitrado-token`.", ephemeral=True)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://api.nitrado.net/services/{service_id}/servers/gameserver",
                    headers=headers, timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    server = data.get("data", {}).get("server", {})

            status = server.get("status", "unknown")
            players = server.get("query", {}).get("players", {})
            player_current = players.get("current", 0)
            player_max = players.get("max", 0)
            player_list = players.get("player", [])

            embed = discord.Embed(title="🖥️ Server Status", color=discord.Color.green() if status == "started" else discord.Color.red())
            embed.add_field(name="Status", value=f"{'🟢' if status == 'started' else '🔴'} {status}", inline=True)
            embed.add_field(name="Players", value=f"{player_current}/{player_max}", inline=True)
            if player_list:
                names = [p.get("name", "Unknown") for p in player_list[:20]]
                embed.add_field(name="Player List", value="\n".join(names) or "None", inline=False)

            _log(interaction.guild_id, "server", "status_check", interaction.user, None)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"❌ Error fetching status: `{e}`", ephemeral=True)

    @app_commands.command(name="server-restart", description="Restart the ARK server")
    async def server_restart(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        client = nitrado.get_client(interaction.guild_id)
        if not client:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "nitrado_not_configured"), ephemeral=True)
        result = client.restart_server()
        _log(interaction.guild_id, "server", "restart", interaction.user, None)
        await interaction.response.send_message("🔄 Server restart triggered." if result else "❌ Failed to trigger restart.")

    @app_commands.command(name="server-stop", description="Stop the ARK server")
    async def server_stop(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        client = nitrado.get_client(interaction.guild_id)
        if not client:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "nitrado_not_configured"), ephemeral=True)
        result = client.stop_server()
        _log(interaction.guild_id, "server", "stop", interaction.user, None)
        await interaction.response.send_message("⏹️ Server stop triggered." if result else "❌ Failed to trigger stop.")

    # ============================================================
    #  INTERNAL HELPERS
    # ============================================================

    async def _get_scope_players(self, guild_id, player_name, scope):
        if scope == "tribe":
            tribe = guild_settings.get_player_tribe(guild_id, player_name)
            if not tribe:
                return [(player_name, None)]
            members = guild_settings.get_tribe_members(guild_id, tribe)
            return [(m[0], m[1]) for m in members]
        return [(player_name, None)]

    async def _execute_auto_punishment(self, interaction, player, punishment_type):
        guild_id = interaction.guild_id
        tempban_hours = guild_settings.get_setting(guild_id, "warning_tempban_hours", 24)
        safe_player = sanitize_rcon_name(player)

        if punishment_type == "ban":
            result = await _send_rcon(guild_id, f"Ban {safe_player}")
            guild_settings.add_punishment(guild_id, player, "ban", "Auto-punishment: warning threshold reached", interaction.user.id)
            return f"🔨 **{player}** auto-banned." if result else "❌ Auto-ban failed."

        elif punishment_type == "tempban":
            result = await _send_rcon(guild_id, f"Ban {safe_player}")
            expires_at = datetime.now(timezone.utc) + timedelta(hours=tempban_hours)
            pid = guild_settings.add_punishment(guild_id, player, "tempban", "Auto-punishment: warning threshold reached", interaction.user.id, expires_at=expires_at)
            if result:
                guild_settings.mark_punishment_executed(pid)
            return f"🔨 **{player}** auto temp-banned for **{tempban_hours}h**." if result else "❌ Auto-tempban failed."

        elif punishment_type in ("wipe_structures", "wipe_dinos", "wipe_both"):
            if punishment_type in ("wipe_dinos", "wipe_both"):
                await _send_rcon(guild_id, f"DestroyAllDinos {safe_player}")
            if punishment_type in ("wipe_structures", "wipe_both"):
                await _send_rcon(guild_id, f"BanPlayer {safe_player}")
                await _send_rcon(guild_id, f"UnBanPlayer {safe_player}")
            guild_settings.add_punishment(guild_id, player, punishment_type, "Auto-punishment: warning threshold reached", interaction.user.id)
            return f"🗑️ **{player}** auto-{punishment_type.replace('_', ' ')}."

        return None


async def setup(bot):
    await bot.add_cog(Moderation(bot))
