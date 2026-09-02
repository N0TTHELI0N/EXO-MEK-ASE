import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
import guild_settings


ASA_SERVERS_URL = "https://cdn2.arkdedicated.com/servers/asa/unofficialserverlist.json"


# ── Cog ─────────────────────────────────────────────────────

class TopServers(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="top-servers", description="View top ASA PlayStation servers by player count")
    @app_commands.describe(count="Number of servers to show (1-25)")
    async def top_servers(self, interaction: discord.Interaction, count: int = 10):
        count = max(1, min(count, 25))

        await interaction.response.defer()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(ASA_SERVERS_URL) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send("❌ Failed to fetch server list.", ephemeral=True)
                    data = await resp.json(content_type=None)
        except Exception as e:
            return await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)

        ps5_servers = [s for s in data if "PS5" in s.get("PlatformType", "")]
        ps5_servers.sort(key=lambda s: s.get("NumPlayers", 0), reverse=True)
        top = ps5_servers[:count]

        if not top:
            return await interaction.followup.send("No PlayStation servers found.", ephemeral=True)

        lang = guild_settings.get_setting(interaction.guild_id, "bot_language", "ar")

        lines = []
        for i, s in enumerate(top):
            rank = i + 1
            name = s.get("Name", "Unknown")
            ip_addr = s.get("IP", "")
            port = s.get("Port", "")
            players = s.get("NumPlayers", 0)
            max_players = s.get("MaxPlayers", 0)
            map_name = s.get("MapName", "").replace("_WP", "")
            is_pve = s.get("SessionIsPve", 0)
            mode = "PVE" if is_pve else "PVP"
            lines.append(f"**#{rank}** {name}\n`{ip_addr}:{port}` — 👥 {players}/{max_players} • {map_name} • {mode}")

        title = "🏆 Top PlayStation ASA Servers" if lang == "en" else "🏆 أفضل سيرفرات ASA لبلاي ستيشن"
        embed = discord.Embed(title=title, description="\n\n".join(lines), color=discord.Color.gold())
        embed.set_footer(text=f"{len(ps5_servers)} PlayStation servers tracked")
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(TopServers(bot))
