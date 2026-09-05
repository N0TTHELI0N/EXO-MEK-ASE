import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone
import guild_settings
import shop_db
import bot_i18n


# ── Cog ─────────────────────────────────────────────────────

class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_update.start()

    def cog_unload(self):
        self.auto_update.cancel()

    # ── Auto Update Task ─────────────────────────────────────
    @tasks.loop(minutes=5)
    async def auto_update(self):
        for guild in self.bot.guilds:
            config = guild_settings.get_setting(guild.id, "leaderboard_config", {})
            if not config.get("enabled"):
                continue
            ch = guild.get_channel(config.get("channel_id", 0))
            if not ch:
                continue
            # placeholder update
            pass

    @auto_update.before_loop
    async def before_auto_update(self):
        await self.bot.wait_until_ready()

    # ── /leaderboard ─────────────────────────────────────────
    @app_commands.command(name="leaderboard", description="Show the tribe leaderboard")
    async def leaderboard(self, interaction: discord.Interaction):
        board = shop_db.get_leaderboard(interaction.guild_id, limit=10)
        if not board:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "tribelog_no_entries"), ephemeral=True)

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, pts) in enumerate(board):
            prefix = medals[i] if i < 3 else f"#{i+1}"
            lines.append(f"{prefix} **{name}** — {pts} pts")

        embed = discord.Embed(
            title=bot_i18n.t(interaction.guild_id, "leaderboard_title"),
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    # ── /setup-leaderboard ───────────────────────────────────
    @app_commands.command(name="setup-leaderboard", description="Setup automatic leaderboard announcements (Admin only)")
    @app_commands.describe(channel="Channel for announcements", interval="Update interval in minutes")
    async def setup_leaderboard(self, interaction: discord.Interaction, channel: discord.TextChannel, interval: int = 5):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, "leaderboard_config", {
            "enabled": True,
            "channel_id": channel.id,
            "interval": interval,
        })
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "leaderboard_setup", channel=channel.mention, interval=interval), ephemeral=True)

    # ── /set-tribe-owner ─────────────────────────────────────
    @app_commands.command(name="set-tribe-owner", description="Set the tribe owner for a member (Admin only)")
    @app_commands.describe(member="Discord member", tribe_name="Tribe name")
    async def set_tribe_owner(self, interaction: discord.Interaction, member: discord.Member, tribe_name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, f"tribe_owner_{member.id}", tribe_name)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "tribe_owner_set", member=member.mention, tribe=tribe_name), ephemeral=True)

    # ── /add-tribe-points ────────────────────────────────────
    @app_commands.command(name="add-tribe-points", description="Add points to a tribe (Admin only)")
    @app_commands.describe(tribe_name="Tribe name", amount="Points to add")
    async def add_tribe_points(self, interaction: discord.Interaction, tribe_name: str, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        shop_db.add_points(interaction.guild_id, tribe_name, amount)
        guild_settings.log_action(interaction.guild_id, "leaderboard", interaction.user.id, str(interaction.user), tribe_name, sub_type="points_added", details={"amount": amount})
        balance = shop_db.get_points(interaction.guild_id, tribe_name)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "tribe_points_added", amount=amount, tribe=tribe_name, balance=balance))

    # ── /remove-tribe-points ─────────────────────────────────
    @app_commands.command(name="remove-tribe-points", description="Remove points from a tribe (Admin only)")
    @app_commands.describe(tribe_name="Tribe name", amount="Points to remove")
    async def remove_tribe_points(self, interaction: discord.Interaction, tribe_name: str, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        shop_db.remove_points(interaction.guild_id, tribe_name, amount)
        guild_settings.log_action(interaction.guild_id, "leaderboard", interaction.user.id, str(interaction.user), tribe_name, sub_type="points_removed", details={"amount": amount})
        balance = shop_db.get_points(interaction.guild_id, tribe_name)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "tribe_points_removed", amount=amount, tribe=tribe_name, balance=balance))


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
