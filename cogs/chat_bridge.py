import re
import time
from collections import deque

import discord
from discord.ext import commands, tasks
from discord import app_commands

import guild_settings
import nitrado
import config
import bot_i18n


CHAT_BRIDGE_INTERVAL_SECONDS = 20
MAX_SEEN = 20000
ECHO_FINGERPRINT_TTL = 120

# Tolerant matchers for ARK ShooterGame.log chat lines.
# Chat lines generally look like:
#   [2024.01.02-03.04.05:123][456]LogChatMessage:  PlayerName: hello
#   [2024.01.02-03.04.05:123][456]LogChatMessage: [Global][PlayerName]: hello
#   [2024.01.02-03.04.05:123][456]LogChatMessage: [TribeName][PlayerName]: hello
#   LogChatMessage: ... [Alliance][Tribe]Name : text  (alliance)
_TS_CAT = re.compile(r"^\[[^\]]+\]\[[^\]]+\]\s*[^:]*?:\s*(.*)$")
_PLAIN_CAT = re.compile(r"^[^:]+:\s*(.*)$")
_CHAT_BODY = re.compile(r"^(?:\[(?P<channel>[^\]]+)\]\s*)?(?P<player>[^:\]]+?)\s*:\s*(?P<msg>.+)$")


def _parse_chat_line(line: str):
    text = line
    m = _TS_CAT.match(text)
    if m:
        text = m.group(1)
    else:
        m = _PLAIN_CAT.match(text)
        if m:
            text = m.group(1)
    text = text.strip()
    if not text:
        return None
    m = _CHAT_BODY.match(text)
    if not m:
        return None
    channel = (m.group("channel") or "global").strip()
    player = m.group("player").strip()
    message = m.group("msg").strip()
    if not player or not message:
        return None
    if _is_noise(player, message, channel):
        return None
    return channel, player, message


def _is_noise(player: str, message: str, channel: str) -> bool:
    low_p = player.lower()
    low_m = message.lower()
    if low_p in ("server", "console", "admin"):
        return True
    if any(x in low_p for x in ("[developer]", "[dev]", "serverchatmessage")):
        return True
    if low_m.startswith(("serverchatmessage", "?setadminpassword", "?adminpassword")):
        return True
    if "chat command sent to server" in low_m:
        return True
    return False


