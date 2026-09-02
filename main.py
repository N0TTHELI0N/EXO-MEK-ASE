import asyncio
import logging
import os
import sys

import discord
from discord.ext import commands

import config
import guild_settings
import shop_db
import bot_i18n
import command_overrides


logger = logging.getLogger("main")
logger.setLevel(logging.INFO)

if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s | %(name)s: %(message)s"))
    logger.addHandler(_handler)


# ── Bot Setup ───────────────────────────────────────────────

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")


# ── Global Command Permission Check ────────────────────────

@bot.tree.interaction_check
async def global_permission_check(interaction: discord.Interaction) -> bool:
    """Runs before every slash command. Checks command_permissions table."""
    if interaction.type != discord.InteractionType.application_command:
        return True

    command_name = interaction.data.get("name", "") if interaction.data else ""
    member = interaction.user

    # DMs — skip permission check
    if not interaction.guild:
        return True

    # Check if user is banned from bot
    banned_users = guild_settings.get_setting(interaction.guild_id, "banned_users", [])
    if member.id in banned_users:
        await interaction.response.send_message(
            "❌ You are banned from using this bot.",
            ephemeral=True,
        )
        return False

    # Admins always pass
    if member.guild_permissions.administrator:
        return True

    # Admin can globally disable a command for everyone else
    if guild_settings.is_command_disabled(interaction.guild_id, command_name):
        await interaction.response.send_message(
            "❌ This command is disabled.",
            ephemeral=True,
        )
        return False

    allowed_roles = guild_settings.get_command_permissions(interaction.guild_id, command_name)
    if not allowed_roles:
        return True  # no restriction — anyone can use

    member_role_ids = {r.id for r in member.roles}
    if member_role_ids & set(allowed_roles):
        return True

    await interaction.response.send_message(
        "❌ You don't have permission to use this command.",
        ephemeral=True,
    )
    return False


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Sync error: {e}")


@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(bot_i18n.t(ctx.guild.id, "no_permission"))
        return
    if isinstance(error, commands.BotMissingPermissions):
        await ctx.send(bot_i18n.t(ctx.guild.id, "rcon_failed"))
        return
    raise error


# ── Extensions ──────────────────────────────────────────────

EXTENSIONS = [
    "cogs.admin",
    "cogs.shop",
    "cogs.custom_commands",
    "cogs.whitelist",
    "cogs.tribelog",
    "cogs.leaderboard",
    "cogs.automod",
    "cogs.server_backup",
    "cogs.moderation",
    "cogs.chat_bridge",
    "cogs.topservers",
    "cogs.help",
]


# ── Main ────────────────────────────────────────────────────

def main():
    command_overrides.install()
    guild_settings.init_db()
    shop_db.init_shop_db()
    shop_db.init_leaderboard_db()

    logger.info("Database initialized. Starting bot...")

    bot.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
