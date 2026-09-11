import os
import random
import string as _string
from datetime import datetime, timezone, date
import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
import threading
import guild_settings
import bot_i18n
import nitrado
import config


def _asyncio_to_thread(fn, *args, **kwargs):
    return asyncio.to_thread(fn, *args, **kwargs)


# ── DB helpers ──────────────────────────────────────────────
# linked_players      guild+discord -> psn_id + status (pending/active)
# wl_tokens           guild+discord -> token balance
# wl_redeemed         guild+discord -> gamertags added to the server whitelist
# Pending PSN-verification jobs are kept in-process (survive only bot uptime).

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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wl_tokens (
                    guild_id    BIGINT NOT NULL,
                    discord_id  BIGINT NOT NULL,
                    tokens      INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, discord_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS wl_redeemed (
                    guild_id    BIGINT NOT NULL,
                    discord_id  BIGINT NOT NULL,
                    gamertag    TEXT NOT NULL,
                    redeemed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (guild_id, discord_id, gamertag)
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
            return bool(row and row[0] == date.today())
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


def _link_player(guild_id: int, discord_id: int, psn_id: str, status: str = "pending"):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO linked_players (guild_id, discord_id, psn_id, status)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (guild_id, discord_id) DO UPDATE SET psn_id = EXCLUDED.psn_id, status = EXCLUDED.status
            """, (guild_id, discord_id, psn_id, status))
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


def _psn_linked_elsewhere(guild_id: int, psn_id: str, exclude_discord: int) -> bool:
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT discord_id FROM linked_players WHERE guild_id = %s AND psn_id = %s AND discord_id <> %s",
                        (guild_id, psn_id, exclude_discord))
            return cur.fetchone() is not None
    finally:
        conn.close()


def _get_tokens(guild_id: int, discord_id: int) -> int:
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tokens FROM wl_tokens WHERE guild_id = %s AND discord_id = %s", (guild_id, discord_id))
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        conn.close()


def _add_tokens(guild_id: int, discord_id: int, qty: int) -> int:
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO wl_tokens (guild_id, discord_id, tokens) VALUES (%s, %s, %s)
                ON CONFLICT (guild_id, discord_id) DO UPDATE SET tokens = wl_tokens.tokens + EXCLUDED.tokens
            """, (guild_id, discord_id, qty))
        conn.commit()
        return _get_tokens(guild_id, discord_id)
    finally:
        conn.close()


def _spend_token(guild_id: int, discord_id: int) -> tuple[bool, int]:
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tokens FROM wl_tokens WHERE guild_id = %s AND discord_id = %s", (guild_id, discord_id))
            row = cur.fetchone()
            bal = int(row[0]) if row else 0
            if bal <= 0:
                return False, 0
            cur.execute("UPDATE wl_tokens SET tokens = tokens - 1 WHERE guild_id = %s AND discord_id = %s", (guild_id, discord_id))
        conn.commit()
        return True, bal - 1
    finally:
        conn.close()


def _record_redeemed(guild_id: int, discord_id: int, gamertag: str):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO wl_redeemed (guild_id, discord_id, gamertag) VALUES (%s, %s, %s)
                ON CONFLICT (guild_id, discord_id, gamertag) DO NOTHING
            """, (guild_id, discord_id, gamertag))
        conn.commit()
    finally:
        conn.close()


def _get_redeemed(guild_id: int, discord_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT gamertag FROM wl_redeemed WHERE guild_id = %s AND discord_id = %s ORDER BY redeemed_at DESC", (guild_id, discord_id))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _all_redeemed_gamertags(guild_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT gamertag FROM wl_redeemed WHERE guild_id = %s", (guild_id,))
            return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def _update_whitelist_file(guild_id: int) -> bool:
    """Write all active linked PSN IDs to the whitelist file via the Nitrado FileServer API."""
    wl_dir = guild_settings.get_setting(guild_id, "whitelist_path", "")
    if not wl_dir:
        return False
    players = _get_linked_players(guild_id)
    active_psns = [p[1] for p in players if p[2] in ("active", "pending")]
    client = nitrado.get_client(guild_id)
    if not client:
        return False
    try:
        content = "\n".join(active_psns) + "\n" if active_psns else ""
        return client.write_file(wl_dir, "Whitelist.txt", content)
    except Exception:
        return False


def _push_whitelist_api(guild_id: int, gamertags) -> int:
    """Best-effort push of gamertags to Nitrado's game whitelist API (works on PS)."""
    ok = 0
    for tag in gamertags:
        if not tag:
            continue
        try:
            result = nitrado.whitelist_player(guild_id, tag)
            if result in ("Whitelisted", "Already whitelisted"):
                ok += 1
        except Exception:
            continue
    return ok


def _random_code(length: int = 8) -> str:
    return "".join(random.choice(_string.ascii_uppercase) for _ in range(length))


# ── PSN verification (About Me) ─────────────────────────────
_PENDING_VERIFY: dict[tuple[int, int], dict] = {}
_VERIFY_LOCK = threading.Lock()
_VERIFY_TIMEOUT_S = 300
_VERIFY_TTL_S = 3600


def _psn_awp_token(guild_id: int) -> str:
    return (guild_settings.get_setting(guild_id, "psn_awp_token", "") or config.PSN_AWP_TOKEN or "").strip()


def _psn_about_me(psn: str, token: str) -> str:
    """Return the About Me text of a PSN id, or '' on failure."""
    if not token:
        return ""
    try:
        from psnawp_api import PSNAWP
        awp = PSNAWP(token)
        user = awp.user(online_id=psn)
        profile = user.profile()
        return str(profile.get("aboutMe", "") or "")
    except Exception:
        return ""


def _verify_job_done(guild_id: int, discord_id: int) -> bool:
    with _VERIFY_LOCK:
        job = _PENDING_VERIFY.get((guild_id, discord_id))
        return bool(job and job.get("done"))


# ── Cog ─────────────────────────────────────────────────────

class Whitelist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _init_whitelist_db()
        self.daily_restart_check.start()
        self.psn_check_loop.start()

    def cog_unload(self):
        self.daily_restart_check.cancel()
        self.psn_check_loop.cancel()

    # ── PSN verification background loop (every 45s) ─────────
    @tasks.loop(seconds=45)
    async def psn_check_loop(self):
        now = datetime.now(timezone.utc)
        with _VERIFY_LOCK:
            jobs = list(_PENDING_VERIFY.items())
        for (gid, uid), job in jobs:
            if job.get("done"):
                continue
            if now.timestamp() > job.get("expires", 0):
                with _VERIFY_LOCK:
                    job["done"] = True
                guild = self.bot.get_guild(gid)
                if guild:
                    member = guild.get_member(uid)
                    if member:
                        try:
                            await member.send(bot_i18n.t(gid, "psn_link_failed_expired", psn=job["psn"]))
                        except Exception:
                            pass
                continue
            try:
                about = await _asyncio_to_thread(_psn_about_me, job["psn"], job["token"])
            except Exception:
                about = ""
            if about and about.strip().upper() == job["code"].strip().upper():
                _link_player(gid, uid, job["psn"], status="active")
                await _asyncio_to_thread(_push_whitelist_api, gid, [job["psn"]])
                with _VERIFY_LOCK:
                    _PENDING_VERIFY.pop((gid, uid), None)
                guild = self.bot.get_guild(gid)
                if guild:
                    member = guild.get_member(uid)
                    if member:
                        try:
                            await member.send(bot_i18n.t(gid, "psn_link_success", psn=job["psn"], member=member.mention))
                        except Exception:
                            pass

    @psn_check_loop.before_loop
    async def before_psn_loop(self):
        await self.bot.wait_until_ready()

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
                success = await _asyncio_to_thread(_update_whitelist_file, gid)
                if success:
                    conn = guild_settings.get_conn()
                    try:
                        with conn.cursor() as cur:
                            cur.execute("UPDATE linked_players SET status = 'active' WHERE guild_id = %s AND status = 'pending'", (gid,))
                        conn.commit()
                    finally:
                        conn.close()
                await _asyncio_to_thread(
                    _push_whitelist_api, gid,
                    [p[1] for p in _get_linked_players(gid) if p[2] == "active"],
                )
                r_client = nitrado.get_client(gid)
                if r_client:
                    await _asyncio_to_thread(r_client.restart_server)
                _mark_ran_today(gid)
                guild_settings.log_action(gid, "whitelist", None, "System", None, sub_type="restart", details={"status": "success"})
                ch_id = guild_settings.get_setting(gid, "log_channel_id")
                if ch_id:
                    ch = guild.get_channel(ch_id)
                    if ch:
                        await ch.send(bot_i18n.t(gid, "server_restarted_whitelist", time=now.strftime('%H:%M')))

    @daily_restart_check.before_loop
    async def before_daily_restart(self):
        await self.bot.wait_until_ready()

    # ── /set-whitelist-path ──────────────────────────────────
    @app_commands.guild_only()
    @app_commands.command(name="set-whitelist-path", description="Set the directory for Whitelist.txt on the server (Admin only)")
    @app_commands.describe(path="Server folder containing Whitelist.txt (e.g. /ShooterGame/Saved)")
    async def set_whitelist_path(self, interaction: discord.Interaction, path: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_setting(interaction.guild_id, "whitelist_path", path)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "whitelist_path_set", path=path), ephemeral=True)

    # ── /set-restart-time ────────────────────────────────────
    @app_commands.guild_only()
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
    @app_commands.guild_only()
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
            status_word = bot_i18n.t(interaction.guild_id, "whitelist_status_active_word") if status == "active" else bot_i18n.t(interaction.guild_id, "whitelist_status_pending_word")
            lines.append(f"{status_emoji} **{name}** → `{psn}` [{status_word}]")
        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "whitelist_title"), description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed)

    # ── /wl-list ─────────────────────────────────────────────
    @app_commands.guild_only()
    @app_commands.command(name="wl-list", description="List all linked players (Admin only)")
    async def wl_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        players = _get_linked_players(interaction.guild_id)
        lines = [f"<@{p[0]}> → `{p[1]}` [{p[2]}]" for p in players]
        await interaction.response.send_message("\n".join(lines) or bot_i18n.t(interaction.guild_id, "whitelist_none_linked"), ephemeral=True)

    # ── /linkpsn ─────────────────────────────────────────────
    @app_commands.guild_only()
    @app_commands.command(name="linkpsn", description="Link your PSN ID to your Discord account (About Me verification)")
    @app_commands.describe(psn="Your PSN gamertag")
    async def linkpsn(self, interaction: discord.Interaction, psn: str):
        if interaction.guild_id is None or interaction.user is None:
            return
        gid = interaction.guild_id
        token = _psn_awp_token(gid)
        if not token:
            return await interaction.response.send_message(bot_i18n.t(gid, "psn_no_token"), ephemeral=True)
        psn = psn.strip()
        if _psn_linked_elsewhere(gid, psn, interaction.user.id):
            return await interaction.response.send_message(bot_i18n.t(gid, "psn_already_linked"), ephemeral=True)
        _link_player(gid, interaction.user.id, psn, status="pending")
        code = _random_code(8)
        with _VERIFY_LOCK:
            _PENDING_VERIFY[(gid, interaction.user.id)] = {
                "psn": psn,
                "code": code,
                "token": token,
                "check_at": datetime.now(timezone.utc).timestamp(),
                "expires": datetime.now(timezone.utc).timestamp() + _VERIFY_TIMEOUT_S,
                "done": False,
            }
        await interaction.response.send_message(bot_i18n.t(gid, "psn_setup_code", code=code), ephemeral=True)
        guild_settings.log_action(gid, "whitelist", interaction.user.id, str(interaction.user), psn, sub_type="link_pending", details={"psn_id": psn})

    # ── /unlinkpsn ───────────────────────────────────────────
    @app_commands.guild_only()
    @app_commands.command(name="unlinkpsn", description="Unlink your PSN ID from the bot")
    async def unlinkpsn(self, interaction: discord.Interaction):
        with _VERIFY_LOCK:
            _PENDING_VERIFY.pop((interaction.guild_id, interaction.user.id), None)
        _unlink_player(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "unlinkpsn_success", member=interaction.user.mention),
            ephemeral=True,
        )
        guild_settings.log_action(interaction.guild_id, "whitelist", interaction.user.id, str(interaction.user), None, sub_type="unlink")

    # ── /wl-status ───────────────────────────────────────────
    @app_commands.guild_only()
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
            bot_i18n.t(interaction.guild_id, "wl_status_body", psn=player[0], status=status_text),
            ephemeral=True,
        )

    # ── /token-add ───────────────────────────────────────────
    @app_commands.guild_only()
    @app_commands.command(name="token-add", description="Give a member whitelist redeem tokens (Admin only)")
    @app_commands.describe(user="Member to receive tokens", count="Number of tokens (default 1)")
    async def token_add(self, interaction: discord.Interaction, user: discord.Member, count: int = 1):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        if count < 1:
            count = 1
        balance = _add_tokens(interaction.guild_id, user.id, count)
        guild_settings.log_action(interaction.guild_id, "whitelist", interaction.user.id, str(interaction.user), None, sub_type="token_add", details={"discord_id": user.id, "count": count})
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "wl_token_added", member=user.mention, count=balance),
            ephemeral=True,
        )

    # ── /wl-redeem ───────────────────────────────────────────
    @app_commands.guild_only()
    @app_commands.command(name="wl-redeem", description="Use 1 token to add a gamertag to the server whitelist")
    @app_commands.describe(gamertag="PSN gamertag to whitelist")
    async def wl_redeem(self, interaction: discord.Interaction, gamertag: str):
        if interaction.guild_id is None:
            return
        gid = interaction.guild_id
        gamertag = gamertag.strip()
        if not nitrado.get_client(gid):
            return await interaction.response.send_message(bot_i18n.t(gid, "wl_no_nitrado"), ephemeral=True)
        ok, left = _spend_token(gid, interaction.user.id)
        if not ok:
            return await interaction.response.send_message(bot_i18n.t(gid, "wl_token_insufficient"), ephemeral=True)
        await interaction.response.defer()
        result = await _asyncio_to_thread(nitrado.whitelist_player, gid, gamertag)
        if result in ("Whitelisted", "Already whitelisted"):
            _record_redeemed(gid, interaction.user.id, gamertag)
            guild_settings.log_action(gid, "whitelist", interaction.user.id, str(interaction.user), gamertag, sub_type="redeem", details={"tokens_left": left})
            await interaction.followup.send(bot_i18n.t(gid, "wl_redeem_ok", gamertag=gamertag, left=left))
        else:
            _add_tokens(gid, interaction.user.id, 1)
            await interaction.followup.send(bot_i18n.t(gid, "wl_redeem_failed", gamertag=gamertag, reason=result))

    # ── /wl-refresh ──────────────────────────────────────────
    @app_commands.guild_only()
    @app_commands.command(name="wl-refresh", description="Re-apply all your redeemed gamertags to the server whitelist")
    async def wl_refresh(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            return
        gid = interaction.guild_id
        if not nitrado.get_client(gid):
            return await interaction.response.send_message(bot_i18n.t(gid, "wl_no_nitrado"), ephemeral=True)
        redeemed = _get_redeemed(gid, interaction.user.id)
        if not redeemed:
            return await interaction.response.send_message(bot_i18n.t(gid, "wl_no_redeemed"), ephemeral=True)
        await interaction.response.defer()
        ok = await _asyncio_to_thread(_push_whitelist_api, gid, redeemed)
        guild_settings.log_action(gid, "whitelist", interaction.user.id, str(interaction.user), None, sub_type="refresh", details={"count": ok})
        await interaction.followup.send(bot_i18n.t(gid, "wl_refresh_ok", count=ok))

    # ── /wl-check ────────────────────────────────────────────
    @app_commands.guild_only()
    @app_commands.command(name="wl-check", description="Check your whitelist token balance and redeemed PSNs")
    async def wl_check(self, interaction: discord.Interaction):
        tokens = _get_tokens(interaction.guild_id, interaction.user.id)
        redeemed = _get_redeemed(interaction.guild_id, interaction.user.id)
        out = bot_i18n.t(interaction.guild_id, "wl_token_balance", tokens=tokens)
        out += "\n" + (bot_i18n.t(interaction.guild_id, "wl_redeemed_list", list="`" + "`, `".join(redeemed) + "`") if redeemed else bot_i18n.t(interaction.guild_id, "wl_no_redeemed"))
        await interaction.response.send_message(out, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Whitelist(bot))