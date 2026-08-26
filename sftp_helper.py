# sftp_helper.py - Shared SFTP operations for ARK server file management
# Used by whitelist, server_backup, and any cog that needs file access

import io
import paramiko
import guild_settings


def connect_sftp(guild_id: int):
    """Create an SFTP connection for a guild's server. Returns paramiko.SFTPClient or None."""
    host = guild_settings.get_setting(guild_id, "sftp_host")
    port = int(guild_settings.get_setting(guild_id, "sftp_port", "22"))
    username = guild_settings.get_setting(guild_id, "sftp_username")
    password = guild_settings.get_setting(guild_id, "sftp_password")

    if not host or not username or not password:
        return None

    transport = paramiko.Transport((host, port))
    transport.connect(username=username, password=password)
    return paramiko.SFTPClient.from_transport(transport)


def read_file(guild_id: int, remote_path: str) -> str | None:
    """Read a file from the server via SFTP. Returns content string or None."""
    sftp = connect_sftp(guild_id)
    if not sftp:
        return None
    try:
        with sftp.open(remote_path, "r") as f:
            return f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None
    finally:
        sftp.close()


def write_file(guild_id: int, remote_path: str, content: str) -> bool:
    """Write content to a file on the server via SFTP."""
    sftp = connect_sftp(guild_id)
    if not sftp:
        return False
    try:
        with sftp.open(remote_path, "w") as f:
            f.write(content)
        return True
    finally:
        sftp.close()


def append_line(guild_id: int, remote_path: str, line: str) -> bool:
    """Append a line to a remote file."""
    existing = read_file(guild_id, remote_path)
    if existing is None:
        existing = ""
    lines = [l for l in existing.split("\n") if l.strip()]
    if line not in lines:
        lines.append(line)
    return write_file(guild_id, remote_path, "\n".join(lines) + "\n")


def remove_line(guild_id: int, remote_path: str, line: str) -> bool:
    """Remove a specific line from a remote file."""
    existing = read_file(guild_id, remote_path)
    if existing is None:
        return False
    lines = [l for l in existing.split("\n") if l.strip() and l.strip() != line.strip()]
    return write_file(guild_id, remote_path, "\n".join(lines) + "\n")


def download_file(guild_id: int, remote_path: str) -> bytes | None:
    """Download a file and return its bytes. Returns None on failure."""
    sftp = connect_sftp(guild_id)
    if not sftp:
        return None
    try:
        buf = io.BytesIO()
        sftp.getfo(remote_path, buf)
        return buf.getvalue()
    except FileNotFoundError:
        return None
    finally:
        sftp.close()


def list_dir(guild_id: int, remote_path: str) -> list[str]:
    """List files in a remote directory."""
    sftp = connect_sftp(guild_id)
    if not sftp:
        return []
    try:
        return sftp.listdir(remote_path)
    except FileNotFoundError:
        return []
    finally:
        sftp.close()
