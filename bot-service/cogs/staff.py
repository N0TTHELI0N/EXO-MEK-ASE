import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone

import guild_settings
import bot_i18n
import config


def _log(guild_id, sub_type, user, target=None, details=None):
    guild_settings.log_admin_action(
        guild_id, user.id if user else None, str(user) if user else None,
        sub_type, target, details,
    )


class Staff(commands.Cog):
    """Staff payment tracking system."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="staff-pay", description="Record a payment for a staff member")
    @app_commands.describe(
        member="The staff member (Discord user)",
        amount="Payment amount",
        role="Staff role label",
        payment_type="Payment type (e.g. salary, bonus, reward)",
        currency="Currency code (default USD)",
        note="Optional note",
    )
    async def staff_pay(self, interaction: discord.Interaction, member: discord.Member, amount: float,
                        role: str = "staff", payment_type: str = "payment",
                        currency: str = "USD", note: str = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        payment_id = guild_settings.add_staff_payment(
            interaction.guild_id, member.id, str(member), role, payment_type,
            amount, currency=currency, note=note, issued_by=interaction.user.id,
        )
        _log(interaction.guild_id, "staff_pay", interaction.user, str(member),
             details={"amount": amount, "type": payment_type, "note": note})
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "staff_payment_recorded",
                       currency=currency, amount=amount, member=member.mention,
                       role=role, payment_type=payment_type, payment_id=payment_id),
            ephemeral=True,
        )

    @app_commands.command(name="staff-payments", description="List staff payments (filter by status)")
    @app_commands.describe(status="Filter by status (pending/paid)")
    @app_commands.choices(status=[
        app_commands.Choice(name="Pending", value="pending"),
        app_commands.Choice(name="Paid", value="paid"),
    ])
    async def staff_payments(self, interaction: discord.Interaction, status: app_commands.Choice[str] = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        payments = guild_settings.get_staff_payments(interaction.guild_id, status=status.value if status else None)
        if not payments:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "staff_no_payments"), ephemeral=True)

        lines = []
        for p in payments[:25]:
            st = "✅" if p["status"] == "paid" else "⏳"
            who = f"<@{p['staff_user_id']}>" if p['staff_user_id'] else p["staff_name"]
            lines.append(f"{st} #{p['id']} **{p['currency']} {p['amount']:,.2f}** → {who} ({p['role']}, {p['payment_type']})")
        title = bot_i18n.t(interaction.guild_id, "staff_payments_title")
        embed = discord.Embed(title=title, description="\n".join(lines), color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="staff-pay-status", description="Mark a staff payment as paid or pending")
    @app_commands.describe(payment_id="Payment ID", status="New status")
    @app_commands.choices(status=[
        app_commands.Choice(name="Paid", value="paid"),
        app_commands.Choice(name="Pending", value="pending"),
    ])
    async def staff_pay_status(self, interaction: discord.Interaction, payment_id: int, status: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        if guild_settings.set_staff_payment_status(payment_id, interaction.guild_id, status.value):
            _log(interaction.guild_id, "staff_pay_status", interaction.user, None, details={"payment_id": payment_id, "status": status.value})
            await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "staff_payment_status_set", payment_id=payment_id, status=status.name), ephemeral=True)
        else:
            await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "staff_payment_not_found", payment_id=payment_id), ephemeral=True)

    @app_commands.command(name="staff-pay-delete", description="Delete a staff payment record")
    @app_commands.describe(payment_id="Payment ID")
    async def staff_pay_delete(self, interaction: discord.Interaction, payment_id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        if guild_settings.delete_staff_payment(payment_id, interaction.guild_id):
            _log(interaction.guild_id, "staff_pay_delete", interaction.user, None, details={"payment_id": payment_id})
            await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "staff_payment_deleted", payment_id=payment_id), ephemeral=True)
        else:
            await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "staff_payment_not_found", payment_id=payment_id), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Staff(bot))
