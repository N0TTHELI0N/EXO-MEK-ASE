import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
import bot_i18n
import guild_settings
import shop_db
import nitrado


GLOBAL_MIN_LEVEL = 11


# ── Delivery view (pending channel buttons) ─────────────────

class PendingPurchaseView(discord.ui.View):
    def __init__(self, cog, guild_id: int, purchase_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.purchase_id = purchase_id

    @discord.ui.button(label="Deliver", style=discord.ButtonStyle.success)
    async def deliver_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(self.guild_id, "admin_only"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.cog.deliver_purchase(interaction, self.purchase_id, from_button=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(self.guild_id, "admin_only"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.cog.cancel_purchase(interaction, self.purchase_id, from_button=True)


async def send_or_update(interaction: discord.Interaction, content: str, ephemeral: bool = False):
    """Send a confirmation, handling both button interactions and slash commands."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        elif interaction.message is not None:
            await interaction.response.send_message(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)
    except Exception:
        try:
            await interaction.response.send_message(content, ephemeral=ephemeral)
        except Exception:
            pass


# ── Cog ─────────────────────────────────────────────────────

class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.post_pending.start()

    def cog_unload(self):
        self.post_pending.cancel()

    # ── Background task: post new pending purchases to channel ──
    @tasks.loop(seconds=30)
    async def post_pending(self):
        for guild in self.bot.guilds:
            pending_channel_id = guild_settings.get_setting(guild.id, "shop_pending_channel", 0)
            if not pending_channel_id:
                continue
            ch = guild.get_channel(pending_channel_id)
            if not ch:
                continue
            # Post new pending purchases that don't have a message yet.
            for p in shop_db.get_pending_purchases(guild.id):
                if p["message_id"]:
                    continue
                view = PendingPurchaseView(self, guild.id, p["id"])
                embed = self._pending_embed(guild.id, p)
                try:
                    msg = await ch.send(embed=embed, view=view)
                    shop_db.set_purchase_message(guild.id, p["id"], msg.id)
                except Exception:
                    continue
            # Clean up Discord messages for purchases resolved elsewhere (e.g. dashboard).
            for p in shop_db.get_resolved_purchases_with_message(guild.id):
                try:
                    msg = await ch.fetch_message(p["message_id"])
                    embed = msg.embeds[0]
                    embed.color = discord.Color.green() if p["status"] == "done" else discord.Color.red()
                    await msg.edit(embed=embed, view=None)
                except Exception:
                    continue

    @post_pending.before_loop
    async def before_post_pending(self):
        await self.bot.wait_until_ready()

    # ── helpers ─────────────────────────────────────────────
    def _pending_embed(self, guild_id: int, p: dict) -> discord.Embed:
        mine = bot_i18n.t(guild_id, "pending_embed")
        return discord.Embed(
            title=f"#{p['id']} · {p['dino_name']} Lvl {p['level']}",
            description=mine.format(
                buyer=p["user_name"],
                dino=p["dino_name"],
                level=p["level"],
                price=p["price"],
                blueprint=p["blueprint"],
            ),
            color=discord.Color.orange(),
        ).set_footer(text=f"Purchase #{p['id']}")

    def _done_channel(self, guild) -> discord.TextChannel | None:
        ch_id = guild_settings.get_setting(guild.id, "shop_done_channel", 0)
        return guild.get_channel(ch_id) if ch_id else None

    def _class_name(self, blueprint: str) -> str:
        cn = blueprint
        if "Blueprint'" in cn:
            cn = cn.split('.')[-1].rstrip("'").strip()
        if not cn.endswith("_C"):
            cn += "_C"
        return cn

    async def deliver_purchase(self, interaction: discord.Interaction, purchase_id: int, from_button: bool = False):
        guild_id = interaction.guild_id
        purchase = shop_db.get_purchase_by_id(guild_id, purchase_id)
        if not purchase:
            return await send_or_update(interaction, bot_i18n.t(guild_id, "pending_not_found"), ephemeral=True)

        class_name = self._class_name(purchase["blueprint"])
        cmd = f'GMSummon "{class_name}" {purchase["level"]}'
        try:
            result = await asyncio.to_thread(nitrado.send_rcon, guild_id, cmd)
        except Exception:
            result = None
        if result is None:
            return await send_or_update(interaction, bot_i18n.t(guild_id, "purchase_spawn_failed", purchase_id=purchase_id), ephemeral=True)

        shop_db.mark_purchase_done(guild_id, purchase_id, interaction.user.id)
        guild_settings.log_action(guild_id, "leaderboard", interaction.user.id, str(interaction.user), purchase["dino_name"], sub_type="purchase_delivered", details={"level": purchase["level"], "purchase_id": purchase_id})

        msg_text = bot_i18n.t(guild_id, "purchase_delivered", dino=purchase["dino_name"], level=purchase["level"], purchase_id=purchase_id)
        await self._resolve_pending_message(guild_id, purchase, ok=True)
        await send_or_update(interaction, msg_text, ephemeral=from_button)
        await self._log_done(guild_id, purchase, interaction.user)

    async def cancel_purchase(self, interaction: discord.Interaction, purchase_id: int, from_button: bool = False):
        guild_id = interaction.guild_id
        purchase = shop_db.get_purchase_by_id(guild_id, purchase_id)
        if not purchase:
            return await send_or_update(interaction, bot_i18n.t(guild_id, "pending_not_found"), ephemeral=True)

        if shop_db.cancel_purchase(guild_id, purchase_id):
            shop_db.add_points(guild_id, purchase["user_name"], purchase["price"])
        guild_settings.log_action(guild_id, "leaderboard", interaction.user.id, str(interaction.user), purchase["dino_name"], sub_type="purchase_cancelled", details={"purchase_id": purchase_id, "refund": purchase["price"]})

        msg_text = bot_i18n.t(guild_id, "purchase_cancelled", purchase_id=purchase_id, amount=purchase["price"])
        await self._resolve_pending_message(guild_id, purchase, ok=False)
        await send_or_update(interaction, msg_text, ephemeral=from_button)

    async def _resolve_pending_message(self, guild_id: int, purchase: dict, ok: bool):
        ch_id = guild_settings.get_setting(guild_id, "shop_pending_channel", 0)
        if not ch_id or not purchase.get("message_id"):
            return
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        ch = guild.get_channel(ch_id)
        if not ch:
            return
        try:
            msg = await ch.fetch_message(purchase["message_id"])
            embed = msg.embeds[0]
            embed.color = discord.Color.green() if ok else discord.Color.red()
            await msg.edit(embed=embed, view=None)
        except Exception:
            pass

    async def _log_done(self, guild_id: int, purchase: dict, actor):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        ch = self._done_channel(guild)
        if not ch:
            return
        embed = discord.Embed(
            title=f"✅ {purchase['dino_name']} Lvl {purchase['level']}",
            description=bot_i18n.t(guild_id, "done_embed").format(
                buyer=purchase["user_name"],
                dino=purchase["dino_name"],
                level=purchase["level"],
                price=purchase["price"],
                delivered_by=actor.mention if hasattr(actor, "mention") else str(actor),
            ),
            color=discord.Color.green(),
        ).set_footer(text=f"Purchase #{purchase['id']}")
        try:
            await ch.send(embed=embed)
        except Exception:
            pass

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

        member_name = interaction.user.display_name
        current = shop_db.get_points(interaction.guild_id, member_name)
        if current < price:
            return await interaction.response.send_message(
                bot_i18n.t(interaction.guild_id, "insufficient_points", price=price, current=current),
                ephemeral=True,
            )

        # Deduct points, then queue the purchase for an admin to spawn in-game.
        shop_db.remove_points(interaction.guild_id, member_name, price)
        purchase_id = shop_db.create_purchase(
            interaction.guild_id,
            interaction.user.id,
            member_name,
            match[0],
            match[1],
            level,
            price,
        )

        guild_settings.log_action(interaction.guild_id, "leaderboard", interaction.user.id, str(interaction.user), name, sub_type="purchase_pending", details={"level": level, "price": price, "purchase_id": purchase_id})
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "purchase_queued", dino=match[0], level=level)
            + f"\n{bot_i18n.t(interaction.guild_id, 'balance_msg', points=shop_db.get_points(interaction.guild_id, member_name))}"
        )

    # ── /pending-purchases ───────────────────────────────────
    @app_commands.command(name="pending-purchases", description="List all pending purchases (Admin only)")
    async def pending_purchases(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        pending = shop_db.get_pending_purchases(interaction.guild_id)
        if not pending:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "pending_empty"), ephemeral=True)

        lines = []
        for p in pending:
            lines.append(
                f"**#{p['id']}** · {p['user_name']} · {p['dino_name']} Lvl {p['level']} · {p['price']} pts\n"
                f"`{p['blueprint']}`"
            )

        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "pending_title"), description="\n".join(lines), color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /set-shop-channels ───────────────────────────────────
    @app_commands.command(name="set-shop-channels", description="Set the pending and done delivery channels (Admin only)")
    @app_commands.describe(pending_channel="Channel for pending deliveries", done_channel="Channel for delivered purchases")
    async def set_shop_channels(self, interaction: discord.Interaction, pending_channel: discord.TextChannel, done_channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, "shop_pending_channel", pending_channel.id)
        guild_settings.update_setting(interaction.guild_id, "shop_done_channel", done_channel.id)
        await interaction.response.send_message(
            f"✅ Pending deliveries → {pending_channel.mention}\n✅ Delivered purchases → {done_channel.mention}",
            ephemeral=True,
        )

    # ── /spawn-pending ───────────────────────────────────────
    @app_commands.command(name="spawn-pending", description="Spawn a pending purchase for a player (Admin only)")
    @app_commands.describe(purchase_id="Pending purchase ID")
    async def spawn_pending(self, interaction: discord.Interaction, purchase_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        await self.deliver_purchase(interaction, purchase_id, from_button=False)

    # ── /cancel-pending ──────────────────────────────────────
    @app_commands.command(name="cancel-pending", description="Cancel a pending purchase and refund points (Admin only)")
    @app_commands.describe(purchase_id="Pending purchase ID")
    async def cancel_pending(self, interaction: discord.Interaction, purchase_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        await self.cancel_purchase(interaction, purchase_id, from_button=False)

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
