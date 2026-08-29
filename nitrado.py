# nitrado.py - Nitrado API wrapper for ARK PS4/5 server management
# Handles server logs, player lists, restarts, cloud backups and file management
# (the FileServer/backup flows replace the old SFTP approach).

import requests
import guild_settings


NITRADO_BASE_URL = "https://api.nitrado.net"


class NitradoClient:
    """Client for interacting with a Nitrado-hosted ARK PS4/5 server."""

    def __init__(self, api_token: str, service_id: str):
        self.api_token = api_token
        self.service_id = service_id
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    # ── low-level ─────────────────────────────────────────────

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        url = f"{NITRADO_BASE_URL}{endpoint}"
        try:
            resp = requests.request(method, url, headers=self.headers, timeout=30, **kwargs)
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data)
        except requests.RequestException as e:
            print(f"Nitrado API error: {type(e).__name__}")
            return {}

    def _post_binary(self, url: str, token: str, content: str) -> bool:
        """POST raw binary content to a Nitrado upload URL."""
        try:
            resp = requests.post(
                url,
                params={"token": token},
                data=content.encode("utf-8"),
                headers={"content-type": "application/binary"},
                timeout=60,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Nitrado upload error: {type(e).__name__}")
            return False

    def _get_binary(self, url: str, token: str) -> str:
        """GET raw content from a Nitrado download URL."""
        try:
            resp = requests.get(
                url,
                params={"token": token},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"Nitrado download error: {type(e).__name__}")
            return ""

    def _get_bytes(self, url: str, token: str) -> bytes:
        """GET raw bytes from a Nitrado download URL (binary-safe)."""
        try:
            resp = requests.get(
                url,
                params={"token": token},
                timeout=120,
            )
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            print(f"Nitrado binary download error: {type(e).__name__}")
            return b""

    # ── server control ───────────────────────────────────────

    def get_server_status(self) -> dict:
        """Get current server status (online/offline, player count, etc.)"""
        return self._request("GET", f"/services/{self.service_id}/gameservers")

    def get_player_list(self) -> list[dict]:
        """Get list of currently connected players."""
        data = self._request("GET", f"/services/{self.service_id}/gameservers/games/players")
        players = data.get("players", [])
        return [
            {
                "name": p.get("name", "Unknown"),
                "id": p.get("id_num", p.get("unique_id", "0")),
                "ping": p.get("ping", 0),
            }
            for p in players
        ]

    def get_logs(self, lines: int = 200) -> str:
        """Get the last N lines of the server log."""
        data = self._request("GET", f"/services/{self.service_id}/gameservers/games/arkse/latest_log")
        log_content = data.get("content", "") if isinstance(data, dict) else ""
        log_lines = log_content.split("\n")
        return "\n".join(log_lines[-lines:])

    def restart_server(self) -> bool:
        """Restart the ARK server."""
        result = self._request("POST", f"/services/{self.service_id}/gameservers/restart")
        return bool(result)

    def stop_server(self) -> bool:
        """Stop the ARK server."""
        result = self._request("POST", f"/services/{self.service_id}/gameservers/stop")
        return bool(result)

    def start_server(self) -> bool:
        """Start the ARK server."""
        result = self._request("POST", f"/services/{self.service_id}/gameservers/games/start")
        return bool(result)

    def send_command(self, command: str) -> str:
        """Execute a server command via the Nitrado API (replaces direct RCON)."""
        data = self._request(
            "POST",
            f"/services/{self.service_id}/gameservers/app_server/command",
            json={"command": command},
        )
        if isinstance(data, dict):
            data = data.get("data", data)
        if isinstance(data, dict):
            return data.get("response", "")
        return ""

    def update_settings(self, settings: dict) -> bool:
        """Update server settings (game.ini, gameusersettings.ini via Nitrado)."""
        data = self._request(
            "POST",
            f"/services/{self.service_id}/gameservers/settings",
            json=settings,
        )
        return bool(data)

    def update_game_setting(self, category: str, key: str, value: str) -> bool:
        """Update a single game setting via the Nitrado gameservers/settings API.

        Body format: {"category": ..., "key": ..., "value": ...} where category is the
        ini section (e.g. "settings" for [ServerSettings] in GameUserSettings.ini).
        """
        data = self._request(
            "POST",
            f"/services/{self.service_id}/gameservers/settings",
            json={"category": category, "key": key, "value": value},
        )
        if isinstance(data, dict):
            return data.get("status") == "success" or bool(data)
        return bool(data)

    # ── file server (replaces SFTP file access) ──────────────

    def fs_base(self) -> str:
        return f"/services/{self.service_id}/gameservers/file_server"

    def list_files(self, directory: str) -> list[str]:
        """List files/folders in a directory on the server."""
        data = self._request(
            "GET",
            f"{self.fs_base()}/list",
            params={"dir": directory},
        )
        return [e.get("name") for e in data.get("entries", []) if e.get("name")]

    def write_file(self, path: str, name: str, content: str) -> bool:
        """Write a file on the server (overwrites if it exists)."""
        data = self._request(
            "POST",
            f"{self.fs_base()}/upload",
            json={"path": path, "file": name},
        )
        token_info = data.get("token") or data
        token = token_info.get("token")
        url = token_info.get("url")
        if not token or not url:
            return False
        return self._post_binary(url, token, content)

    def read_file(self, file: str) -> str:
        """Read a file's content from the server."""
        data = self._request("GET", f"{self.fs_base()}/download", params={"file": file})
        token_info = data.get("token") or data
        token = token_info.get("token")
        url = token_info.get("url")
        if not token or not url:
            return ""
        return self._get_binary(url, token)

    def list_file_entries(self, directory: str) -> list[dict]:
        """List file/dir entries (name, size, type, path) in a directory."""
        data = self._request(
            "GET",
            f"{self.fs_base()}/list",
            params={"dir": directory},
        )
        entries = data.get("entries", []) if isinstance(data, dict) else []
        out = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            out.append(
                {
                    "name": e.get("name"),
                    "size": e.get("size") or 0,
                    "type": e.get("type"),
                    "path": e.get("path") or directory,
                }
            )
        return out

    def download_file_bytes(self, file: str) -> bytes:
        """Download a file as raw bytes (binary-safe). Returns b'' on failure."""
        data = self._request("GET", f"{self.fs_base()}/download", params={"file": file})
        token_info = data.get("token") or data
        token = token_info.get("token")
        url = token_info.get("url")
        if not token or not url:
            return b""
        return self._get_bytes(url, token)

    def delete_file(self, file: str) -> bool:
        """Delete a file on the server."""
        result = self._request(
            "DELETE",
            f"{self.fs_base()}/delete",
            json={"path": file},
        )
        return True  # endpoint raises on error; success is un-typed

    def create_directory(self, path: str, name: str) -> bool:
        """Create a directory on the server."""
        result = self._request(
            "POST",
            f"{self.fs_base()}/mkdir",
            json={"path": path, "name": name},
        )
        return True

    # ── cloud backups ────────────────────────────────────────

    def backup_list(self) -> list[dict]:
        """List available cloud backups."""
        data = self._request("GET", f"/services/{self.service_id}/gameservers/backups")
        if isinstance(data, dict):
            backups = data.get("backups", [])
        else:
            backups = data
        return backups if isinstance(backups, list) else []

    def backup_create(self, backup_type: str = "game") -> bool:
        """Create a cloud backup ('game' or another supported type)."""
        result = self._request(
            "POST",
            f"/services/{self.service_id}/gameservers/backups",
            json={"type": backup_type},
        )
        status = result.get("status") if isinstance(result, dict) else None
        return status == "success" or bool(result)

    def backup_restore(self, name: str, paths: list[str] | None = None) -> bool:
        """Restore a cloud backup to the server."""
        result = self._request(
            "POST",
            f"/services/{self.service_id}/gameservers/backups/extract",
            json={"name": name, "paths": paths or []},
        )
        return bool(result)

    def backup_delete(self, name: str) -> bool:
        """Delete a cloud backup."""
        result = self._request(
            "DELETE",
            f"/services/{self.service_id}/gameservers/backups",
            params={"prefix": name},
        )
        return True


def get_client(guild_id: int) -> NitradoClient | None:
    """Get a Nitrado client for a guild. Returns None if not configured."""
    config = guild_settings.get_nitrado_config(guild_id)
    token = config.get("api_token")
    service_id = config.get("service_id")
    if not token or not service_id:
        return None
    return NitradoClient(token, service_id)


def send_rcon(guild_id: int, command: str) -> str | None:
    """Send a server command via the Nitrado API. Returns response or None."""
    client = get_client(guild_id)
    if not client:
        return None
    try:
        return client.send_command(command)
    except Exception as e:
        print(f"[Nitrado] send_command error (guild {guild_id}): {type(e).__name__}")
        return None


def get_server_info(guild_id: int) -> dict:
    """Get server info for a guild. Returns empty dict if not configured."""
    client = get_client(guild_id)
    if not client:
        return {}
    return client.get_server_status()


def change_admin_password(guild_id: int, password: str) -> str:
    """Change the ARK admin password via the RCON SetAdminPassword command."""
    client = get_client(guild_id)
    if not client:
        return "Nitrado not configured"
    if not password:
        return "No password provided"
    result = client.send_command(f"SetAdminPassword {password}")
    return "Applied" if result is not None else "Command failed"


def change_server_password(guild_id: int, password: str) -> str:
    """Change the ARK server (join) password via the Nitrado settings API."""
    client = get_client(guild_id)
    if not client:
        return "Nitrado not configured"
    if not password:
        return "No password provided"
    ok = client.update_game_setting("settings", "ServerPassword", password)
    return "Applied" if ok else "Failed"


def get_ark_server_name(guild_id: int) -> str:
    """Read the actual ARK server name from GameUserSettings.ini (SessionName)."""
    client = get_client(guild_id)
    if not client:
        return ""
    for path in [
        "ShooterGame/Saved/Config/GameUserSettings.ini",
        "ShooterGame/Saved/Config/LinuxServer/GameUserSettings.ini",
    ]:
        try:
            content = client.read_file(path)
            if content:
                for line in content.splitlines():
                    line = line.strip()
                    if line.lower().startswith("sessionname="):
                        name = line.split("=", 1)[1].strip()
                        if name:
                            return name
                return ""
        except Exception:
            continue
    return ""


def server_name(guild_id: int) -> str:
    """Best-effort ARK server name: GameUserSettings first, then API info."""
    name = get_ark_server_name(guild_id)
    if name:
        return name
    try:
        info = get_server_info(guild_id) or {}
        inner = info.get("gameserver", info) if isinstance(info, dict) else {}
        return str(inner.get("name") or inner.get("server_name") or "") if isinstance(inner, dict) else ""
    except Exception:
        return ""


def ban_player(guild_id: int, name: str) -> str:
    """Ban a player by name via ARK RCON. Returns a status message."""
    client = get_client(guild_id)
    if not client:
        return "Nitrado not configured"
    try:
        client.send_command(f"Ban {name}")
        return "Banned"
    except Exception as e:
        return "Failed: " + type(e).__name__


def unban_player(guild_id: int, name: str) -> str:
    """Unban a player by name via ARK RCON. Returns a status message."""
    client = get_client(guild_id)
    if not client:
        return "Nitrado not configured"
    try:
        client.send_command(f"Unban {name}")
        return "Unbanned"
    except Exception as e:
        return "Failed: " + type(e).__name__


def whitelist_player(guild_id: int, name: str) -> str:
    """Add a player to the Nitrado whitelist. Best-effort; returns a status message."""
    client = get_client(guild_id)
    if not client:
        return "Nitrado not configured"
    try:
        data = client._request(
            "POST",
            f"/services/{client.service_id}/gameservers/games/whitelist",
            json={"add": name},
        )
        return "Whitelisted" if data else "Failed"
    except Exception as e:
        return "Failed: " + type(e).__name__