class ChatBridge(commands.Cog):
    """In-game ARK chat bridge & log."""

    def __init__(self, bot):
        self.bot = bot
        self.seen_lines = {}
        # avoid re-forwarding our own ServerChatMessage echoes
        self._echo_guard = deque(maxlen=200)
        # avoid flooding a Discord channel during a log burst
        self._post_guard = deque(maxlen=100)

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _fp(channel, player, message):
        return (channel or "global", (player or "").strip().lower(), (message or "").strip().lower())

    def _is_echo(self, channel, player, message):
        fp = self._fp(channel, player, message)
        now = time.time()
        for saved in self._echo_guard:
            if saved[0] == fp and now - saved[1] < ECHO_FINGERPRINT_TTL:
                return True
        return False

    def _remember_sent(self, channel, player, message):
        self._echo_guard.append((self._fp(channel, player, message), time.time()))

    def _is_new_line(self, guild_id, text):
        last = self.seen_lines.get(guild_id)
        if last is None:
            self.seen_lines[guild_id] = text
            return True
        if text == last:
            return False
        # accept any new line within a bounded window; cursor is the last seen line
        self.seen_lines[guild_id] = text
        return True

    @staticmethod
    async def _send_to_game(guild_id, sender_name: str, message: str) -> bool:
        # Try the standard ServerChatMessage RCON broadcast first, then fallbacks.
        attempts = [
            f"ServerChatMessage 0 [Discord]{sender_name} {message}",
            f"ServerChatMessage 0 [Discord] {sender_name}: {message}",
        ]
        for cmd in attempts:
            resp = await asyncio_to_thread(nitrado.send_rcon, guild_id, cmd)
            if resp is not None:
                return True
        return False

    # ── background monitor: game -> Discord/log ─────────────
    @tasks.loop(seconds=CHAT_BRIDGE_INTERVAL_SECONDS)
    async def chat_monitor(self):
        import discord as _d
        for guild in self.bot.guilds:
            cfg = guild_settings.get_chat_bridge_config(guild.id)
            if not cfg or not cfg.get("enabled"):
                continue
            client = nitrado.get_client(guild.id)
            if client is None:
                continue
            try:
                raw = await asyncio_to_thread(client.get_logs, 400)
            except Exception:
                continue
            lines = (raw or "").splitlines()
            # First run: just remember the latest line so we only capture NEW chat.
            if guild.id not in self.seen_lines:
                if lines:
                    self.seen_lines[guild.id] = lines[-1].strip()
                continue
            log_channel = guild.get_channel(cfg.get("log_channel_id") or 0)
            relay_channel = guild.get_channel(cfg.get("relay_channel_id") or 0)
            posts_this_tick = 0
            for line in lines:
                text = (line or "").strip()
                if not text:
                    continue
                if not self._is_new_line(guild.id, text):
                    continue
                parsed = _parse_chat_line(text)
                if not parsed:
                    continue
                channel, player, message = parsed
                if self._is_echo(channel, player, message):
                    continue
                guild_settings.add_chat_log(
                    guild.id, channel, player, message,
                    tribe_name=player, raw_line=text, direction="in",
                )
                # forward to one-way log channel
                target = None
                if cfg.get("relay_out") and isinstance(relay_channel, _d.TextChannel):
                    target = relay_channel
                elif isinstance(log_channel, _d.TextChannel):
                    target = log_channel
                if target is None:
                    continue
                if posts_this_tick >= 15:
                    break
                if self._post_guard and time.time() - self._post_guard[0][1] < 0.6:
                    continue
                self._post_guard.append((1, time.time()))
                try:
                    await target.send(
                        f"💬 **{channel}** · **{player}**: {message[:1900]}"
                    )
                    posts_this_tick += 1
                except Exception:
                    continue

    @chat_monitor.before_loop
    async def before_chat_monitor(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            cfg = guild_settings.get_chat_bridge_config(guild.id)
            if cfg and cfg.get("last_log_line"):
                self.seen_lines[guild.id] = cfg["last_log_line"]

    # ── relay: Discord -> game ───────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        cfg = guild_settings.get_chat_bridge_config(message.guild.id)
        if not cfg or not cfg.get("enabled") or not cfg.get("relay_in"):
            return
        relay_id = cfg.get("relay_channel_id")
        if not relay_id or message.channel.id != relay_id:
            return
        content = message.content.strip()
        if not content or content.startswith("/") or content.startswith("!"):
            return
        if await self._send_to_game(message.guild.id, message.author.display_name, content):
            self._remember_sent("game", f"[Discord] {message.author.display_name}".lower(), content)
            guild_settings.add_chat_log(
                message.guild.id, "outgoing", message.author.display_name,
                content, raw_line=content, direction="out",
            )
            try:
                await message.add_reaction("✅")
            except Exception:
                pass

    # ── config commands ──────────────────────────────────────
    @app_commands.command(name="chat-bridge-enable", description="Enable or disable the in-game chat bridge (Admin)")
    @app_commands.describe(enabled="Enable or disable")
    async def chat_bridge_enable(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_chat_bridge_config(interaction.guild_id, enabled=enabled)
        await interaction.response.send_message(f"✅ In-game chat bridge **{'enabled' if enabled else 'disabled'}.**", ephemeral=True)

    @app_commands.command(name="chat-bridge-channel", description="Set the one-way in-game chat log channel (Admin)")
    @app_commands.describe(channel="Channel for in-game chat log")
    async def chat_bridge_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_chat_bridge_config(interaction.guild_id, log_channel_id=channel.id)
        await interaction.response.send_message(f"✅ One-way chat log channel set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="chat-bridge-relay", description="Set the two-way Discord<->game relay channel (Admin)")
    @app_commands.describe(channel="Channel to relay game chat both ways")
    async def chat_bridge_relay(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_chat_bridge_config(interaction.guild_id, relay_channel_id=channel.id)
        await interaction.response.send_message(f"✅ Two-way relay channel set to {channel.mention}", ephemeral=True)

    @app_commands.command(name="chat-bridge-toggle", description="Control chat bridge direction (Admin)")
    @app_commands.describe(
        game_to_discord="Forward in-game chat to the relay channel",
        discord_to_game="Send Discord messages in the relay channel into the game",
    )
    async def chat_bridge_toggle(self, interaction: discord.Interaction, game_to_discord: bool = None, discord_to_game: bool = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        cfg = guild_settings.get_chat_bridge_config(interaction.guild_id)
        kwargs = {}
        if game_to_discord is not None:
            kwargs["relay_out"] = game_to_discord
        if discord_to_game is not None:
            kwargs["relay_in"] = discord_to_game
        if kwargs:
            guild_settings.update_chat_bridge_config(interaction.guild_id, **kwargs)
        cfg = guild_settings.get_chat_bridge_config(interaction.guild_id)
        await interaction.response.send_message(
            f"⚙️ Chat bridge: in→discord: **{cfg.get('relay_out')}**, discord→game: **{cfg.get('relay_in')}**", ephemeral=True,
        )

    @app_commands.command(name="chat-bridge-send", description="Send a message into the game chat as Discord (Admin)")
    @app_commands.describe(message="Message to send into the game")
    async def chat_bridge_send(self, interaction: discord.Interaction, message: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        ok = await self._send_to_game(interaction.guild_id, interaction.user.display_name, message)
        if ok:
            self._remember_sent("game", f"[Discord] {interaction.user.display_name}".lower(), message)
            guild_settings.add_chat_log(interaction.guild_id, "outgoing", interaction.user.display_name, message, raw_line=message, direction="out")
        await interaction.response.send_message("✅ Message sent into game chat." if ok else "❌ Failed — server not reachable.", ephemeral=True)

    @app_commands.command(name="chat-bridge-status", description="Show chat bridge status")
    async def chat_bridge_status(self, interaction: discord.Interaction):
        cfg = guild_settings.get_chat_bridge_config(interaction.guild_id)
        lines = [
            f"**Enabled:** {cfg.get('enabled')}",
            f"**Log channel:** <#{cfg.get('log_channel_id')}>" if cfg.get("log_channel_id") else "**Log channel:** not set",
            f"**Relay channel:** <#{cfg.get('relay_channel_id')}>" if cfg.get("relay_channel_id") else "**Relay channel:** not set",
            f"**In→Discord (relay_out):** {cfg.get('relay_out')}",
            f"**Discord→Game (relay_in):** {cfg.get('relay_in')}",
        ]
        embed = discord.Embed(title="💬 Chat Bridge", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def asyncio_to_thread(fn, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


async def setup(bot):
    await bot.add_cog(ChatBridge(bot))
