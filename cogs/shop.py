import discord
from discord.ext import commands
from discord import app_commands
import bot_i18n
import guild_settings
import shop_db
import config
from security import sanitize_rcon_name


GLOBAL_MIN_LEVEL = 11


# ── Cog ─────────────────────────────────────────────────────

class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _send_rcon(self, guild_id: int, command: str) -> str | None:
        host = guild_settings.get_setting(guild_id, "rcon_host") or config.RCON_HOST
        port = guild_settings.get_setting(guild_id, "rcon_port") or config.RCON_PORT
        password = guild_settings.get_setting(guild_id, "rcon_password") or config.RCON_PASSWORD

        if not host:
            return None

        try:
            from rcon import Client
            with Client(host, port=port, passwd=password) as client:
                return client.cmd(command)
        except Exception as e:
            print(f"[Shop] RCON error: {type(e).__name__}")
            return None

    # ── /add-shop-dino ───────────────────────────────────────
    @app_commands.command(name="add-shop-dino", description="Add a dinosaur to the shop (Admin only)")
    @app_commands.describe(name="Display name", blueprint="Blueprint path", min_level="Min level", max_level="Max level", price="Price in points", category="Category")
    async def add_shop_dino(self, interaction: discord.Interaction, name: str, blueprint: str, min_level: int = 1, max_level: int = 150, price: int = 0, category: str = "General"):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        shop_db.add_shop_dino(interaction.guild_id, name, blueprint, min_level, max_level, price, category)
        guild_settings.log_action(interaction.guild_id, "admin_command", interaction.user.id, str(interaction.user), name, sub_type="dino_spawn", details={"blueprint": blueprint, "price": price})
        await interaction.response.send_message(f"✅ **{name}** added to the shop.")

    # ── /remove-shop-dino ────────────────────────────────────
    @app_commands.command(name="remove-shop-dino", description="Remove a dinosaur from the shop (Admin only)")
    @app_commands.describe(name="Dino name to remove")
    async def remove_shop_dino(self, interaction: discord.Interaction, name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        shop_db.remove_shop_dino(interaction.guild_id, name)
        guild_settings.log_action(interaction.guild_id, "admin_command", interaction.user.id, str(interaction.user), name, sub_type="other")
        await interaction.response.send_message(f"✅ **{name}** removed from the shop.")

    # ── /list-dinos ──────────────────────────────────────────
    @app_commands.command(name="list-dinos", description="List all dinosaurs in the shop")
    async def list_dinos(self, interaction: discord.Interaction):
        dinos = shop_db.get_shop_dinos(interaction.guild_id)
        if not dinos:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "shop_empty"), ephemeral=True)

        lines = []
        for d in dinos:
            lines.append(f"**{d[0]}** — Lvl {d[2]}-{d[3]} — {d[4]} pts")

        embed = discord.Embed(title="🦕 Shop Dinosaurs", description="\n".join(lines), color=discord.Color.green())
        await interaction.response.send_message(embed=embed)

    # ── /buy-dino ────────────────────────────────────────────
    @app_commands.command(name="buy-dino", description="Buy a dinosaur from the shop")
    @app_commands.describe(name="Dino name", level="Level to spawn")
    async def buy_dino(self, interaction: discord.Interaction, name: str, level: int):
        dinos = shop_db.get_shop_dinos(interaction.guild_id)
        match = next((d for d in dinos if d[0].lower() == name.lower()), None)
        if not match:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "dino_not_available"), ephemeral=True)

        min_lvl, max_lvl, price = match[2], match[3], match[4]
        if level < GLOBAL_MIN_LEVEL or level > max_lvl:
            return await interaction.response.send_message(
                bot_i18n.t(interaction.guild_id, "level_not_allowed", min_level=GLOBAL_MIN_LEVEL, max_level=max_lvl),
                ephemeral=True,
            )

        # Check points
        member_name = interaction.user.display_name
        current = shop_db.get_points(interaction.guild_id, member_name)
        if current < price:
            return await interaction.response.send_message(
                bot_i18n.t(interaction.guild_id, "insufficient_points", price=price, current=current),
                ephemeral=True,
            )

        # Deduct points
        shop_db.remove_points(interaction.guild_id, member_name, price)

        # Spawn via RCON
        bp = match[1]
        safe_name = sanitize_rcon_name(interaction.user.display_name)
        cmd = f'GiveItemToPlayer "{safe_name}" "{bp}" {level} 0 false'
        result = await self._send_rcon(interaction.guild_id, cmd)
        if result is None:
            # Refund on failure
            shop_db.add_points(interaction.guild_id, member_name, price)
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "purchase_rcon_failed"), ephemeral=True)

        new_balance = shop_db.get_points(interaction.guild_id, member_name)
        guild_settings.log_action(interaction.guild_id, "leaderboard", interaction.user.id, str(interaction.user), name, sub_type="purchase", details={"level": level, "price": price})
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "purchase_success", dino=name, level=level)
            + f"\n{bot_i18n.t(interaction.guild_id, 'balance_msg', points=new_balance)}"
        )

    # ── /balance ─────────────────────────────────────────────
    @app_commands.command(name="balance", description="Check your current point balance")
    async def balance(self, interaction: discord.Interaction):
        points = shop_db.get_points(interaction.guild_id, interaction.user.display_name)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "balance_msg", points=points),
            ephemeral=True,
        )

    # ── /add-points ──────────────────────────────────────────
    @app_commands.command(name="add-points", description="Add points to a member (Admin only)")
    @app_commands.describe(member="Member", amount="Points to add")
    async def add_points(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        shop_db.add_points(interaction.guild_id, member.display_name, amount)
        guild_settings.log_action(interaction.guild_id, "leaderboard", interaction.user.id, str(interaction.user), member.display_name, sub_type="points_added", details={"amount": amount})
        balance = shop_db.get_points(interaction.guild_id, member.display_name)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "points_added", amount=amount, balance=balance)
        )

    # ── /remove-points ───────────────────────────────────────
    @app_commands.command(name="remove-points", description="Remove points from a member (Admin only)")
    @app_commands.describe(member="Member", amount="Points to remove")
    async def remove_points(self, interaction: discord.Interaction, member: discord.Member, amount: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        shop_db.remove_points(interaction.guild_id, member.display_name, amount)
        guild_settings.log_action(interaction.guild_id, "leaderboard", interaction.user.id, str(interaction.user), member.display_name, sub_type="points_removed", details={"amount": amount})
        balance = shop_db.get_points(interaction.guild_id, member.display_name)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "points_removed", amount=amount, balance=balance)
        )

    # ── /set-min-level ───────────────────────────────────────
    @app_commands.command(name="set-min-level", description="Set the minimum spawn level (Admin only)")
    @app_commands.describe(level="Minimum level (global)")
    async def set_min_level(self, interaction: discord.Interaction, level: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        global GLOBAL_MIN_LEVEL
        GLOBAL_MIN_LEVEL = level
        await interaction.response.send_message(f"✅ Global minimum level set to **{level}**.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Shop(bot))
