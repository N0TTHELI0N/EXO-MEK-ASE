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


# ── Player extraction patterns ──────────────────────────────────────────────
# After stripping the log header, non-admin player lines fall into a few
# categories.  We try them in order; the first match wins.

_PLAYER_PSN = re.compile(r"^(?P<name>.+?)\s+\((?P<psn>[^)]+)\)\s*$")
_PLAYER_COLON = re.compile(
    r"^(?P<player>[^(:\]]+?)\s*(?:\((?P<psn>[^)]+)\))?\s*:\s*(?P<msg>.+)$"
)
_JOIN_LEAVE = re.compile(
    r"\b(?P<name>\S{2,40})\s+(?:joined|left|disconnected|quit)\b", re.I
)
_RICHCOLOR = re.compile(r"<richcolor[^>]*>([^<]+)</", re.I)

# Death broadcast:  "AN8R - Lvl 105 (ZO6) was killed! [KillerSID: 875216655)"
# The victim is the player whose thread gets the entry (their controlled dino
# or their character died). Kills ("was killed by") are matched separately.
_DEATH_LINE = re.compile(
    r"^(?P<name>.+?)\s*(?:-\s*Lvl\s+\d+\s*(?:\([^)]*\))?\s*)?was killed!",
    re.I,
)

# System lines that mention a player but are NOT typed by them.  We extract
# the first word-sequence after a richcolor tag or after common verb patterns
# as the actor.
_TAME_KILL = re.compile(
    r"\b(\S{2,30})\s+(?:tamed|killed|destroyed|was killed by|was tamed by)\b",
    re.I,
)

_NOISE = (
    "log file closed",
    "log file opened",
    "log file open",
    "log fragment",
    "logmemory",
    "full startup",
    "has successfully started",
    "?listen?",
    "MaxPlayers=",
    "AltSaveDirectoryName",
    "-WinPS4",
    "-server -log",
    "servergamelogincludetribelogs",
)


def _extract_player(line: str) -> tuple[str, str] | None:
    """Return ``(player_name, psn_id)`` if the line belongs to a player,
    or ``None`` if it is admin/noise/system."""
    text = guild_settings.strip_log_header(line or "").strip()
    if not text:
        return None
    low = text.lower()
    if any(n in low for n in _NOISE):
        return None
    if "admincmd" in low:
        return None

    # Tribe / global chat:  "PlayerName (PSN): msg"  or  "PlayerName: msg"
    m = _PLAYER_COLON.match(text)
    if m:
        player_raw = m.group("player").strip()
        psn = (m.group("psn") or "").strip()
        pm = _PLAYER_PSN.match(player_raw)
        if pm:
            return pm.group("name").strip(), pm.group("psn").strip()
        if player_raw and 2 <= len(player_raw) <= 40:
            return player_raw, psn

    # Join / leave
    m = _JOIN_LEAVE.search(text)
    if m:
        name = m.group("name").strip().strip("'\"")
        if name and 2 <= len(name) <= 40:
            return name, ""

    # Death broadcast:  victim was killed!
    m = _DEATH_LINE.match(text)
    if m:
        name = m.group("name").strip().strip("'\"")
        if name and 2 <= len(name) <= 40:
            return name, ""

    # Richcolor broadcast:  <richcolor ...>PlayerName tamed a …</>
    m = _RICHCOLOR.search(text)
    if m:
        inner = m.group(1).strip()
        # Try tame/kill verb pattern first (more accurate)
        km = _TAME_KILL.search(inner)
        if km:
            actor = km.group(1).strip()
            if actor and 2 <= len(actor) <= 40:
                return actor, ""
        # Otherwise first word as player
        first = inner.split()[0] if inner.split() else ""
        if first and 2 <= len(first) <= 40:
            return first, ""

    return None


# ── DB helpers (reuse tribe tables; tribe_name = player key) ────────────────

