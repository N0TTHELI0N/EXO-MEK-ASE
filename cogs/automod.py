import os
import re
import glob
import discord
from discord.ext import commands, tasks
from discord import app_commands

import guild_settings
import bot_i18n
import config


# ── Config ──────────────────────────────────────────────────

DEFAULT_LOG_PATH = r"C:\path\to\ARK\ShooterGame\Saved\Logs\ShooterGame.log"

# Default words to flag (Arabic + English)
DEFAULT_PROFANITY_LIST = [
    "قحبة", "زب", "كس", "lhv", "zib", "f***", "f**k", "shit", "fuck",
    "bitch", "ass", "damn", "crap", "slut", "retard", "idiot"
]

# Max messages per user in TIME_WINDOW before mute
SPAM_LIMIT = 5
TIME_WINDOW_SECONDS = 10
MUTE_DURATION_MINUTES = 5


# ── Cog ─────────────────────────────────────────────────────

class Automod(commands.Cog):
    MAX_KNOWN_LINES = 10000
    
    def __init__(self, bot):
        self.bot = bot
        self._recent_messages: dict[int, list[float]] = {}
        self.log_path = DEFAULT_LOG_PATH
        self.known_lines = set()
        self.watch_logs.start()

    def cog_unload(self):
        self.watch_logs.cancel()

    # ── Helpers ──────────────────────────────────────────────

    def _get_all_words(self, guild_id: int) -> list[str]:
        """Get all profanity words: default + custom from DB."""
        custom_words = guild_settings.get_automod_words(guild_id)
        return list(set(DEFAULT_PROFANITY_LIST + custom_words))

    def _get_log_channel(self, guild_id: int) -> int | None:
        return guild_settings.get_setting(guild_id, "automod_log_channel_id") or config.AUTOMOD_LOG_CHANNEL_ID

    # ── Log Watcher ──────────────────────────────────────────
    @tasks.loop(seconds=10)
    async def watch_logs(self):
        """Watch the ARK log file for flagged keywords."""
        if not os.path.exists(self.log_path):
            return

        try:
            with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            for line in lines:
                line_key = line.strip()
                if line_key in self.known_lines:
                    continue
                self.known_lines.add(line_key)
                
                if len(self.known_lines) > self.MAX_KNOWN_LINES:
                    self.known_lines = set(list(self.known_lines)[-5000:])

                lower = line.lower()
                for guild in self.bot.guilds:
                    all_words = self._get_all_words(guild.id)
                    for word in all_words:
                        if word.lower() in lower:
                            ch_id = self._get_log_channel(guild.id)
                            if ch_id:
                                ch = guild.get_channel(ch_id)
                                if ch:
                                    await ch.send(f"🚨 **Automod Alert**\n```\n{line.strip()[:1900]}\n```")
                            break
        except Exception as e:
            print(f"[Automod] Log read error: {e}")

    @watch_logs.before_loop
    async def before_watch(self):
        await self.bot.wait_until_ready()

    # ── Message Listener ─────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        guild_id = message.guild.id
        enabled = guild_settings.get_setting(guild_id, "automod_enabled", False)
        if not enabled:
            return

        content = message.content.lower()

        # 1. Profanity check (default + custom words)
        all_words = self._get_all_words(guild_id)
        for word in all_words:
            if word.lower() in content:
                try:
                    await message.delete()
                except Exception:
                    pass
                await message.channel.send(
                    f"⚠️ {message.author.mention} —违规词汇已删除。",
                    delete_after=5,
                )
                guild_settings.log_action(
                    guild_id, "automod", message.author.id, str(message.author),
                    message.author.display_name, sub_type="profanity",
                    details={"word": word, "channel": message.channel.name}
                )
                return

        # 2. Spam detection
        import time
        now = time.time()
        uid = message.author.id
        if uid not in self._recent_messages:
            self._recent_messages[uid] = []
        self._recent_messages[uid].append(now)
        self._recent_messages[uid] = [t for t in self._recent_messages[uid] if now - t < TIME_WINDOW_SECONDS]

        if len(self._recent_messages[uid]) >= SPAM_LIMIT:
            try:
                mute_role = discord.utils.get(message.guild.roles, name="Muted")
                if not mute_role:
                    mute_role = await message.guild.create_role(name="Muted", permissions=discord.Permissions(send_messages=False))
                    for ch in message.guild.text_channels:
                        await ch.set_permissions(mute_role, send_messages=False)

                await message.author.add_roles(mute_role, reason="Automod: spam")
                await message.channel.send(
                    f"🔇 {message.author.mention} muted for {MUTE_DURATION_MINUTES} min (spam).",
                    delete_after=10,
                )
                guild_settings.log_action(
                    guild_id, "automod", message.author.id, str(message.author),
                    message.author.display_name, sub_type="spam",
                    details={"messages_count": len(self._recent_messages[uid])}
                )
                import asyncio
                await asyncio.sleep(MUTE_DURATION_MINUTES * 60)
                await message.author.remove_roles(mute_role, reason="Automod: mute expired")
            except Exception as e:
                print(f"[Automod] Mute error: {e}")

            self._recent_messages[uid] = []


async def setup(bot):
    await bot.add_cog(Automod(bot))
