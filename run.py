import threading
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def run_bot():
    import guild_settings
    import shop_db
    import config

    guild_settings.init_db()
    shop_db.init_shop_db()
    shop_db.init_leaderboard_db()

    import discord
    from discord.ext import commands
    import bot_i18n

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    EXTENSIONS = [
        "cogs.admin",
        "cogs.shop",
        "cogs.whitelist",
        "cogs.tribelog",
        "cogs.leaderboard",
        "cogs.automod",
        "cogs.server_backup",
        "cogs.moderation",
        "cogs.topservers",
        "cogs.help",
    ]

    @bot.event
    async def on_ready():
        print(f"[Bot] Logged in as {bot.user} ({bot.user.id})")
        print(f"[Bot] Guilds: {len(bot.guilds)}")
        try:
            synced = await bot.tree.sync()
            print(f"[Bot] Synced {len(synced)} slash commands globally", flush=True)
        except Exception as e:
            print(f"[Bot] Global sync error: {e}", flush=True)
        # Guild-scoped sync makes commands appear immediately in each server
        for guild in bot.guilds:
            try:
                g_synced = await bot.tree.sync(guild=guild)
                print(f"[Bot] Synced {len(g_synced)} commands for {guild.name} ({guild.id})", flush=True)
            except Exception as e:
                print(f"[Bot] Guild sync error for {guild.name}: {e}", flush=True)

    @bot.tree.interaction_check
    async def global_permission_check(interaction: discord.Interaction) -> bool:
        if interaction.type != discord.InteractionType.application_command:
            return True
        command_name = interaction.data.get("name", "") if interaction.data else ""
        member = interaction.user
        if not interaction.guild:
            return True
        banned_users = guild_settings.get_setting(interaction.guild_id, "banned_users", [])
        if member.id in banned_users:
            await interaction.response.send_message(
                "❌ You are banned from using this bot.", ephemeral=True
            )
            return False
        if member.guild_permissions.administrator:
            return True
        allowed_roles = guild_settings.get_command_permissions(
            interaction.guild_id, command_name
        )
        if not allowed_roles:
            return True
        member_role_ids = {r.id for r in member.roles}
        if member_role_ids & set(allowed_roles):
            return True
        await interaction.response.send_message(
            "❌ You don't have permission to use this command.", ephemeral=True
        )
        return False

    @bot.event
    async def on_command_error(ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(bot_i18n.t(ctx.guild.id, "no_permission"))
            return
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(bot_i18n.t(ctx.guild.id, "rcon_failed"))
            return
        raise error

    for ext in EXTENSIONS:
        bot.load_extension(ext)

    if not config.DISCORD_TOKEN:
        print("[Bot] ERROR: DISCORD_TOKEN is not set. Bot cannot start.", flush=True)
        return

    try:
        bot.run(config.DISCORD_TOKEN)
    except Exception as e:
        print(f"[Bot] ERROR: bot crashed: {type(e).__name__}: {e}", flush=True)
    except SystemExit as e:
        print(f"[Bot] Bot exited: {e}", flush=True)


def run_dashboard():
    from dashboard.app import app, guild_settings as gs
    gs.init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    def _bot_worker():
        try:
            run_bot()
        except Exception as e:
            import traceback
            print(f"[Bot] FATAL error in bot thread:\n{traceback.format_exc()}", flush=True)

    bot_thread = threading.Thread(target=_bot_worker, daemon=True)
    bot_thread.start()
    run_dashboard()