def _init_db():
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_log_events (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    tribe_name  TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    posted_forum BOOLEAN DEFAULT FALSE
                )
            """)
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_tribe_log_events_content ON tribe_log_events (guild_id, md5(content))")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tribe_events ON tribe_log_events(guild_id, tribe_name, created_at DESC)")
        conn.commit()
    finally:
        conn.close()


def _get_config(guild_id: int):
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


def _update_config(guild_id: int, **kwargs):
    ALLOWED = {"enabled", "channel_id", "log_source", "log_path", "nitrado_token", "nitrado_user_id", "nitrado_service_id"}
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO tribe_log_config (guild_id) VALUES (%s) ON CONFLICT (guild_id) DO NOTHING", (guild_id,))
            for key, val in kwargs.items():
                if key not in ALLOWED:
                    continue
                cur.execute(f"UPDATE tribe_log_config SET {key} = %s WHERE guild_id = %s", (val, guild_id))
        conn.commit()
    finally:
        conn.close()


def _get_known_players(guild_id: int):
    """Return list of player keys (name) and their PSN IDs."""
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tribe_name, tribe_game_id FROM known_tribes WHERE guild_id = %s", (guild_id,))
            return {r[0]: r[1] for r in cur.fetchall()}
    finally:
        conn.close()


def _add_known_player(guild_id: int, player_name: str, psn_id: str = ""):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO known_tribes (guild_id, tribe_name, tribe_game_id) VALUES (%s, %s, %s)
                ON CONFLICT (guild_id, tribe_name) DO UPDATE SET tribe_game_id = COALESCE(NULLIF(EXCLUDED.tribe_game_id, ''), known_tribes.tribe_game_id)
            """, (guild_id, player_name, psn_id or ""))
        conn.commit()
    finally:
        conn.close()


async def player_autocomplete(interaction: discord.Interaction, current: str):
    players = _get_known_players(interaction.guild_id)
    return [
        app_commands.Choice(name=n, value=n)
        for n in players if current.lower() in n.lower()
    ][:25]


# ── Cog ─────────────────────────────────────────────────────────────────────

