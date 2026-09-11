import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
import guild_settings
import bot_i18n


def _asyncio_to_thread(fn, *args, **kwargs):
    return asyncio.to_thread(fn, *args, **kwargs)


class Vanity(commands.Cog):
    """Auto-updating vanity voice channel names showing server/member counts."""

    def __init__(self, bot):
        self.bot = bot
        self.member_count_loop.start()

    def cog_unload(self):
        self.member_count_loop.cancel()

    def _counts(self):
        discords = len(self.bot.guilds)
        members = sum(1 for g in self.bot.guilds for m in g.members if not m.bot)
        return members, discords

    @tasks.loop(minutes=30)
    async def member_count_loop(self):
        if not self.bot.guilds:
            return
        members, discords = self._counts()
        for guild in self.bot.guilds:
            users_id = guild_settings.get_setting(guild.id, "vanity_users_channel")
            discords_id = guild_settings.get_setting(guild.id, "vanity_discords_channel")
            if not users_id and not discords_id:
                continue
            try:
                if users_id:
                    ch = guild.get_channel(users_id)
                    if ch and isinstance(ch, discord.VoiceChannel):
                        await ch.edit(name=f"Total Users: {members}")
                if discords_id:
                    ch = guild.get_channel(discords_id)
                    if ch and isinstance(ch, discord.VoiceChannel):
                        await ch.edit(name=f"Total Discords: {discords}")
            except discord.HTTPException:
                continue
            except Exception:
                continue

    @member_count_loop.before_loop
    async def before_member_count_loop(self):
        await self.bot.wait_until_ready()

    # ── /set-vanity-channels ─────────────────────────────────

    @app_commands.command(name="set-vanity-channels", description="Set voice channels that show member counts (Admin only)")
    @app_commands.describe(users_channel="Voice channel showing Total Users", discords_channel="Voice channel showing Total Discords")
    async def set_vanity_channels(
        self,
        interaction: discord.Interaction,
        users_channel: discord.VoiceChannel = None,
        discords_channel: discord.VoiceChannel = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        if users_channel is None:
            guild_settings.update_setting(interaction.guild_id, "vanity_users_channel", None)
        else:
            guild_settings.update_setting(interaction.guild_id, "vanity_users_channel", users_channel.id)
        if discords_channel is None:
            guild_settings.update_setting(interaction.guild_id, "vanity_discords_channel", None)
        else:
            guild_settings.update_setting(interaction.guild_id, "vanity_discords_channel", discords_channel.id)
        guild_settings.log_action(
            interaction.guild_id, "vanity", interaction.user.id, str(interaction.user), None,
            sub_type="set", details={"users": users_channel.id if users_channel else None,
                                     "discords": discords_channel.id if discords_channel else None},
        )
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "vanity_set_ok",
                       users=f"<#{users_channel.id}>" if users_channel else bot_i18n.t(interaction.guild_id, "vanity_disabled"),
                       discords=f"<#{discords_channel.id}>" if discords_channel else bot_i18n.t(interaction.guild_id, "vanity_disabled")),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Vanity(bot))