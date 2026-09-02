import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
import bot_i18n
import guild_settings
import config


TOP_SERVERS_URL = "https://topg.org/api/servers"


# ── Cog ─────────────────────────────────────────────────────

class TopServers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="top-servers", description="View ARK server rankings on TopServers")
    @app_commands.describe(game="Game to search", count="Number of servers to show (1-25)")
    @app_commands.choices(game=[
        app_commands.Choice(name="ARK: Survival Evolved", value="ark"),
        app_commands.Choice(name="ARK: Survival Ascended", value="arksa"),
    ])
    async def top_servers(self, interaction: discord.Interaction, game: app_commands.Choice[str] = None, count: int = 10):
        game_val = game.value if game else "ark"
        count = max(1, min(count, 25))

        await interaction.response.defer()

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "key": config.TOPSERVERS_API_KEY,
                    "game": game_val,
                    "page": 1,
                }
                async with session.get(TOP_SERVERS_URL, params=params) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send("❌ Failed to fetch server list.", ephemeral=True)
                    data = await resp.json()
        except Exception as e:
            return await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)

        servers = data.get("servers", [])[:count]
        if not servers:
            return await interaction.followup.send("No servers found.", ephemeral=True)

        lang = guild_settings.get_setting(interaction.guild_id, "bot_language", "ar")

        lines = []
        for i, s in enumerate(servers):
            rank = s.get("rank", i + 1)
            name = s.get("name", "Unknown")
            players = s.get("players", "0/0")
            ip_addr = s.get("ip", "")
            port_num = s.get("port", "")
            lines.append(f"**#{rank}** {name}\n`{ip_addr}:{port_num}` — 👥 {players}")

        title = "🏆 Top ARK Servers" if lang == "en" else "🏆 أفضل سيرفرات ARK"
        embed = discord.Embed(title=title, description="\n\n".join(lines), color=discord.Color.gold())
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(TopServers(bot))
