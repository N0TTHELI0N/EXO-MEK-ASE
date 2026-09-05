import threading
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def run_bot():
    import guild_settings
    import shop_db
    import config
    import command_overrides

    command_overrides.install()

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
        "cogs.custom_commands",
        "cogs.whitelist",
        "cogs.tribelog",
        "cogs.leaderboard",
        "cogs.automod",
        "cogs.server_backup",
        "cogs.moderation",
        "cogs.chat_bridge",

        "cogs.help",
        "cogs.playtime",
        "cogs.player_ops",
        "cogs.anti_abuse",
    ]

    # Discord allows max 100 global slash commands. These cogs hold the
    # commands that spill over the limit, so they are registered per-guild
    # instead (guild scope has its own separate limit of 100).
    GUILD_SCOPED_EXTENSIONS = [
        ("cogs.cluster", "Cluster"),
        ("cogs.staff", "Staff"),
    ]

    async def _register_guild_scoped(bot):
        """Build commands for cogs that exceed the global slash limit and
        register them per-guild (the tree's guild scope has its own limit)."""
        scoped = []
        for mod_name, cls_name in GUILD_SCOPED_EXTENSIONS:
            try:
                mod = __import__(mod_name, fromlist=[cls_name])
                cog = getattr(mod, cls_name)(bot)
                scoped.extend(cog.get_app_commands())
            except Exception as e:
                print(f"[Bot] ERROR building guild-scoped {mod_name}: {e}", flush=True)
        return scoped

    @bot.event
    async def on_ready():
        print(f"[Bot] Logged in as {bot.user} ({bot.user.id})")
        print(f"[Bot] Guilds: {len(bot.guilds)}")
        # Load cogs (async in discord.py 2.4) before syncing so commands are registered
        for ext in EXTENSIONS:
            try:
                await bot.load_extension(ext)
                print(f"[Bot] Loaded extension {ext}", flush=True)
            except Exception as e:
                print(f"[Bot] ERROR loading {ext}: {e}", flush=True)
        try:
            synced = await bot.tree.sync()
            print(f"[Bot] Synced {len(synced)} slash commands globally", flush=True)
        except Exception as e:
            print(f"[Bot] Global sync error: {e}", flush=True)
        guild_scoped = await _register_guild_scoped(bot)
        print(f"[Bot] Guild-scoped commands ready: {len(guild_scoped)}", flush=True)
        # Commands over the global limit live in guild scope. Syncing a guild
        # replaces its whole slash-command list server-side, which also drops
        # any stale per-guild copies left from earlier testing.
        for guild in bot.guilds:
            for cmd in guild_scoped:
                try:
                    bot.tree.add_command(cmd, guild=guild, override=True)
                except Exception as e:
                    print(f"[Bot] Guild-scoped add error {cmd.name} in {guild.name}: {e}", flush=True)
            try:
                synced = await bot.tree.sync(guild=guild)
                print(f"[Bot] Synced {len(synced)} guild commands for {guild.name}", flush=True)
            except Exception as e:
                print(f"[Bot] Guild cleanup error for {guild.name}: {e}", flush=True)

    @bot.event
    async def on_guild_join(guild):
        print(f"[Bot] Joined guild {guild.name}", flush=True)
        try:
            for mod_name, cls_name in GUILD_SCOPED_EXTENSIONS:
                mod = __import__(mod_name, fromlist=[cls_name])
                cog = getattr(mod, cls_name)(bot)
                for cmd in cog.get_app_commands():
                    bot.tree.add_command(cmd, guild=guild, override=True)
            synced = await bot.tree.sync(guild=guild)
            print(f"[Bot] Synced {len(synced)} guild commands for {guild.name}", flush=True)
        except Exception as e:
            print(f"[Bot] on_guild_join sync error for {guild.name}: {e}", flush=True)

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
                bot_i18n.t(interaction.guild_id, "user_banned_from_bot"), ephemeral=True
            )
            return False
        # Owner always has full access (bypass license gate)
        if member.id == config.BOT_OWNER_ID:
            return True
        # License gate: every feature requires a valid license, except the license
        # management commands themselves so a server can activate its key.
        if command_name not in ("set-license",):
            if not guild_settings.is_license_valid(interaction.guild_id):
                await interaction.response.send_message(
                    bot_i18n.t(interaction.guild_id, "license_gate_required"),
                    ephemeral=True,
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
            bot_i18n.t(interaction.guild_id, "custom_permission_denied"), ephemeral=True
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
