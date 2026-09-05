import discord
from discord.ext import commands
from discord import app_commands
import bot_i18n
import guild_settings
import commands_manifest
import config


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


# ── Help View (dropdown) ────────────────────────────────────

class HelpView(discord.ui.View):
    def __init__(self, bot, guild_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.guild_id = guild_id
        self.lang = guild_settings.get_setting(guild_id, "bot_language", "ar")

        select = discord.ui.Select(
            placeholder=bot_i18n.t(guild_id, "help_placeholder"),
            min_values=1,
            max_values=1,
        )
        options = []
        options.append(discord.SelectOption(
            label=bot_i18n.t(guild_id, "help_about_label"),
            description=bot_i18n.t(guild_id, "help_about_desc"),
            value="about",
        ))
        options.append(discord.SelectOption(
            label=bot_i18n.t(guild_id, "help_setup_label"),
            description=bot_i18n.t(guild_id, "help_setup_desc"),
            value="setup",
        ))
        for cat in CATEGORY_ORDER:
            label = CATEGORY_LABELS.get(cat, {}).get(self.lang, cat.title())
            options.append(discord.SelectOption(label=label, value=f"cat_{cat}"))
        select.options = options
        select.callback = self._select_callback
        self.add_item(select)

    async def _select_callback(self, interaction: discord.Interaction):
        value = interaction.data.get("values", ["about"])[0]
        if value.startswith("cat_"):
            self.current_category = value[4:]
            embed = self._build_category_embed()
        elif value == "setup":
            self.current_category = None
            embed = self._build_setup_embed()
        else:
            self.current_category = None
            embed = self._build_about_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    # ── embed builders ───────────────────────────────────────
    def _build_about_embed(self):
        guild_id = self.guild_id
        lang = self.lang
        lang_name = "العربية" if lang == "ar" else "English"
        body = bot_i18n.t(guild_id, "help_about_body", lang_name=lang_name)

        embed = discord.Embed(
            title=bot_i18n.t(guild_id, "help_welcome_title"),
            description=body,
            color=discord.Color.red(),
        )

        links = []
        if config.DASHBOARD_BASE_URL:
            links.append(f"• [🌐 {bot_i18n.t(guild_id, 'help_about_dashboard')}]({config.DASHBOARD_BASE_URL}) — {bot_i18n.t(guild_id, 'help_about_dashboard_url')}")
        if config.BOT_INVITE_URL:
            links.append(f"• [🤖 {bot_i18n.t(guild_id, 'help_about_invite')}]({config.BOT_INVITE_URL}) — {bot_i18n.t(guild_id, 'help_about_invite_url')}")
        if links:
            embed.add_field(
                name=bot_i18n.t(guild_id, "help_about_field_links"),
                value="\n".join(links),
                inline=False,
            )
            embed.add_field(
                name=bot_i18n.t(guild_id, "help_about_field_how"),
                value=bot_i18n.t(guild_id, "help_setup_body", license_hint=bot_i18n.t(guild_id, "help_license_inactive")),
                inline=False,
            )
        embed.set_footer(text=bot_i18n.t(guild_id, "help_footer_hint"))
        return embed

    def _build_setup_embed(self):
        guild_id = self.guild_id
        if guild_settings.is_license_valid(guild_id):
            license_hint = bot_i18n.t(guild_id, "help_license_active")
        else:
            license_hint = bot_i18n.t(guild_id, "help_license_inactive")

        embed = discord.Embed(
            title=bot_i18n.t(guild_id, "help_setup_label"),
            description=bot_i18n.t(guild_id, "help_setup_body", license_hint=license_hint),
            color=discord.Color.red(),
        )
        embed.set_footer(text=bot_i18n.t(guild_id, "help_footer_hint"))
        return embed

    def _build_category_embed(self):
        lang = self.lang
        cat = self.current_category
        cat_label = CATEGORY_LABELS.get(cat, {}).get(lang, cat.title())
        title = bot_i18n.t(self.guild_id, "help_category_header", label=cat_label)

        commands_in_cat = COMMAND_CATEGORIES.get(cat, [])
        lines = []
        for cmd_name in commands_in_cat:
            cmd = self.bot.tree.get_command(cmd_name)
            if cmd:
                default = cmd.description or bot_i18n.t(self.guild_id, "help_no_description")
                desc = guild_settings.get_command_description(self.guild_id, cmd_name, default)
                lines.append(f"`/{cmd_name}` — {desc}")
            else:
                lines.append(f"`/{cmd_name}`")

        if not lines:
            desc = bot_i18n.t(self.guild_id, "help_category_empty")
        else:
            desc = "\n".join(lines)

        embed = discord.Embed(title=title, description=desc, color=discord.Color.red())
        embed.set_footer(text=bot_i18n.t(self.guild_id, "help_footer_hint"))
        return embed


# ── Cog ─────────────────────────────────────────────────────

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all available commands")
    async def help_command(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        view = HelpView(self.bot, guild_id)
        embed = view._build_about_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))