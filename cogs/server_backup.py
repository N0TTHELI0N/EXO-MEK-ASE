import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import guild_settings
import bot_i18n
from nitrado import get_client


# ── DB helpers (audit log of backups created via the bot) ───

def _init_backup_db():
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS backup_records (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    name        TEXT NOT NULL,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    created_by  BIGINT,
                    file_path   TEXT
                )
            """)
        conn.commit()
    finally:
        conn.close()


def _save_backup_record(guild_id: int, name: str, created_by: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO backup_records (guild_id, name, created_by) VALUES (%s, %s, %s)",
                (guild_id, name, created_by),
            )
        conn.commit()
    finally:
        conn.close()


def _get_backup_records(guild_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, created_at FROM backup_records WHERE guild_id = %s ORDER BY created_at DESC",
                (guild_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ── Helper to fetch cloud backups from Nitrado ──────────────

def _nitrado_backups(guild_id: int) -> list[dict]:
    client = get_client(guild_id)
    if not client:
        return []
    return client.backup_list()


# ── Autocomplete ────────────────────────────────────────────

async def backup_autocomplete(interaction: discord.Interaction, current: str):
    backups = _nitrado_backups(interaction.guild_id)
    names = []
    for b in backups:
        if isinstance(b, dict):
            n = b.get("name") or b.get("backup") or b.get("id") or str(b)
        else:
            n = str(b)
        if n and current.lower() in str(n).lower():
            names.append(str(n))
    return [app_commands.Choice(name=n[:90], value=n[:90]) for n in names[:25]]


# ── Cog ─────────────────────────────────────────────────────

class ServerBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _init_backup_db()

    # ── /backup-create ───────────────────────────────────────
    @app_commands.command(name="backup-create", description="Create a Nitrado cloud backup (Admin only)")
    async def backup_create(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        client = get_client(interaction.guild_id)
        if not client:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "nitrado_not_configured"), ephemeral=True)

        try:
            ok = client.backup_create("game")
            name = datetime.now(timezone.utc).strftime("backup_%Y%m%d_%H%M%S")
            _save_backup_record(interaction.guild_id, name, interaction.user.id)
            guild_settings.log_action(
                interaction.guild_id, "server", interaction.user.id, str(interaction.user),
                None, sub_type="backup", details={"action": "create", "name": name},
            )
            if not ok:
                await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_failed"), ephemeral=True)
                return
            await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_created", name=name), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_failed") + f"\n`{e}`", ephemeral=True)

    # ── /backup-list ─────────────────────────────────────────
    @app_commands.command(name="backup-list", description="List all Nitrado cloud backups")
    async def backup_list(self, interaction: discord.Interaction):
        backups = _nitrado_backups(interaction.guild_id)
        if not backups:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "backup_list_empty"), ephemeral=True)

        lines = []
        for b in backups[:20]:
            if isinstance(b, dict):
                n = b.get("name") or b.get("backup") or b.get("id") or "backup"
                t = b.get("created_at") or b.get("date") or b.get("timestamp") or ""
                lines.append(f"• **{n}** {t}".strip())
            else:
                lines.append(f"• **{b}**")

        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "backup_title"), description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /backup-rollback ─────────────────────────────────────
    @app_commands.command(name="backup-rollback", description="Restore a Nitrado cloud backup to the server (Admin only)")
    @app_commands.describe(backup_name="Backup name from /backup-list")
    @app_commands.autocomplete(backup_name=backup_autocomplete)
    async def backup_rollback(self, interaction: discord.Interaction, backup_name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        client = get_client(interaction.guild_id)
        if not client:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "nitrado_not_configured"), ephemeral=True)

        try:
            ok = client.backup_restore(backup_name)
            guild_settings.log_action(
                interaction.guild_id, "server", interaction.user.id, str(interaction.user),
                None, sub_type="backup", details={"action": "restore", "name": backup_name},
            )
            if not ok:
                await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_failed"), ephemeral=True)
                return
            await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_restored", name=backup_name), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_failed") + f"\n`{e}`", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ServerBackup(bot))
