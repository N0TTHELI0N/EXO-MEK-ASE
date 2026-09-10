import discord
from discord.ext import commands, tasks
from discord import app_commands
import bot_i18n
import guild_settings


async def _normalize_thread(result):
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, discord.Thread):
                return item
        return None
    return result if isinstance(result, discord.Thread) else None


class ServerLogs(commands.Cog):
    """Server-logs forum (player join/leave) + game-chat forum.

    Events are captured by cogs/chat_bridge.py from the ARK server log; this
    cog owns the two forums and posts the queued entries to their threads.
    """

    def __init__(self, bot):
        self.bot = bot
        self.post_server_logs.start()

    def cog_unload(self):
        self.post_server_logs.cancel()

    # ── forum helpers ────────────────────────────────────────

    async def _find_or_create_forum(self, guild: discord.Guild, name: str, topic: str) -> discord.ForumChannel | None:
        forum = discord.utils.get(guild.channels, name=name, type=discord.ChannelType.forum)
        if forum is not None:
            return forum
        try:
            return await guild.create_forum(name=name, topic=topic, reason=f"{name} forum - created by setup command")
        except Exception:
            return None

    async def _ensure_thread(self, forum: discord.ForumChannel, name: str, intro: str) -> int | None:
        existing = discord.utils.find(lambda t, n=name: t.name == n or name in t.name or t.name.startswith(name[:10]), forum.threads)
        if existing:
            return existing.id
        try:
            result = await forum.create_thread(
                name=name,
                content=intro,
                auto_archive_duration=10080,
            )
            thread = await _normalize_thread(result)
            return thread.id if thread else None
        except Exception:
            return None

    # ── background poster ────────────────────────────────────

    @tasks.loop(seconds=15)
    async def post_server_logs(self):
        for guild in self.bot.guilds:
            cfg = guild_settings.get_server_log_config(guild.id)
            if not cfg or not cfg.get("enabled"):
                continue
            server_thread = guild.get_thread(cfg.get("server_events_thread_id")) if cfg.get("server_events_thread_id") else None
            chat_thread = guild.get_thread(cfg.get("chat_thread_id")) if cfg.get("chat_thread_id") else None

            if isinstance(server_thread, discord.Thread):
                for ev in guild_settings.get_unposted_server_events(guild.id):
                    name = ev["player_name"] or "?"
                    if ev["event_type"] == "join":
                        icon, verb = "🟢", bot_i18n.t(guild.id, "server_event_join")
                    else:
                        icon, verb = "🔴", bot_i18n.t(guild.id, "server_event_leave")
                    ts = int(ev["created_at"].timestamp()) if getattr(ev["created_at"], "timestamp", None) else None
                    ts_part = f" · <t:{ts}:f>" if ts else ""
                    try:
                        await server_thread.send(f"{icon} **{name}** — {verb}{ts_part}")
                        guild_settings.mark_server_event_posted(ev["id"])
                    except Exception:
                        break

            if isinstance(chat_thread, discord.Thread):
                posts = 0
                for log in guild_settings.get_unposted_chat_forum_logs(guild.id):
                    if posts >= 15:
                        break
                    player = log["player_name"] or "?"
                    icon = "➡️" if log["direction"] == "out" else "💬"
                    channel = (log["channel"] or "global").replace("[", "").replace("]", "")
                    try:
                        await chat_thread.send(f"{icon} `{channel}` **{player}**: {log['message'][:1900]}")
                        guild_settings.mark_chat_forum_posted(log["id"])
                        posts += 1
                    except Exception:
                        break

    @post_server_logs.before_loop
    async def before_post_server_logs(self):
        await self.bot.wait_until_ready()

    # ── /setup-server-logs ───────────────────────────────────
    @app_commands.command(name="setup-server-logs", description="Create the server-logs forum (player join/leave) (Admin only)")
    @app_commands.describe(channel="Existing forum to use (optional)")
    async def setup_server_logs(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        forum = channel if isinstance(channel, discord.ForumChannel) else await self._find_or_create_forum(
            interaction.guild, "server-logs", bot_i18n.t(interaction.guild_id, "server_logs_topic"),
        )
        if forum is None:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "forum_error", error="create failed"), ephemeral=True)
        thread_id = await self._ensure_thread(forum, "👤 Player Events", bot_i18n.t(interaction.guild_id, "server_logs_thread_intro"))
        if not thread_id:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "forum_error", error="thread failed"), ephemeral=True)
        guild_settings.update_server_log_config(interaction.guild_id, server_forum_id=forum.id, server_events_thread_id=thread_id)
        await interaction.followup.send(
            bot_i18n.t(interaction.guild_id, "server_logs_forum_ready", forum=forum.mention, thread=f"<#{thread_id}>"),
            ephemeral=True,
        )

    # ── /setup-game-chat-forum ───────────────────────────────
    @app_commands.command(name="setup-game-chat-forum", description="Create the game-chat forum (in-game chat log) (Admin only)")
    @app_commands.describe(channel="Existing forum to use (optional)")
    async def setup_game_chat_forum(self, interaction: discord.Interaction, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        forum = channel if isinstance(channel, discord.ForumChannel) else await self._find_or_create_forum(
            interaction.guild, "game-chat", bot_i18n.t(interaction.guild_id, "chat_forum_topic"),
        )
        if forum is None:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "forum_error", error="create failed"), ephemeral=True)
        thread_id = await self._ensure_thread(forum, "💬 Game Chat", bot_i18n.t(interaction.guild_id, "chat_forum_thread_intro"))
        if not thread_id:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "forum_error", error="thread failed"), ephemeral=True)
        guild_settings.update_server_log_config(interaction.guild_id, chat_forum_id=forum.id, chat_thread_id=thread_id)
        await interaction.followup.send(
            bot_i18n.t(interaction.guild_id, "chat_forum_ready", forum=forum.mention, thread=f"<#{thread_id}>"),
            ephemeral=True,
        )

    # ── /server-logs-enable ──────────────────────────────────
    @app_commands.command(name="server-logs-enable", description="Enable or disable posting to server-logs & game-chat forums (Admin)")
    @app_commands.describe(enabled="Enable or disable")
    async def server_logs_enable(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_server_log_config(interaction.guild_id, enabled=enabled)
        state = bot_i18n.t(interaction.guild_id, "enabled_word") if enabled else bot_i18n.t(interaction.guild_id, "disabled_word")
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "server_logs_toggled", state=state), ephemeral=True)


async def setup(bot):
    await bot.add_cog(ServerLogs(bot))