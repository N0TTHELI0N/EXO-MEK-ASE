import discord
from discord.ext import commands
from discord import app_commands
import bot_i18n
import guild_settings
import commands_manifest


# ── Category definitions ────────────────────────────────────
# Derived from commands_manifest.py (the canonical command list)
# so the menu always matches what is actually registered.

CATEGORY_ORDER = [c for c in commands_manifest.CATEGORY_ORDER
                  if any(cmd[1] == c for cmd in commands_manifest.COMMANDS)]

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
    "chat": {"ar": "شات اللعبة", "en": "In-Game Chat"},
    "admin": {"ar": "الإدارة", "en": "Admin"},
    "other": {"ar": "أخرى", "en": "Other"},
}


def _build_command_categories():
    cats = {cat: [] for cat in CATEGORY_ORDER}
    for name, cat, _desc in commands_manifest.COMMANDS:
        if cat in cats:
            cats[cat].append(name)
    return cats


COMMAND_CATEGORIES = _build_command_categories()


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
                default = cmd.description or "No description"
                desc = guild_settings.get_command_description(self.guild_id, cmd_name, default)
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

        guild_settings.set_command_description(interaction.guild_id, command, description)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "help_text_updated", key=command), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))
