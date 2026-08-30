# playtime.py - Track ARK player playtime by polling the Nitrado player list.
# The Nitrado API only reports currently-online players, so playtime is
# accumulated over time here and stored per guild in player_playtime.

import discord
from discord.ext import commands, tasks
from discord import app_commands
import guild_settings
import nitrado
import bot_i18n


def _fmt(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{sec}s")
    return " ".join(parts)


class Playtime(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.track.start()

    def cog_unload(self):
        self.track.cancel()

    @tasks.loop(minutes=1)
    async def track(self):
        for guild in self.bot.guilds:
            try:
                client = nitrado.get_client(guild.id)
                if client is None:
                    continue
                players = client.get_player_list()
                guild_settings.record_playtime(guild.id, players, 60)
            except Exception as e:
                print(f"[playtime] track error guild={guild.id}: {type(e).__name__}: {e}", flush=True)

    @track.before_loop
    async def before_track(self):
        await self.bot.wait_until_ready()

    # ── /top-players ─────────────────────────────────────────
    @app_commands.command(name="top-players", description="Show the top players by time spent on the server")
    @app_commands.describe(limit="Number of players to show (default 10)")
    async def top_players(self, interaction: discord.Interaction, limit: int = 10):
        limit = max(1, min(limit, 25))
        top = guild_settings.get_top_players(interaction.guild_id, limit=limit)
        if not top:
            return await interaction.response.send_message(
                bot_i18n.t(interaction.guild_id, "playtime_no_data"), ephemeral=True
            )
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, p in enumerate(top):
            prefix = medals[i] if i < 3 else f"#{i+1}"
            lines.append(f"{prefix} **{p['player_name']}** — {_fmt(p['seconds'])}")
        embed = discord.Embed(
            title="🏆 Top Players",
            description="\n".join(lines) if lines else bot_i18n.t(interaction.guild_id, "playtime_no_data"),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=bot_i18n.t(interaction.guild_id, "playtime_tracking_note"))
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(Playtime(bot))
