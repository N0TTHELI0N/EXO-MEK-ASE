import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, date
import paramiko
import guild_settings
import bot_i18n
import config


# ── DB helpers ──────────────────────────────────────────────

def _init_whitelist_db():
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS linked_players (
                    guild_id    BIGINT NOT NULL,
                    discord_id  BIGINT NOT NULL,
                    psn_id      TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    linked_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (guild_id, discord_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS restart_schedule (
                    guild_id        BIGINT PRIMARY KEY,
                    restart_hour    INTEGER DEFAULT 3,
                    restart_minute  INTEGER DEFAULT 0,
                    last_run_date   DATE
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _already_ran_today(guild_id: int) -> bool:
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT last_run_date FROM restart_schedule WHERE guild_id = %s", (guild_id,))
            row = cur.fetchone()
            if row and row[0] == date.today():
                return True
            return False
    finally:
        conn.close()


def _mark_ran_today(guild_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO restart_schedule (guild_id, last_run_date) VALUES (%s, %s)
                ON CONFLICT (guild_id) DO UPDATE SET last_run_date = EXCLUDED.last_run_date
            """, (guild_id, date.today()))
        conn.commit()
    finally:
        conn.close()


def _link_player(guild_id: int, discord_id: int, psn_id: str):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO linked_players (guild_id, discord_id, psn_id, status)
                VALUES (%s, %s, %s, 'pending')
                ON CONFLICT (guild_id, discord_id) DO UPDATE SET psn_id = EXCLUDED.psn_id, status = 'pending'
            """, (guild_id, discord_id, psn_id))
        conn.commit()
    finally:
        conn.close()


def _unlink_player(guild_id: int, discord_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM linked_players WHERE guild_id = %s AND discord_id = %s", (guild_id, discord_id))
        conn.commit()
    finally:
        conn.close()


def _get_linked_players(guild_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT discord_id, psn_id, status FROM linked_players WHERE guild_id = %s", (guild_id,))
            return cur.fetchall()
    finally:
        conn.close()


def _get_player(guild_id: int, discord_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT psn_id, status FROM linked_players WHERE guild_id = %s AND discord_id = %s", (guild_id, discord_id))
            return cur.fetchone()
    finally:
        conn.close()


def _update_whitelist_file(guild_id: int) -> bool:
    """Write all active linked PSN IDs to the whitelist file via SFTP."""
    wl_path = guild_settings.get_setting(guild_id, "whitelist_path", "")
    if not wl_path:
        return False

    players = _get_linked_players(guild_id)
    active_psns = [p[1] for p in players if p[2] == "active" or p[2] == "pending"]

    host = guild_settings.get_setting(guild_id, "sftp_host")
    port = guild_settings.get_setting(guild_id, "sftp_port", 22)
    username = guild_settings.get_setting(guild_id, "sftp_username")
    password = guild_settings.get_setting(guild_id, "sftp_password")

    if not all([host, username, password]):
        return False

    try:
        transport = paramiko.Transport((host, int(port)))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)

        content = "\n".join(active_psns) + "\n" if active_psns else ""
        with sftp.open(wl_path, "w") as f:
            f.write(content)

        sftp.close()
        transport.close()
        return True
    except Exception as e:
        print(f"[Whitelist] SFTP error: {type(e).__name__}")
        return False


async def _send_rcon(guild_id: int, command: str) -> str | None:
    host = guild_settings.get_setting(guild_id, "rcon_host") or config.RCON_HOST
    port = guild_settings.get_setting(guild_id, "rcon_port") or config.RCON_PORT
    password = guild_settings.get_setting(guild_id, "rcon_password") or config.RCON_PASSWORD

    if not host:
        return None

    try:
        from rcon import Client
        with Client(host, port=port, passwd=password) as client:
            return client.cmd(command)
    except Exception as e:
        print(f"[Whitelist] RCON error: {type(e).__name__}")
        return None


# ── Cog ─────────────────────────────────────────────────────

class Whitelist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _init_whitelist_db()
        self.daily_restart_check.start()

    def cog_unload(self):
        self.daily_restart_check.cancel()

    # ── Daily Restart Task (every 15 min) ────────────────────
    @tasks.loop(minutes=15)
    async def daily_restart_check(self):
        now = datetime.now(timezone.utc)
        for guild in self.bot.guilds:
            gid = guild.id
            if _already_ran_today(gid):
                continue

            sched = guild_settings.get_setting(gid, "restart_schedule", {})
            hour = sched.get("hour", 3)
            minute = sched.get("minute", 0)

            if now.hour == hour and now.minute >= minute and now.minute < minute + 15:
                # Update whitelist file
                success = _update_whitelist_file(gid)
                if success:
                    # Mark all pending as active
                    conn = guild_settings.get_conn()
                    try:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE linked_players SET status = 'active' WHERE guild_id = %s AND status = 'pending'", (gid,))
                        conn.commit()
                    finally:
                        conn.close()

                    # Restart via RCON
                    await _send_rcon(gid, "DoExit")
                    _mark_ran_today(gid)
                    guild_settings.log_action(gid, "whitelist", None, "System", None, sub_type="restart", details={"status": "success"})

                    ch_id = guild_settings.get_setting(gid, "log_channel_id")
                    if ch_id:
                        ch = guild.get_channel(ch_id)
                        if ch:
                            await ch.send(f"🔄 Server restarted. Whitelist updated at {now.strftime('%H:%M')} UTC.")

    @daily_restart_check.before_loop
    async def before_daily_restart(self):
        await self.bot.wait_until_ready()

    # ── /set-whitelist-path ──────────────────────────────────
    @app_commands.command(name="set-whitelist-path", description="Set the path to Whitelist.txt on the server (Admin only)")
    @app_commands.describe(path="Full path to Whitelist.txt (e.g. /ARK/.../Whitelist.txt)")
    async def set_whitelist_path(self, interaction: discord.Interaction, path: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, "whitelist_path", path)
        await interaction.response.send_message(f"✅ Whitelist path set to:\n`{path}`", ephemeral=True)

    # ── /set-restart-time ────────────────────────────────────
    @app_commands.command(name="set-restart-time", description="Set the daily restart time for whitelist activation (Admin only)")
    @app_commands.describe(hour="UTC hour (0-23)", minute="UTC minute (0-59)")
    async def set_restart_time(self, interaction: discord.Interaction, hour: int, minute: int = 0):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, "restart_schedule", {"hour": hour, "minute": minute})
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "restart_scheduled", time=f"{hour:02d}:{minute:02d}"),
            ephemeral=True,
        )

    # ── /whitelist ───────────────────────────────────────────
    @app_commands.command(name="whitelist", description="View whitelist status")
    async def whitelist_cmd(self, interaction: discord.Interaction):
        players = _get_linked_players(interaction.guild_id)
        if not players:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "whitelist_not_found", member="everyone"), ephemeral=True)

        lines = []
        for disc_id, psn, status in players:
            member = interaction.guild.get_member(disc_id)
            name = member.display_name if member else f"User#{disc_id}"
            status_emoji = "✅" if status == "active" else "⏳"
            lines.append(f"{status_emoji} **{name}** → `{psn}` [{status}]")

        embed = discord.Embed(title="📋 Whitelist", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed)

    # ── /wl-list ─────────────────────────────────────────────
    @app_commands.command(name="wl-list", description="List all linked players (Admin only)")
    async def wl_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        players = _get_linked_players(interaction.guild_id)
        lines = [f"<@{p[0]}> → `{p[1]}` [{p[2]}]" for p in players]
        await interaction.response.send_message("\n".join(lines) or "No linked players.", ephemeral=True)

    # ── /linkpsn ─────────────────────────────────────────────
    @app_commands.command(name="linkpsn", description="Link your PSN ID to your Discord account for whitelist")
    @app_commands.describe(gamertag="Your PSN gamertag")
    async def linkpsn(self, interaction: discord.Interaction, gamertag: str):
        _link_player(interaction.guild_id, interaction.user.id, gamertag)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "linkpsn_success", gamertag=gamertag, member=interaction.user.mention),
            ephemeral=True,
        )
        guild_settings.log_action(interaction.guild_id, "whitelist", interaction.user.id, str(interaction.user), interaction.user.display_name, sub_type="link", details={"psn_id": gamertag})

    # ── /unlinkpsn ───────────────────────────────────────────
    @app_commands.command(name="unlinkpsn", description="Unlink your PSN ID from the bot")
    async def unlinkpsn(self, interaction: discord.Interaction):
        _unlink_player(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "unlinkpsn_success", member=interaction.user.mention),
            ephemeral=True,
        )
        guild_settings.log_action(interaction.guild_id, "whitelist", interaction.user.id, str(interaction.user), interaction.user.display_name, sub_type="unlink")

    # ── /wl-status ───────────────────────────────────────────
    @app_commands.command(name="wl-status", description="Check your whitelist status")
    async def wl_status(self, interaction: discord.Interaction):
        player = _get_player(interaction.guild_id, interaction.user.id)
        if not player:
            return await interaction.response.send_message(
                bot_i18n.t(interaction.guild_id, "wl_not_registered", member=interaction.user.mention),
                ephemeral=True,
            )

        status = player[1]
        status_text = bot_i18n.t(interaction.guild_id, "whitelist_active") if status == "active" else bot_i18n.t(interaction.guild_id, "whitelist_pending_restart")
        await interaction.response.send_message(
            f"**PSN:** `{player[0]}`\n**Status:** {status_text}",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Whitelist(bot))
