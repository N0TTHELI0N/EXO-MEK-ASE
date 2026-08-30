# sftp_client.py - SFTP file access for Nitrado ARK saves via paramiko.
# Replaces the Nitrado file-server API for the Save Files browser (which
# returns empty on PlayStation services).

import os
import stat

import paramiko


class SFTPClient:
    """SFTP browser over a Nitrado gameserver's FTP credentials."""

    def __init__(self, host: str, username: str, password: str, port: int = 22):
        self.host = host
        self.username = username
        self.password = password
        self.port = int(port or 22)

    def _connect(self):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=30,
        )
        return client, client.open_sftp()

    def list_entries(self, path: str) -> list[dict]:
        """Return sorted entries (dirs first) for an SFTP directory path."""
        path = path or "/"
        client = None
        sftp = None
        out = []
        try:
            client, sftp = self._connect()
            for attr in sftp.listdir_attr(path):
                is_dir = stat.S_ISDIR(attr.st_mode)
                out.append(
                    {
                        "name": attr.filename,
                        "size": attr.st_size if not is_dir else 0,
                        "type": "dir" if is_dir else "file",
                        "size_s": "",
                        "is_dir": is_dir,
                        "path": (path.rstrip("/") + "/" + attr.filename),
                        "mtime": int(getattr(attr, "st_mtime", 0) or 0),
                    }
                )
        finally:
            if sftp is not None:
                sftp.close()
            if client is not None:
                client.close()
        out.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return out

    def download(self, path: str) -> bytes:
        """Download a file's raw bytes."""
        client = None
        sftp = None
        try:
            client, sftp = self._connect()
            with sftp.open(path, "rb") as f:
                return f.read()
        finally:
            if sftp is not None:
                sftp.close()
            if client is not None:
                client.close()

    def upload(self, path: str, filename: str, data: bytes) -> bool:
        """Upload bytes to a directory path."""
        client = None
        sftp = None
        try:
            client, sftp = self._connect()
            target = path.rstrip("/") + "/" + filename
            try:
                sftp.stat(path)
            except IOError:
                sftp.mkdir(path)
            with sftp.open(target, "wb") as f:
                f.write(data)
            return True
        except Exception as e:
            print(f"[sftp] upload error: {type(e).__name__}: {e}")
            return False
        finally:
            if sftp is not None:
                sftp.close()
            if client is not None:
                client.close()


def get_sftp_config(guild_id: int) -> dict:
    """Return FTP/SFTP credentials for a guild (empty dict if not configured)."""
    cfg = {}
    try:
        import guild_settings
        info = guild_settings.get_nitrado_config(guild_id)
        if info.get("ftp_host") and info.get("ftp_user") and info.get("ftp_password"):
            cfg = {
                "host": info["ftp_host"],
                "port": int(info.get("ftp_port") or 22),
                "user": info["ftp_user"],
                "password": info["ftp_password"],
            }
    except Exception as e:
        print(f"[sftp] config error: {type(e).__name__}: {e}")
    return cfg


def make_sftp(guild_id: int) -> SFTPClient | None:
    """Build an SFTPClient from stored guild config, or None if unset."""
    cfg = get_sftp_config(guild_id)
    if not cfg:
        return None
    return SFTPClient(cfg["host"], cfg["user"], cfg["password"], cfg["port"])
