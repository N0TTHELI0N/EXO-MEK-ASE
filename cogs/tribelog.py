import os
import re
import hashlib
from collections import OrderedDict
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone
import guild_settings
import nitrado
import config
import bot_i18n


TRIBE_LOG_PATTERN = re.compile(r"Tribe called '(.+?)' added a member")

# Patterns used to discover tribe names straight from server log lines.
TRIBE_DISCOVERY_PATTERNS = [
    re.compile(r"Tribe called ['\"]?([^'\"]+)['\"]?", re.I),
    re.compile(r"Tribe ['\"]?([^'\"\s]+)['\"]?", re.I),
    re.compile(r"Tribe (?:of |named )?['\"]?([^'\"\s]+)['\"]?", re.I),
    re.compile(r"LogTribeLog.*?Tribe[:= ]+['\"]?([^'\"\s]+)", re.I),
    re.compile(r"TribeName[:=]+([^,\s]+)", re.I),
]

ALLOWED_TRIBELOG_COLUMNS = {"enabled", "channel_id", "log_source", "log_path", "nitrado_token", "nitrado_user_id", "nitrado_service_id"}

MAX_SEEN_LINES = 20000


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
        self._seen_lines: dict[int, OrderedDict] = {}
        self._file_pos: dict[tuple, int] = {}
        self._load_cache()
        self.tribe_log_monitor.start()

    def cog_unload(self):
        self.tribe_log_monitor.cancel()

    def _load_cache(self):
        conn = guild_settings.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT guild_id, tribe_name FROM known_tribes")
                for gid, name in cur.fetchall():
                    self.known_tribes_cache.setdefault(gid, set()).add(name)
        finally:
            conn.close()

    # ── helpers ─────────────────────────────────────────────

    def _remember_line(self, guild_id: int, text: str):
        key = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
        seen = self._seen_lines.setdefault(guild_id, OrderedDict())
        seen[key] = True
        while len(seen) > MAX_SEEN_LINES:
            seen.popitem(last=False)
        return key

    def _is_new_line(self, guild_id: int, text: str) -> bool:
        key = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
        seen = self._seen_lines.get(guild_id)
        return not (seen and key in seen)

    def _discover_tribe(self, line: str, known: set) -> str | None:
        """Return a known tribe name mentioned in the line, else a newly-discovered one."""
        low = line.lower()
        for name in known:
            if name and name.lower() in low:
                return name
        for pat in TRIBE_DISCOVERY_PATTERNS:
            m = pat.search(line)
            if m:
                name = m.group(1).strip().strip("'\"")
                if name and 2 <= len(name) <= 64:
                    return name
        return None

    def _read_new_lines(self, guild_id: int, path: str):
        try:
            size = os.path.getsize(path)
            key = (guild_id, path)
            pos = self._file_pos.get(key)
            if pos is None or size < pos:
                pos = 0
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(pos)
                lines = f.readlines()
                self._file_pos[key] = f.tell()
            return lines
        except Exception:
            return []

    # ── /setup-tribe-forum ──────────────────────────────────
    @app_commands.command(name="setup-tribe-forum", description="Create a tribe-logs forum with one post per tribe (Admin only)")
    @app_commands.describe(channel="Existing forum/text channel to use (optional - otherwise auto-created)")
    async def setup_tribe_forum(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        forum = channel if isinstance(channel, discord.ForumChannel) else None
        if not forum:
            try:
                forum = await interaction.guild.create_forum(
                    name="tribe-logs",
                    topic=bot_i18n.t(interaction.guild_id, "tribe_forum_topic"),
                    reason="Tribe log forum - created by setup-tribe-forum",
                )
            except Exception as e:
                return await interaction.followup.send(f"❌ Could not create forum: {e}", ephemeral=True)

        guild_settings.set_tribe_forum_config(interaction.guild_id, forum.id)

        tribes = self.known_tribes_cache.get(interaction.guild_id, set()) or set(_get_known_tribes(interaction.guild_id))
        created = []
        for tribe in sorted(tribes):
            thread_id = await self._ensure_tribe_thread(interaction.guild, forum, tribe)
            if thread_id:
                created.append((tribe, thread_id))
        if created:
            lines = "\n".join(f"  • **{t}** → <#{tid}>" for t, tid in created)
        else:
            lines = bot_i18n.t(interaction.guild_id, "tribe_forum_no_tribes")

        await interaction.followup.send(
            f"✅ Tribe-logs forum ready.\nForum: {forum.mention}\nMonitored tribes ({len(created)}):\n{lines}",
            ephemeral=True,
        )

    # ── /add-tribe-name ─────────────────────────────────────
    @app_commands.command(name="add-tribe-name", description="Add a tribe name to monitor (Admin only)")
    @app_commands.describe(tribe_name="Tribe name")
    async def add_tribe_name(self, interaction: discord.Interaction, tribe_name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        name = tribe_name.strip()
        if not name:
            return await interaction.response.send_message("❌ Empty tribe name.", ephemeral=True)
        _add_known_tribe(interaction.guild_id, name)
        self.known_tribes_cache.setdefault(interaction.guild_id, set()).add(name)
        # create a thread right away if forum is set
        cfg = guild_settings.get_tribe_forum_config(interaction.guild_id)
        if cfg and cfg["forum_id"]:
            forum = interaction.guild.get_channel(cfg["forum_id"])
            if isinstance(forum, discord.ForumChannel):
                await self._ensure_tribe_thread(interaction.guild, forum, name)
        await interaction.response.send_message(f"✅ **{name}** added to monitoring list.", ephemeral=True)

    async def _ensure_tribe_thread(self, guild: discord.Guild, forum: discord.ForumChannel, tribe: str) -> int | None:
        """Reuse or create the forum thread for a tribe. Returns thread id."""
        cfg = guild_settings.get_tribe_forum_config(guild.id)
        if not cfg or cfg["forum_id"] != forum.id:
            guild_settings.set_tribe_forum_config(guild.id, forum.id)

        existing = discord.utils.get(forum.threads, name=lambda t, n=tribe: t.name == n or t.name.startswith(n) or n in t.name)
        if existing:
            guild_settings.set_tribe_thread(guild.id, tribe, existing.id)
            return existing.id
        try:
            thread = await forum.create_thread(
                name=tribe,
                content=bot_i18n.t(guild.id, "tribe_forum_thread_intro", tribe=tribe),
                auto_archive_duration=10080,
            )
            guild_settings.set_tribe_thread(guild.id, tribe, thread.id)
            return thread.id
        except Exception:
            return None

    # ── background monitor ──────────────────────────────────
    @tasks.loop(seconds=30)
    async def tribe_log_monitor(self):
        for guild in self.bot.guilds:
            cfg = _get_tribelog_config(guild.id)
            if not cfg or not cfg.get("enabled"):
                continue
            source = cfg.get("log_source", "file")
            path = (cfg.get("log_path") or "").strip()
            known = self.known_tribes_cache.get(guild.id, set())
            if not known:
                db_known = _get_known_tribes(guild.id)
                known = set(db_known)
                self.known_tribes_cache[guild.id] = known

            lines = []
            if source == "nitrado":
                client = nitrado.get_client(guild.id)
                if client is not None:
                    try:
                        raw = await asyncio_to_thread(client.get_logs, 300)
                        if raw:
                            lines = raw.splitlines()
                    except Exception:
                        lines = []
            else:
                if path:
                    lines = self._read_new_lines(guild.id, path)

            forum_cfg = guild_settings.get_tribe_forum_config(guild.id)
            forum = guild.get_channel(forum_cfg["forum_id"]) if forum_cfg and forum_cfg["forum_id"] else None

            for line in lines:
                text = (line or "").strip()
                if not text:
                    continue
                if not self._is_new_line(guild.id, text):
                    continue
                self._remember_line(guild.id, text)
                tribe = self._discover_tribe(text, known)
                if not tribe:
                    continue
                # newly discovered tribe -> persist + cache + thread
                if tribe not in known:
                    _add_known_tribe(guild.id, tribe)
                    known.add(tribe)
                    if isinstance(forum, discord.ForumChannel):
                        await self._ensure_tribe_thread(guild, forum, tribe)
                guild_settings.add_tribe_log_event(guild.id, tribe, text)

            # post queued events to their per-tribe threads
            if isinstance(forum, discord.ForumChannel) and forum_cfg:
                for event in guild_settings.get_unposted_tribe_events(guild.id):
                    cfg2 = guild_settings.get_tribe_forum_config(guild.id)
                    threads = (cfg2 or {}).get("threads", {})
                    tid = threads.get(event["tribe_name"])
                    target = guild.get_thread(tid) if tid else None
                    if not target:
                        tid2 = await self._ensure_tribe_thread(guild, forum, event["tribe_name"])
                        target = guild.get_thread(tid2) if tid2 else None
                        if not target:
                            continue
                    try:
                        await target.send(event["content"][:1900])
                        guild_settings.mark_tribe_event_posted(event["id"])
                    except Exception:
                        continue

    @tribe_log_monitor.before_loop
    async def before_tribe_log_monitor(self):
        await self.bot.wait_until_ready()

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

    # ── /view-tribelog ───────────────────────────────────────
    @app_commands.command(name="view-tribelog", description="View monitored tribes and log config")
    @app_commands.describe(tribe_name="Look up a specific tribe")
    @app_commands.autocomplete(tribe_name=tribe_autocomplete)
    async def view_tribelog(self, interaction: discord.Interaction, tribe_name: str = ""):
        config_data = _get_tribelog_config(interaction.guild_id) or {}
        tribes = _get_known_tribes(interaction.guild_id)
        counts = guild_settings.get_tribe_event_counts(interaction.guild_id)
        forum_cfg = guild_settings.get_tribe_forum_config(interaction.guild_id) or {}
        thread_map = forum_cfg.get("threads", {})

        lines = [
            f"**Enabled:** {config_data.get('enabled', False)}",
            f"**Channel:** <#{config_data.get('channel_id', 0)}>" if config_data.get("channel_id") else "**Channel:** Not set",
            f"**Source:** {config_data.get('log_source', 'file')}",
            f"**Forum:** <#{forum_cfg.get('forum_id', 0)}>" if forum_cfg.get("forum_id") else "**Forum:** Not set",
            f"**Monitored tribes ({len(tribes)}):**",
        ]
        for t in tribes:
            thread = f" → <#{thread_map[t]}>" if t in thread_map else ""
            lines.append(f"  • {t} ({counts.get(t, 0)} events){thread}")

        if tribe_name:
            lines.append(f"\n**Tribe '{tribe_name}' status:** Monitored ({counts.get(tribe_name, 0)} events)")

        embed = discord.Embed(title="📋 Tribe Log Config", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


# Helper so we don't need to import asyncio at top (kept simple).
async def asyncio_to_thread(fn, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


async def setup(bot):
    await bot.add_cog(Tribelog(bot))
