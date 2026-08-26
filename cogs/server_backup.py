import os
import io
import stat
import zipfile
import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timezone
import paramiko
import guild_settings
import bot_i18n
import config
from security import validate_path


# ── DB helpers ──────────────────────────────────────────────

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


def _save_backup_record(guild_id: int, name: str, created_by: int, file_path: str):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO backup_records (guild_id, name, created_by, file_path) VALUES (%s, %s, %s, %s)",
                (guild_id, name, created_by, file_path),
            )
        conn.commit()
    finally:
        conn.close()


def _get_backup_records(guild_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, created_at, created_by FROM backup_records WHERE guild_id = %s ORDER BY created_at DESC",
                (guild_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _get_backup_record(guild_id: int, backup_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, file_path FROM backup_records WHERE guild_id = %s AND id = %s",
                (guild_id, backup_id),
            )
            return cur.fetchone()
    finally:
        conn.close()


def _delete_backup_record(guild_id: int, backup_id: int):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM backup_records WHERE guild_id = %s AND id = %s",
                (guild_id, backup_id),
            )
        conn.commit()
    finally:
        conn.close()


# ── SFTP helpers ────────────────────────────────────────────

def _sftp_connect(guild_id: int):
    host = guild_settings.get_setting(guild_id, "sftp_host") or os.getenv("SFTP_HOST", "")
    port = guild_settings.get_setting(guild_id, "sftp_port") or int(os.getenv("SFTP_PORT", "22"))
    username = guild_settings.get_setting(guild_id, "sftp_username") or os.getenv("SFTP_USERNAME", "")
    password = guild_settings.get_setting(guild_id, "sftp_password") or os.getenv("SFTP_PASSWORD", "")

    if not all([host, username, password]):
        return None

    transport = paramiko.Transport((host, int(port)))
    transport.connect(username=username, password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    return sftp, transport


def _sftp_walk(sftp, remote_path):
    """Recursively walk a remote directory, yielding (dirpath, dirnames, filenames)."""
    dirs = []
    files = []
    for entry in sftp.listdir_attr(remote_path):
        name = entry.st_filename
        if stat.S_ISDIR(entry.st_mode):
            dirs.append(name)
        else:
            files.append(name)
    yield remote_path, dirs, files
    for d in dirs:
        yield from _sftp_walk(sftp, os.path.join(remote_path, d))


def _sftp_get_tree(sftp, remote_path, local_path):
    """Download an entire remote directory tree."""
    os.makedirs(local_path, exist_ok=True)
    for dirpath, dirnames, filenames in sftp.walk(remote_path):
        rel = os.path.relpath(dirpath, remote_path)
        local_dir = os.path.join(local_path, rel)
        os.makedirs(local_dir, exist_ok=True)
        for f in filenames:
            remote_file = os.path.join(dirpath, f)
            local_file = os.path.join(local_dir, f)
            sftp.get(remote_file, local_file)


def _sftp_put_tree(sftp, local_path, remote_path):
    """Upload an entire local directory tree."""
    for root, dirs, files in os.walk(local_path):
        rel = os.path.relpath(root, local_path)
        remote_dir = os.path.join(remote_path, rel)
        try:
            sftp.mkdir(remote_dir)
        except IOError:
            pass
        for f in files:
            local_file = os.path.join(root, f)
            remote_file = os.path.join(remote_dir, f)
            sftp.put(local_file, remote_file)


# ── Autocomplete ────────────────────────────────────────────

async def backup_autocomplete(interaction: discord.Interaction, current: str):
    records = _get_backup_records(interaction.guild_id)
    return [
        app_commands.Choice(name=f"#{r[0]} {r[1]} ({r[2].strftime('%Y-%m-%d %H:%M')})", value=str(r[0]))
        for r in records if current.lower() in r[1].lower()
    ][:25]


# ── Cog ─────────────────────────────────────────────────────

class ServerBackup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        _init_backup_db()

    # ── /set-sftp ────────────────────────────────────────────
    @app_commands.command(name="set-sftp", description="Set SFTP credentials for backups (Admin only)")
    @app_commands.describe(host="SFTP host", port="Port", username="Username", password="Password")
    async def set_sftp(self, interaction: discord.Interaction, host: str, port: int = 22, username: str = "", password: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        guild_settings.update_setting(interaction.guild_id, "sftp_host", host)
        guild_settings.update_setting(interaction.guild_id, "sftp_port", port)
        guild_settings.update_setting(interaction.guild_id, "sftp_username", username)
        guild_settings.update_setting(interaction.guild_id, "sftp_password", password)
        await interaction.response.send_message("✅ SFTP credentials saved.", ephemeral=True)

    # ── /backup-create ───────────────────────────────────────
    @app_commands.command(name="backup-create", description="Create a server backup (Admin only)")
    @app_commands.describe(name="Backup name (optional)")
    async def backup_create(self, interaction: discord.Interaction, name: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        sftp_result = _sftp_connect(interaction.guild_id)
        if not sftp_result:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "sftp_not_configured"), ephemeral=True)

        sftp, transport = sftp_result
        try:
            save_dir = guild_settings.get_setting(interaction.guild_id, "save_dir", "/ARK/ShooterGame/Saved")
            backup_name = name or f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for dirpath, dirnames, filenames in _sftp_walk(sftp, save_dir):
                    for f in filenames:
                        remote_file = os.path.join(dirpath, f)
                        arcname = os.path.relpath(remote_file, save_dir)
                        data = sftp.open(remote_file, "rb").read()
                        zf.writestr(arcname, data)

            local_path = f"./backups/{interaction.guild_id}/{backup_name}.zip"
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(zip_buffer.getvalue())

            _save_backup_record(interaction.guild_id, backup_name, interaction.user.id, local_path)
            guild_settings.log_action(interaction.guild_id, "server", interaction.user.id, str(interaction.user), None, sub_type="backup", details={"action": "create", "name": backup_name})
            await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_created", name=backup_name), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_failed") + f"\n`{e}`", ephemeral=True)
        finally:
            sftp.close()
            transport.close()

    # ── /backup-list ─────────────────────────────────────────
    @app_commands.command(name="backup-list", description="List all server backups")
    async def backup_list(self, interaction: discord.Interaction):
        records = _get_backup_records(interaction.guild_id)
        if not records:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "backup_list_empty"), ephemeral=True)

        lines = [f"#{r[0]} — **{r[1]}** ({r[2].strftime('%Y-%m-%d %H:%M UTC')})" for r in records]
        embed = discord.Embed(title="📦 Backups", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed)

    # ── /backup-rollback ─────────────────────────────────────
    @app_commands.command(name="backup-rollback", description="Restore a backup to the server (Admin only)")
    @app_commands.describe(backup_id="Backup ID from /backup-list")
    @app_commands.autocomplete(backup_id=backup_autocomplete)
    async def backup_rollback(self, interaction: discord.Interaction, backup_id: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)

        record = _get_backup_record(interaction.guild_id, int(backup_id))
        if not record:
            return await interaction.response.send_message("❌ Backup not found.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        sftp_result = _sftp_connect(interaction.guild_id)
        if not sftp_result:
            return await interaction.followup.send(bot_i18n.t(interaction.guild_id, "sftp_not_configured"), ephemeral=True)

        sftp, transport = sftp_result
        try:
            save_dir = guild_settings.get_setting(interaction.guild_id, "save_dir", "/ARK/ShooterGame/Saved")
            local_zip = record[2]
            with zipfile.ZipFile(local_zip, "r") as zf:
                for member in zf.infolist():
                    remote_path = os.path.normpath(os.path.join(save_dir, member.filename))
                    if not remote_path.startswith(os.path.normpath(save_dir)):
                        await interaction.followup.send(f"❌ Path traversal detected in zip: {member.filename}", ephemeral=True)
                        return
                    remote_dir = os.path.dirname(remote_path)
                    try:
                        sftp.mkdir(remote_dir)
                    except IOError:
                        pass
                    data = zf.read(member.filename)
                    with sftp.open(remote_path, "wb") as f:
                        f.write(data)

            guild_settings.log_action(interaction.guild_id, "server", interaction.user.id, str(interaction.user), None, sub_type="backup", details={"action": "restore", "name": record[1]})
            await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_restored", name=record[1]), ephemeral=True)
        except Exception as e:
            await interaction.followup.send(bot_i18n.t(interaction.guild_id, "backup_failed") + f"\n`{e}`", ephemeral=True)
        finally:
            sftp.close()
            transport.close()

    # ── /backup-download ─────────────────────────────────────
    @app_commands.command(name="backup-download", description="Download a backup file")
    @app_commands.describe(backup_id="Backup ID from /backup-list")
    @app_commands.autocomplete(backup_id=backup_autocomplete)
    async def backup_download(self, interaction: discord.Interaction, backup_id: str):
        record = _get_backup_record(interaction.guild_id, int(backup_id))
        if not record:
            return await interaction.response.send_message("❌ Backup not found.", ephemeral=True)

        local_zip = record[2]
        if not os.path.exists(local_zip):
            return await interaction.response.send_message("❌ Backup file not found on disk.", ephemeral=True)

        await interaction.response.send_message(
            f"📦 Backup **{record[1]}**",
            file=discord.File(local_zip, filename=f"{record[1]}.zip"),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(ServerBackup(bot))