class Playerlog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _init_db()
        self.known_players_cache: dict[int, dict[str, str]] = {}  # guild -> {name: psn}
        self._seen_lines: dict[int, OrderedDict] = {}
        self._file_pos: dict[tuple, int] = {}
        self._load_cache()
        self.player_log_monitor.start()

    def cog_unload(self):
        self.player_log_monitor.cancel()

    def _load_cache(self):
        conn = guild_settings.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT guild_id, tribe_name, tribe_game_id FROM known_tribes")
                for gid, name, psn in cur.fetchall():
                    self.known_players_cache.setdefault(gid, {})[name] = psn or ""
        finally:
            conn.close()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _remember_line(self, guild_id: int, text: str):
        key = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
        seen = self._seen_lines.setdefault(guild_id, OrderedDict())
        seen[key] = True
        while len(seen) > 20000:
            seen.popitem(last=False)
        return key

    def _is_new_line(self, guild_id: int, text: str) -> bool:
        key = hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()
        seen = self._seen_lines.get(guild_id)
        return not (seen and key in seen)

    @staticmethod
    def _thread_name(player_name: str, psn_id: str = "") -> str:
        """Build the Discord forum thread name for a player."""
        psn_id = (psn_id or "").strip()
        if psn_id:
            return f"{player_name} ({psn_id})"
        return player_name

    @staticmethod
    async def _resolve_thread(guild: discord.Guild, thread_id) -> discord.Thread | None:
        if not thread_id:
            return None
        t = guild.get_thread(thread_id)
        if isinstance(t, discord.Thread):
            return t
        try:
            ch = await guild.fetch_channel(thread_id)
        except Exception:
            return None
        return ch if isinstance(ch, discord.Thread) else None

    async def _ensure_player_thread(self, guild: discord.Guild, forum: discord.ForumChannel, player_name: str, psn_id: str = "") -> int | None:
        """Reuse or create the forum thread for a player.  Returns thread id."""
        cfg = guild_settings.get_tribe_forum_config(guild.id)
        if not cfg or cfg["forum_id"] != forum.id:
            guild_settings.set_tribe_forum_config(guild.id, forum.id)

        # Look up existing thread by player name (ignoring PSN in the stored key)
        existing = None
        for t in forum.threads:
            if t.name == player_name or t.name.startswith(player_name + " ("):
                existing = t
                break
        if existing:
            # Newly-discovered PSN → keep the thread title in sync.
            want = self._thread_name(player_name, psn_id)
            if want and existing.name != want and existing.name == player_name:
                try:
                    await existing.edit(name=want)
                except Exception:
                    pass
            guild_settings.set_tribe_thread(guild.id, player_name, existing.id)
            return existing.id
        try:
            thread = await forum.create_thread(
                name=self._thread_name(player_name, psn_id),
                content=bot_i18n.t(guild.id, "playerlog_thread_intro", player=player_name),
                auto_archive_duration=10080,
            )
            guild_settings.set_tribe_thread(guild.id, player_name, thread.id)
            return thread.id
        except Exception:
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

    # ── /add-player ─────────────────────────────────────────────────────────
    @app_commands.command(name="add-player", description="Add a player to the player log (Admin only)")
    @app_commands.describe(player_name="In-game player name", psn_id="PlayStation ID (optional)")
    async def add_player(self, interaction: discord.Interaction, player_name: str, psn_id: str = ""):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        name = player_name.strip()
        if not name:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "playerlog_empty_name"), ephemeral=True)
        _add_known_player(interaction.guild_id, name, psn_id)
        self.known_players_cache.setdefault(interaction.guild_id, {})[name] = psn_id
        cfg = guild_settings.get_tribe_forum_config(interaction.guild_id)
        if cfg and cfg["forum_id"]:
            forum = interaction.guild.get_channel(cfg["forum_id"])
            if isinstance(forum, discord.ForumChannel):
                await self._ensure_player_thread(interaction.guild, forum, name, psn_id)
        await interaction.followup.send(bot_i18n.t(interaction.guild_id, "playerlog_player_added", name=name), ephemeral=True)

    # ── background monitor ──────────────────────────────────────────────────
    @tasks.loop(seconds=30)
    async def player_log_monitor(self):
        for guild in self.bot.guilds:
            cfg = _get_config(guild.id) or {}
            if cfg.get("enabled") is False:
                continue
            source = cfg.get("log_source") or "file"
            path = (cfg.get("log_path") or "").strip()
            players = self.known_players_cache.get(guild.id, {})
            if not players:
                db_players = _get_known_players(guild.id)
                players = db_players
                self.known_players_cache[guild.id] = players

            lines = []
            if source == "nitrado":
                client = nitrado.get_client(guild.id)
                if client is not None:
                    try:
                        raw = await asyncio_to_thread(nitrado.get_logs_cached, client, 300)
                        if raw:
                            lines = raw.splitlines()
                    except Exception:
                        lines = []
            elif path:
                lines = self._read_new_lines(guild.id, path)
            if not lines and source != "nitrado":
                client = nitrado.get_client(guild.id)
                if client is not None:
                    try:
                        raw = await asyncio_to_thread(nitrado.get_logs_cached, client, 300)
                        if raw:
                            lines = raw.splitlines()
                    except Exception:
                        lines = []

            forum_cfg = guild_settings.get_tribe_forum_config(guild.id)
            forum = guild.get_channel(forum_cfg["forum_id"]) if forum_cfg and forum_cfg["forum_id"] else None

            for line in lines:
                text = (line or "").strip()
                if not text:
                    continue
                if not self._is_new_line(guild.id, text):
                    continue
                self._remember_line(guild.id, text)
                result = _extract_player(text)
                if not result:
                    continue
                player_name, psn_id = result
                # Update PSN mapping if newly discovered
                if psn_id and player_name in players and not players[player_name]:
                    players[player_name] = psn_id
                    _add_known_player(guild.id, player_name, psn_id)
                # Auto-register new players
                if player_name not in players:
                    _add_known_player(guild.id, player_name, psn_id)
                    players[player_name] = psn_id
                    if isinstance(forum, discord.ForumChannel):
                        await self._ensure_player_thread(guild, forum, player_name, psn_id)
                guild_settings.add_tribe_log_event(guild.id, player_name, text)

            # Post queued events to their per-player threads
            if isinstance(forum, discord.ForumChannel) and forum_cfg:
                for event in guild_settings.get_unposted_tribe_events(guild.id):
                    cfg2 = guild_settings.get_tribe_forum_config(guild.id)
                    threads = (cfg2 or {}).get("threads", {})
                    player_key = event["tribe_name"]
                    tid = threads.get(player_key)
                    target = await self._resolve_thread(guild, tid) if tid else None
                    if not isinstance(target, discord.Thread):
                        psn = players.get(player_key, "")
                        tid2 = await self._ensure_player_thread(guild, forum, player_key, psn)
                        target = await self._resolve_thread(guild, tid2) if tid2 else None
                        if not isinstance(target, discord.Thread):
                            continue
                    if target.archived:
                        try:
                            await target.edit(archived=False, auto_archive_duration=10080)
                        except Exception:
                            pass
                    raw = (event["content"] or "").strip()
                    low_raw = raw.lower()
                    if any(probe in low_raw for probe in _NOISE):
                        try:
                            guild_settings.mark_tribe_event_posted(event["id"])
                        except Exception:
                            pass
                        continue
                    try:
                        ts = guild_settings.parse_log_timestamp(raw)
                        prefix = f"<t:{ts}:R> | " if ts else ""
                        display = guild_settings.strip_log_header(raw)
                        await target.send(f"{prefix}```{display[:1850]}```")
                        guild_settings.mark_tribe_event_posted(event["id"])
                    except Exception:
                        continue

    @player_log_monitor.before_loop
    async def before_player_log_monitor(self):
        await self.bot.wait_until_ready()

    # ── /set-playerlog-enabled ──────────────────────────────────────────────
    @app_commands.command(name="set-playerlog-enabled", description="Enable or disable player log monitoring (Admin only)")
    @app_commands.describe(enabled="Enable or disable")
    async def set_playerlog_enabled(self, interaction: discord.Interaction, enabled: bool):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        _update_config(interaction.guild_id, enabled=enabled)
        status = bot_i18n.t(interaction.guild_id, "enabled_word" if enabled else "disabled_word")
        await interaction.followup.send(bot_i18n.t(interaction.guild_id, "playerlog_toggled", status=status), ephemeral=True)

    # ── /set-playerlog-channel ──────────────────────────────────────────────
    @app_commands.command(name="set-playerlog-channel", description="Set the channel for player log forum (Admin only)")
    @app_commands.describe(channel="Forum channel for player logs")
    async def set_playerlog_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        _update_config(interaction.guild_id, channel_id=channel.id)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "playerlog_channel_set", channel=channel.mention), ephemeral=True)

    # ── /set-playerlog-source ───────────────────────────────────────────────
    @app_commands.command(name="set-playerlog-source", description="Configure player log source (Admin only)")
    @app_commands.describe(source="Source type: file or nitrado", log_path="Log file path (if file source)")
    @app_commands.choices(source=[
        app_commands.Choice(name="Local File", value="file"),
        app_commands.Choice(name="Nitrado API", value="nitrado"),
    ])
    async def set_playerlog_source(self, interaction: discord.Interaction, source: app_commands.Choice[str], log_path: str = ""):
        await interaction.response.defer(ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        _update_config(interaction.guild_id, log_source=source.value, log_path=log_path)
        await interaction.followup.send(bot_i18n.t(interaction.guild_id, "playerlog_source_set", source=source.value), ephemeral=True)

    # ── /set-playerlog-config ───────────────────────────────────────────────
    @app_commands.command(name="set-playerlog-config", description="Set Nitrado credentials for player log (Admin only)")
    @app_commands.describe(api_token="Nitrado API token", user_id="User ID", service_id="Service ID")
    async def set_playerlog_config(self, interaction: discord.Interaction, api_token: str = "", user_id: str = "", service_id: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        kwargs = {}
        if api_token:
            kwargs["nitrado_token"] = api_token
        if user_id:
            kwargs["nitrado_user_id"] = user_id
        if service_id:
            kwargs["nitrado_service_id"] = service_id
        _update_config(interaction.guild_id, **kwargs)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "playerlog_config_saved"), ephemeral=True)

    # ── /view-playerlog ─────────────────────────────────────────────────────
    @app_commands.command(name="view-playerlog", description="View player log config and monitored players")
    @app_commands.describe(player_name="Look up a specific player")
    @app_commands.autocomplete(player_name=player_autocomplete)
    async def view_playerlog(self, interaction: discord.Interaction, player_name: str = ""):
        await interaction.response.defer(ephemeral=True)
        config_data = _get_config(interaction.guild_id) or {}
        players = _get_known_players(interaction.guild_id)
        counts = guild_settings.get_tribe_event_counts(interaction.guild_id)
        forum_cfg = guild_settings.get_tribe_forum_config(interaction.guild_id) or {}
        thread_map = forum_cfg.get("threads", {})

        lines = [
            f"**Enabled:** {config_data.get('enabled', False)}",
            f"**Channel:** <#{config_data.get('channel_id', 0)}>" if config_data.get("channel_id") else "**Channel:** Not set",
            f"**Source:** {config_data.get('log_source', 'file')}",
            f"**Forum:** <#{forum_cfg.get('forum_id', 0)}>" if forum_cfg.get("forum_id") else "**Forum:** Not set",
            f"**Monitored players ({len(players)}):**",
        ]
        for name, psn in players.items():
            thread = f" → <#{thread_map[name]}>" if name in thread_map else ""
            display = f"{name} ({psn})" if psn else name
            lines.append(f"  • {display} ({counts.get(name, 0)} events){thread}")

        if player_name:
            psn = players.get(player_name, "")
            display = f"{player_name} ({psn})" if psn else player_name
            lines.append(f"\n**{display}** — {counts.get(player_name, 0)} events")

        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "playerlog_config_title"), description="\n".join(lines), color=discord.Color.blurple())
        await interaction.followup.send(embed=embed, ephemeral=True)


async def asyncio_to_thread(fn, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


async def setup(bot):
    await bot.add_cog(Playerlog(bot))
