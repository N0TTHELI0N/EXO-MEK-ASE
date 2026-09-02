import discord
from discord.ext import commands
from discord import app_commands
import bot_i18n
import config
import guild_settings
import shop_db
import commands_manifest


# ── Command list for autocomplete ───────────────────────────
# Derived from commands_manifest.py so it always matches reality.

ALL_COMMANDS = [cmd[0] for cmd in commands_manifest.COMMANDS]


async def command_autocomplete(interaction: discord.Interaction, current: str):
    return [
        app_commands.Choice(name=c, value=c)
        for c in ALL_COMMANDS if current.lower() in c.lower()
    ][:25]


# ── Helper ──────────────────────────────────────────────────

def is_server_owner():
    async def predicate(ctx):
        return ctx.guild and ctx.author.id == ctx.guild.owner_id
    return commands.check(predicate)


def is_tribe_owner_or_admin():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        return False
    return commands.check(predicate)


# ── Cog ─────────────────────────────────────────────────────

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── /set-nitrado-token ───────────────────────────────────
    @app_commands.command(name="set-nitrado-token", description="Set Nitrado API token for this server (Admin only)")
    @app_commands.describe(
        api_token="Nitrado API token",
        service_id="Nitrado service ID"
    )
    async def set_nitrado_token(self, interaction: discord.Interaction, api_token: str, service_id: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, "nitrado_api_token", api_token)
        if service_id:
            guild_settings.update_setting(interaction.guild_id, "nitrado_service_id", service_id)
        await interaction.response.send_message("✅ Nitrado token saved.", ephemeral=True)

    # ── /set-log-channel ─────────────────────────────────────
    @app_commands.command(name="set-log-channel", description="Set the log channel for bot activity (Admin only)")
    @app_commands.describe(channel="Channel to use for logs")
    async def set_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, "log_channel_id", channel.id)
        await interaction.response.send_message(f"✅ Log channel set to {channel.mention}", ephemeral=True)

    # ── /set-license ─────────────────────────────────────────
    @app_commands.command(name="set-license", description="Set the license key for this guild (Admin only)")
    @app_commands.describe(key="License key (issued by the bot owner)")
    async def set_license(self, interaction: discord.Interaction, key: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        parsed = guild_settings.parse_license_key(key)
        if parsed is None:
            return await interaction.response.send_message(
                "❌ Invalid license key format.", ephemeral=True
            )
        if not guild_settings.verify_license_key(interaction.guild_id, key):
            return await interaction.response.send_message(
                "❌ This license key does not match the license issued for this server, or it has expired.",
                ephemeral=True,
            )
        expiry = guild_settings.get_license_expiry(interaction.guild_id)
        if expiry == "Unlimited":
            msg = "♾️ License verified (unlimited)."
        else:
            msg = f"✅ License verified. Active until {expiry}."
        await interaction.response.send_message(msg, ephemeral=True)

    # ── /set-language ────────────────────────────────────────
    @app_commands.command(name="set-language", description="Set bot language (Admin only)")
    @app_commands.describe(language="Bot language")
    @app_commands.choices(language=[
        app_commands.Choice(name="العربية", value="ar"),
        app_commands.Choice(name="English", value="en"),
    ])
    async def set_language(self, interaction: discord.Interaction, language: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, "bot_language", language.value)
        guild_settings.log_action(
            interaction.guild_id, "admin_command", interaction.user.id, str(interaction.user),
            None, sub_type="other", details={"action": "set_language", "language": language.value}
        )
        lang_name = "العربية" if language.value == "ar" else "English"
        await interaction.response.send_message(f"✅ Language set to **{lang_name}**.", ephemeral=True)

    # ── /ban-user ────────────────────────────────────────────
    @app_commands.command(name="ban-user", description="Ban a user from the bot in this guild (Admin only)")
    @app_commands.describe(user="User to ban")
    async def ban_user(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        banned = guild_settings.get_setting(interaction.guild_id, "banned_users", [])
        if user.id not in banned:
            banned.append(user.id)
            guild_settings.update_setting(interaction.guild_id, "banned_users", banned)
        await interaction.response.send_message(f"✅ {user.mention} banned from bot.", ephemeral=True)

    # ── /view-guilds ─────────────────────────────────────────
    @app_commands.command(name="view-guilds", description="View all guilds the bot is in (Admin only)")
    async def view_guilds(self, interaction: discord.Interaction):
        if interaction.user.id != config.BOT_OWNER_ID:
            return await interaction.response.send_message("❌ Bot owner only.", ephemeral=True)

        guilds = self.bot.guilds
        lines = [f"**{g.name}** (ID: `{g.id}`) — {g.member_count} members" for g in guilds]
        await interaction.response.send_message("\n".join(lines) or "No guilds.", ephemeral=True)

    # ── /force-sync-guild ────────────────────────────────────
    @app_commands.command(name="force-sync-guild", description="Force sync slash commands for this guild (Admin only)")
    async def force_sync_guild(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        try:
            synced = await self.bot.tree.sync(guild=interaction.guild)
            await interaction.response.send_message(f"✅ Synced {len(synced)} commands.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Sync failed: {e}", ephemeral=True)

    # ── /set-command-permission ──────────────────────────────
    @app_commands.command(name="set-command-permission", description="Allow a role to use a specific command (Admin only)")
    @app_commands.describe(command="Command name", role="Role to allow")
    @app_commands.autocomplete(command=command_autocomplete)
    async def set_command_permission(self, interaction: discord.Interaction, command: str, role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild_settings.set_command_permission(interaction.guild_id, command, role.id)
        await interaction.response.send_message(
            f"✅ Role {role.mention} can now use `/{command}`.", ephemeral=True
        )

    # ── /remove-command-permission ───────────────────────────
    @app_commands.command(name="remove-command-permission", description="Remove a role from a command (Admin only)")
    @app_commands.describe(command="Command name", role="Role to remove")
    @app_commands.autocomplete(command=command_autocomplete)
    async def remove_command_permission(self, interaction: discord.Interaction, command: str, role: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild_settings.remove_command_permission(interaction.guild_id, command, role.id)
        await interaction.response.send_message(
            f"✅ Role {role.mention} can no longer use `/{command}`.", ephemeral=True
        )

    # ── /view-command-permissions ────────────────────────────
    @app_commands.command(name="view-command-permissions", description="View all command permission settings (Admin only)")
    async def view_command_permissions(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        all_perms = guild_settings.get_all_command_permissions(interaction.guild_id)
        if not all_perms:
            return await interaction.response.send_message(
                "📋 No command permissions configured.\nAll commands use default Discord permissions.", ephemeral=True
            )

        lines = ["**Command Permissions**\n"]
        for cmd, role_ids in sorted(all_perms.items()):
            roles = []
            for rid in role_ids:
                role_obj = interaction.guild.get_role(rid)
                roles.append(role_obj.mention if role_obj else f"`{rid}`")
            lines.append(f"`/{cmd}` → {', '.join(roles)}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ── /clear-command-permissions ───────────────────────────
    @app_commands.command(name="clear-command-permissions", description="Reset a command to default permissions (Admin only)")
    @app_commands.describe(command="Command name to reset")
    @app_commands.autocomplete(command=command_autocomplete)
    async def clear_command_permissions(self, interaction: discord.Interaction, command: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild_settings.clear_command_permissions(interaction.guild_id, command)
        await interaction.response.send_message(
            f"✅ `/{command}` reset to default permissions.", ephemeral=True
        )

    # ── /automod-add-word ────────────────────────────────────
    @app_commands.command(name="automod-add-word", description="Add a word to automod monitoring (Admin only)")
    @app_commands.describe(word="Word to monitor")
    async def automod_add_word(self, interaction: discord.Interaction, word: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild_settings.add_automod_word(interaction.guild_id, word, interaction.user.id)
        guild_settings.log_action(
            interaction.guild_id, "automod", interaction.user.id, str(interaction.user),
            word, sub_type="word_added", details={"word": word}
        )
        await interaction.response.send_message(f"✅ Word `{word}` added to automod.", ephemeral=True)

    # ── /automod-remove-word ─────────────────────────────────
    @app_commands.command(name="automod-remove-word", description="Remove a word from automod monitoring (Admin only)")
    @app_commands.describe(word="Word to remove")
    async def automod_remove_word(self, interaction: discord.Interaction, word: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        removed = guild_settings.remove_automod_word(interaction.guild_id, word)
        if removed:
            guild_settings.log_action(
                interaction.guild_id, "automod", interaction.user.id, str(interaction.user),
                word, sub_type="word_removed", details={"word": word}
            )
            await interaction.response.send_message(f"✅ Word `{word}` removed from automod.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Word `{word}` not found.", ephemeral=True)

    # ── /automod-list-words ──────────────────────────────────
    @app_commands.command(name="automod-list-words", description="List all custom automod words (Admin only)")
    async def automod_list_words(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        words = guild_settings.get_automod_words(interaction.guild_id)
        if not words:
            return await interaction.response.send_message(
                "📋 No custom automod words configured.\nDefault words are still active.", ephemeral=True
            )

        lines = [f"`{w}`" for w in words]
        embed = discord.Embed(
            title="🔍 Automod Custom Words",
            description="\n".join(lines),
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"Total: {len(words)} custom words")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /automod-clear-words ─────────────────────────────────
    @app_commands.command(name="automod-clear-words", description="Clear all custom automod words (Admin only)")
    async def automod_clear_words(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

        guild_settings.clear_automod_words(interaction.guild_id)
        guild_settings.log_action(
            interaction.guild_id, "automod", interaction.user.id, str(interaction.user),
            None, sub_type="words_cleared"
        )
        await interaction.response.send_message("✅ All custom automod words cleared.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Admin(bot))
