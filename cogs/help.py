import discord
from discord.ext import commands
from discord import app_commands
import bot_i18n
import guild_settings


# ── Category definitions ────────────────────────────────────

CATEGORY_ORDER = ["general", "server", "moderation", "shop", "custom", "whitelist", "tribelog", "leaderboard", "automod", "admin", "other"]

CATEGORY_LABELS = {
    "general": {"ar": "عامة", "en": "General"},
    "server": {"ar": "السيرفر", "en": "Server"},
    "moderation": {"ar": "الإشراف", "en": "Moderation"},
    "shop": {"ar": "المتجر", "en": "Shop"},
    "custom": {"ar": "الأوامر المخصصة", "en": "Custom Commands"},
    "whitelist": {"ar": "الوايت ليست", "en": "Whitelist"},
    "tribelog": {"ar": "سجلات القبائل", "en": "Tribe Log"},
    "leaderboard": {"ar": "لوحة المتصدرين", "en": "Leaderboard"},
    "automod": {"ar": "الأتمود", "en": "Auto-Mod"},
    "admin": {"ar": "الإدارة", "en": "Admin"},
    "other": {"ar": "أخرى", "en": "Other"},
}

COMMAND_CATEGORIES = {
    "shop": ["add-shop-dino", "remove-shop-dino", "list-dinos", "buy-dino", "balance", "add-points", "remove-points", "set-min-level", "pending-purchases", "spawn-pending", "cancel-pending", "set-shop-channels"],
    "custom": ["custom", "custom-list", "custom-add", "custom-remove", "ark-command", "setup-forum-logs", "setup-shop-forum"],
    "whitelist": ["whitelist", "linkpsn", "unlinkpsn", "wl-status", "wl-list", "set-wl-path", "set-restart-time"],
    "moderation": ["ban", "kick", "mute", "unmute", "warn", "warnings", "clear-warnings", "banplayer", "unbanplayer", "wipe-player"],
    "tribelog": ["tribe-log", "enable-tribe-log", "disable-tribe-log", "set-tribe-log-channel", "set-tribe-log-config", "set-tribe-log-source"],
    "leaderboard": ["leaderboard", "setup-leaderboard", "leaderboard-preview", "set-tribe-owner", "add-tribe-points", "remove-tribe-points"],
    "admin": ["set-nitrado-token", "set-log-channel", "set-license", "set-language", "ban-user", "view-guilds", "force-sync-guild"],
    "automod": ["automod-toggle", "automod-set-log-channel", "automod-set-log-path", "automod-add-word", "automod-remove-word", "automod-list-words", "automod-clear-words"],
    "server": ["backup-create", "backup-list", "backup-rollback", "backup-download"],
}


# ── Help View ───────────────────────────────────────────────

class HelpView(discord.ui.View):
    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.guild_id = guild_id
        self.lang = bot_i18n.t(guild_id, "help_title") and guild_settings.get_setting(guild_id, "bot_language", "ar")
        self.current_category = CATEGORY_ORDER[0]
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for cat in CATEGORY_ORDER:
            label = CATEGORY_LABELS.get(cat, {}).get(self.lang, cat.title())
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, custom_id=f"cat_{cat}")
            btn.callback = self._make_callback(cat)
            self.add_item(btn)

    def _make_callback(self, category):
        async def callback(interaction: discord.Interaction):
            self.current_category = category
            embed = self._build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        return callback

    def _build_embed(self):
        lang = self.lang
        cat_label = CATEGORY_LABELS.get(self.current_category, {}).get(lang, self.current_category.title())
        title = f"📖 {cat_label}"

        commands_in_cat = COMMAND_CATEGORIES.get(self.current_category, [])
        lines = []
        for cmd_name in commands_in_cat:
            cmd = self.bot.tree.get_command(cmd_name)
            if cmd:
                desc = cmd.description or "No description"
                lines.append(f"`/{cmd_name}` — {desc}")
            else:
                lines.append(f"`/{cmd_name}`")

        if not lines:
            desc = "لا توجد أوامر في هذا التصنيف" if lang == "ar" else "No commands in this category."
        else:
            desc = "\n".join(lines)

        return discord.Embed(title=title, description=desc, color=discord.Color.blurple())


# ── Cog ─────────────────────────────────────────────────────

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands")
    async def help_command(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        lang = guild_settings.get_setting(guild_id, "bot_language", "ar")
        view = HelpView(self.bot, guild_id)
        embed = view._build_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="set-help-text", description="Override the description of a slash command (Admin only)")
    @app_commands.describe(command="Command name (e.g. buy-dino)", description="New description text")
    async def set_help_text(self, interaction: discord.Interaction, command: str, description: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        overrides = guild_settings.get_setting(interaction.guild_id, "help_overrides", {})
        overrides[command] = description
        guild_settings.update_setting(interaction.guild_id, "help_overrides", overrides)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "help_text_updated", key=command), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))
