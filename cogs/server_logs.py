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