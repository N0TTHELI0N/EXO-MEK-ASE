# nitrado.py - Nitrado API wrapper for ARK PS4/5 server management
# Handles server logs, player lists, restarts, and other Nitrado-specific operations

import requests
import guild_settings


NITRADO_BASE_URL = "https://api.nitrado.com"


class NitradoClient:
    """Client for interacting with a Nitrado-hosted ARK PS4/5 server."""

    def __init__(self, api_token: str, service_id: str):
        self.api_token = api_token
        self.service_id = service_id
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

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

    def get_server_status(self) -> dict:
        """Get current server status (online/offline, player count, etc.)"""
        return self._request("GET", f"/services/{self.service_id}/gameserver")

    def get_player_list(self) -> list[dict]:
        """Get list of currently connected players."""
        data = self._request("GET", f"/services/{self.service_id}/gameserver")
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
        data = self._request("GET", f"/services/{self.service_id}/gameserver/logs")
        log_content = data.get("content", "")
        log_lines = log_content.split("\n")
        return "\n".join(log_lines[-lines:])

    def restart_server(self) -> bool:
        """Restart the ARK server."""
        result = self._request("POST", f"/services/{self.service_id}/gameserver/restart")
        return bool(result)

    def stop_server(self) -> bool:
        """Stop the ARK server."""
        result = self._request("POST", f"/services/{self.service_id}/gameserver/stop")
        return bool(result)

    def start_server(self) -> bool:
        """Start the ARK server."""
        result = self._request("POST", f"/services/{self.service_id}/gameserver/start")
        return bool(result)

    def send_rcon(self, command: str) -> str:
        """Send an RCON command via Nitrado API."""
        payload = {"command": command}
        data = self._request(
            "POST",
            f"/services/{self.service_id}/gameserver/rcon",
            json=payload,
        )
        return data.get("response", "")

    def update_settings(self, settings: dict) -> bool:
        """Update server settings (game.ini, gameusersettings.ini via Nitrado)."""
        data = self._request(
            "POST",
            f"/services/{self.service_id}/gameserver/settings",
            json=settings,
        )
        return bool(data)


def get_client(guild_id: int) -> NitradoClient | None:
    """Get a Nitrado client for a guild. Returns None if not configured."""
    config = guild_settings.get_nitrado_config(guild_id)
    token = config.get("api_token")
    service_id = config.get("service_id")
    if not token or not service_id:
        return None
    return NitradoClient(token, service_id)


def get_server_info(guild_id: int) -> dict:
    """Get server info for a guild. Returns empty dict if not configured."""
    client = get_client(guild_id)
    if not client:
        return {}
    return client.get_server_status()
