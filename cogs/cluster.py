import discord
from discord.ext import commands
from discord import app_commands

import guild_settings
import bot_i18n
import nitrado
import config


def _log(guild_id, sub_type, user, target=None, details=None):
    guild_settings.log_admin_action(
        guild_id, user.id if user else None, str(user) if user else None,
        sub_type, target, details,
    )


class Cluster(commands.Cog):
    """Cluster Alpha tracking: designate alpha tribes per cluster."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="cluster-set", description="Set or update the alpha tribe for a cluster")
    @app_commands.describe(cluster_name="Cluster name (map/adventure name)", tribe_name="Alpha tribe name", disc_channel="Optional Discord channel for alpha announcements")
    async def cluster_set(self, interaction: discord.Interaction, cluster_name: str, tribe_name: str, disc_channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.add_cluster(
            interaction.guild_id, cluster_name.strip(), tribe_name.strip(),
            disc_channel=disc_channel.id if disc_channel else None,
            created_by=interaction.user.id,
        )
        _log(interaction.guild_id, "cluster_set", interaction.user, tribe_name, details={"cluster": cluster_name})
        ch = f" <#{disc_channel.id}>" if disc_channel else ""
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "cluster_alpha_set", cluster=cluster_name, tribe=tribe_name, channel=ch),
            ephemeral=True,
        )

    @app_commands.command(name="cluster-list", description="List all clusters and their alpha tribes")
    async def cluster_list(self, interaction: discord.Interaction):
        clusters = guild_settings.get_clusters(interaction.guild_id)
        if not clusters:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "cluster_empty"), ephemeral=True)
        lines = []
        for c in clusters:
            ch = f" <#{c['disc_channel']}>" if c['disc_channel'] else ""
            lines.append(f"🌐 **{c['cluster_name']}** → ⭐ **{c['tribe_name']}**{ch}")
        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "cluster_alpha_title"), description="\n".join(lines), color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="cluster-remove", description="Remove a cluster entry")
    @app_commands.describe(cluster_id="Cluster ID (see /cluster-list)")
    async def cluster_remove(self, interaction: discord.Interaction, cluster_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        if guild_settings.remove_cluster(cluster_id, interaction.guild_id):
            _log(interaction.guild_id, "cluster_remove", interaction.user, None, details={"cluster_id": cluster_id})
            await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "cluster_removed", cluster_id=cluster_id), ephemeral=True)
        else:
            await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "cluster_not_found", cluster_id=cluster_id), ephemeral=True)

    @app_commands.command(name="cluster-status", description="Show cluster alpha status")
    async def cluster_status(self, interaction: discord.Interaction):
        clusters = guild_settings.get_clusters(interaction.guild_id)
        lines = [bot_i18n.t(interaction.guild_id, "cluster_active_count", count=len(clusters))]
        for c in clusters:
            lines.append(f"• **{c['cluster_name']}** → **{c['tribe_name']}**")
        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "cluster_status_title"), description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Cluster(bot))
