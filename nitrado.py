# nitrado.py - Nitrado API wrapper for ARK PS4/5 server management
# Handles server logs, player lists, restarts, cloud backups and file management
# (the FileServer/backup flows replace the old SFTP approach).

import time
import requests
import guild_settings


NITRADO_BASE_URL = "https://api.nitrado.net"

_ERR_LOG_THROTTLE = {}

# Global Nitrado request throttle + backoff. Heavy probing (or the dashboard
# polling) tripped Cloudflare ("429 Just a moment..."), so we enforce a minimum
# gap between every API call and a hard cooldown after any 429.
_NITRADO_MIN_INTERVAL = 1.0
_nitrado_last_req = 0.0
_nitrado_cooldown_until = 0.0
_player_raw_logged = False


def _begin_request() -> bool:
    """Wait for the minimum request gap; returns False if cooling down."""
    global _nitrado_last_req, _nitrado_cooldown_until
    now = time.monotonic()
    if now < _nitrado_cooldown_until:
        return False
    wait = _nitrado_last_req + _NITRADO_MIN_INTERVAL - now
    if wait > 0:
        time.sleep(wait)
    _nitrado_last_req = time.monotonic()
    return True


def _mark_429(reason: str = ""):
    global _nitrado_cooldown_until
    if time.monotonic() >= _nitrado_cooldown_until:
        print(f"[nitrado] 429/rejected by Cloudflare{(': ' + reason) if reason else ''} — pausing all Nitrado calls for 180s", flush=True)
    _nitrado_cooldown_until = time.monotonic() + 180.0


def _log_error_once(status, endpoint, body):
    """Log a Nitrado error at most once per (status, endpoint) window (process-wide)."""
    import time as _t
    key = f"{status}::{endpoint}"
    now = _t.monotonic()
    if now - _ERR_LOG_THROTTLE.get(key, 0) < 120:
        return
    _ERR_LOG_THROTTLE[key] = now
    if len(_ERR_LOG_THROTTLE) > 100:
        _ERR_LOG_THROTTLE.clear()
    print(f"Nitrado API error: HTTPError status={status} endpoint={endpoint} body={body!r}", flush=True)


class NitradoClient:
    """Client for interacting with a Nitrado-hosted ARK PS4/5 server."""

    def __init__(self, api_token: str, service_id: str):
        self.api_token = api_token
        self.service_id = service_id
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        self._log_fail_ts = {}
        self._gs_cached = None
        self._probe_next_idx = {"ShooterGame_Last.log": 0, "ShooterGame.log": 0}
        self._sftp_fail_ts = 0.0
        self._seek_broken = {}

    def _extract_token_url(self, payload) -> tuple[str, str]:
        """Pull (token, url) from a file_server response payload.

        Nitrado wraps upload/download/seek responses as
        {"status": "success", "data": {"token": {"token": ..., "url": ...}}}
        (the body may itself already be that data node). Returns ("", "") if
        the token/url pair can't be found.
        """
        if not isinstance(payload, dict):
            return "", ""
        node = payload
        for _ in range(3):
            if isinstance(node, dict) and isinstance(node.get("data"), dict):
                node = node["data"]
            else:
                break
        if isinstance(node, dict):
            tk = node.get("token")
            if isinstance(tk, dict):
                return str(tk.get("token") or ""), str(tk.get("url") or "")
            if isinstance(tk, str) and tk:
                return tk, str(node.get("url") or "")
            if isinstance(node.get("url"), str) and node["url"]:
                return "", node["url"]
        return "", ""

    # ── low-level ─────────────────────────────────────────────

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        if not _begin_request():
            return {}
        url = f"{NITRADO_BASE_URL}{endpoint}"
        try:
            resp = requests.request(method, url, headers=self.headers, timeout=10, **kwargs)
            if resp.status_code == 429:
                _mark_429(str(resp.status_code))
                return {}
            resp.raise_for_status()
            data = resp.json()
            outer = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(outer, list):
                outer = outer[0] if outer else {}
            return outer or {}
        except requests.RequestException as e:
            status = getattr(e.response, "status_code", None)
            if status == 429:
                _mark_429(str(status))
            body = ""
            try:
                if e.response is not None:
                    body = (e.response.text or "")[:150]
            except Exception:
                pass
            _log_error_once(status, endpoint, body)
            return {}

    def _raw(self, method: str, endpoint: str, **kwargs):
        """Send a request without raising; return (status_code, payload)."""
        if not _begin_request():
            return 429, {"_text": "throttled", "throttled": True}
        url = f"{NITRADO_BASE_URL}{endpoint}"
        try:
            resp = requests.request(method, url, headers=self.headers, timeout=10, **kwargs)
            if resp.status_code == 429:
                _mark_429(str(resp.status_code))
                return resp.status_code, {"_text": (resp.text or "")[:300]}
            try:
                payload = resp.json()
            except Exception:
                payload = {"_text": (resp.text or "")[:300]}
            return resp.status_code, payload
        except requests.RequestException as e:
            if getattr(e.response, "status_code", None) == 429:
                _mark_429("429")
            return getattr(e.response, "status_code", 0), {}

    def list_services(self) -> list[dict]:
        """List all Nitrado services accessible with this token."""
        code, body = self._raw("GET", "/services")
        if not isinstance(body, dict):
            return []
        inner = body.get("data", body)
        if isinstance(inner, dict):
            services = inner.get("services", [])
        elif isinstance(inner, list):
            services = inner
        else:
            services = []
        return services if isinstance(services, list) else []

    def _post_binary(self, url: str, token: str, content: str) -> bool:
        """POST raw binary content to a Nitrado upload URL."""
        if time.monotonic() < _nitrado_cooldown_until:
            return False
        try:
            resp = requests.post(
                url,
                params={"token": token},
                data=content.encode("utf-8"),
                headers={"content-type": "application/binary"},
                timeout=60,
            )
            if resp.status_code == 429:
                _mark_429(str(resp.status_code))
                return False
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Nitrado upload error: {type(e).__name__}")
            return False

    def _get_binary(self, url: str, token: str) -> str:
        """GET raw content from a Nitrado download URL."""
        if time.monotonic() < _nitrado_cooldown_until:
            return ""
        try:
            resp = requests.get(
                url,
                params={"token": token},
                timeout=60,
            )
            if resp.status_code == 429:
                _mark_429(str(resp.status_code))
                return ""
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"Nitrado download error: {type(e).__name__}")
            return ""

    def _get_bytes(self, url: str, token: str) -> bytes:
        """GET raw bytes from a Nitrado download URL (binary-safe)."""
        if time.monotonic() < _nitrado_cooldown_until:
            return b""
        try:
            resp = requests.get(
                url,
                params={"token": token},
                timeout=120,
            )
            if resp.status_code == 429:
                _mark_429(str(resp.status_code))
                return b""
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
        global _player_raw_logged
        if not _player_raw_logged:
            import json as _json
            print(f"[nitrado] RAW player list response: {_json.dumps(data, default=str)}", flush=True)
            _player_raw_logged = True
        players = data.get("players", [])
        return [
            {
                "name": p.get("name", "Unknown"),
                "id": p.get("id_num", p.get("unique_id", "0")),
                "ping": p.get("ping", 0),
                "online": bool(p.get("online", False)),
            }
            for p in players
        ]

    def _discover_game_slugs(self) -> list[str]:
        """List the game ids actually installed on this service (authoritative)."""
        code, body = self._raw("GET", f"/services/{self.service_id}/gameservers/games")
        if not isinstance(body, dict):
            return []
        inner = body.get("data", body)
        games = inner.get("games", []) if isinstance(inner, dict) else (inner if isinstance(inner, list) else [])
        candidates = []
        for g in games:
            if not isinstance(g, dict):
                continue
            for k in ("folder_short", "id", "game", "game_id", "folder", "short"):
                v = str(g.get(k) or "").strip()
                if v:
                    candidates.append(v)
        return list(dict.fromkeys(candidates))

    def _server_gs(self) -> dict:
        """Fetch (and cache) the gameserver object once per client.

        The /gameservers payload may be flat ({username, game, ...}) or nested
        under a 'gameserver'/'data' key; both are unwrapped here.""" 
        if self._gs_cached is None:
            info = self._request("GET", f"/services/{self.service_id}/gameservers")
            if isinstance(info, dict):
                inner = info
                while True:
                    nxt = None
                    for _k in ("gameserver", "data"):
                        _v = inner.get(_k)
                        if isinstance(_v, dict):
                            nxt = _v
                            break
                    if not isinstance(nxt, dict):
                        break
                    inner = nxt
                info = inner
            self._gs_cached = info if isinstance(info, dict) else {}
        return self._gs_cached

    def _log_file_candidates(self, filename: str) -> list[str]:
        """Deterministic candidate paths for an ARK log file.

        Nitrado file_server serves game files under the account/game root; the
        web Files tab shows `arkps/ShooterGame/...` but the API rejected that
        with 500, so we probe the full /games/<user>[/noftp] roots first. No
        list/recursive APIs — only a handful of cheap download attempts.
        """
        gs = self._server_gs() or {}
        game = str(gs.get("game") or self._game_short() or "arkps").strip("/").strip("\ufeff")
        user = str(gs.get("username") or "").strip()
        if not getattr(self, "_gs_status_printed", False):
            self._gs_status_printed = True
            print(f"[nitrado-gs] status={gs.get('status')} state={gs.get('status')} game={game!r} user={user!r}", flush=True)
            if isinstance(gs, dict):
                ftp_keys = sorted(k for k in gs.keys() if "ftp" in k.lower() or "sftp" in k.lower())
                if ftp_keys:
                    print(f"[nitrado-gs] ftp-related fields present: {ftp_keys}", flush=True)
        rel = f"ShooterGame/Saved/Logs/{filename}"
        game_rel = f"{game}/{rel}"
        cands: list[str] = []
        if user:
            cands += [
                f"/games/{user}/noftp/{game_rel}",
                f"/games/{user}/{game_rel}",
                f"/games/{user}/noftp/{rel}",
                f"/games/{user}/{rel}",
                f"/games/{user}/ftproot/{game_rel}",
                f"/games/{user}/ftproot/{rel}",
                f"noftp/{user}/{game_rel}",
                f"{user}/{game_rel}",
            ]
        cands += [
            f"/ftproot/{game_rel}",
            f"ftproot/{game_rel}",
            game_rel,
            rel,
        ]
        return list(dict.fromkeys(cands))

    def file_server_list(self, dir_path: str = "/", search: str = None) -> tuple[int, list]:
        """List entries under a server path via the Nitrado file server API.
        With ``search`` set, list becomes a recursive file search (the
        Nitrato SDK's doFileSearch). Returns (http_status, entries)."""
        params: dict = {"dir": dir_path}
        if search:
            params["search"] = search
        code, body = self._raw("GET", f"{self.fs_base()}/list", params=params)
        entries: list = []
        if isinstance(body, dict):
            inner = body.get("data", body)
            if isinstance(inner, dict):
                entries = inner.get("entries") or []
            elif isinstance(inner, list):
                entries = inner
        if not getattr(self, "_fs_list_printed", False):
            self._fs_list_printed = True
            if code != 200:
                snippet = ""
                if isinstance(body, dict):
                    snippet = str(body.get("_text") or body.get("message") or "")[:120]
                print(f"[nitrado-fs] file_server/list dir={dir_path!r} search={search!r} HTTP={code} {snippet!r} entries=?", flush=True)
            else:
                n = len(entries) if isinstance(entries, list) else "?"
                print(f"[nitrado-fs] file_server/list dir={dir_path!r} search={search!r} HTTP={code} entries={n}", flush=True)
        return code, entries

    def seek_tail(self, file: str, length: int = 1000000) -> str:
        """Read the tail of a server file with file_server/seek (offset=negative).
        Returns None while a rate-limit cooldown is active."""
        if time.monotonic() < _nitrado_cooldown_until:
            return None
        if not _begin_request():
            return None
        try:
            resp = requests.get(
                f"{NITRADO_BASE_URL}{self.fs_base()}/seek",
                params={"file": file, "offset": -length, "length": length, "mode": "raw"},
                headers=self.headers, timeout=20,
            )
        except requests.RequestException:
            return ""
        if resp.status_code == 429:
            _mark_429(str(resp.status_code))
            return ""
        if resp.status_code != 200:
            self._seek_broken[file] = time.time()  # skip seek for a while
            if not getattr(self, "_seek_printed", False):
                self._seek_printed = True
                print(f"[nitrado-fs] seek HTTP={resp.status_code} file={file!r} body={resp.text[:150]!r}", flush=True)
            return ""
        try:
            data = resp.json()
        except Exception:
            return ""
        token, url = self._extract_token_url(data)
        if not token or not url:
            return ""
        try:
            r = requests.get(url, params={"token": token}, timeout=40)
        except requests.RequestException:
            return ""
        if r.status_code == 429:
            _mark_429(str(r.status_code))
            return ""
        if r.status_code in (200, 206):
            return r.text[: 4 * length]
        print(f"[nitrado-fs] seek body HTTP={r.status_code} file={file!r}", flush=True)
        return ""

    def _search_log_path(self, filenames: tuple = ("ShooterGame.log", "ShooterGame_Last.log")) -> str:
        """Recursive file_server search for an ARK log (the list `search` param)."""
        gs = self._server_gs() or {}
        user = str(gs.get("username") or "").strip()
        bases = ["/", "Server", "arkps", "arkps/Server", "/games"]
        if user:
            bases += [f"/games/{user}", f"/games/{user}/ftproot", f"/games/{user}/Server",
                      f"/games/{user}/Server/ShooterGame/Saved/Logs"]
        for base in bases:
            for fname in filenames:
                code, entries = self.file_server_list(base, search=fname)
                if code != 200 or not isinstance(entries, list):
                    continue
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    if e.get("type") == "file" and str(e.get("name") or "") == fname:
                        path = str(e.get("path") or "")
                        if not path:
                            path = f"{base.rstrip('/')}/{fname}" if base.strip("/") else fname
                        self._fs_log_path = path
                        print(f"[nitrado-fs] SEARCH-FOUND {fname} under {base!r} => {path!r}", flush=True)
                        return path
        return ""

    def _discover_log_path(
        self,
        filenames: tuple = ("ShooterGame_Last.log", "ShooterGame.log"),
        max_dirs: int = 24,
    ) -> str:
        """Walk the file_server tree to locate an ARK log file.

        Tries a recursive ``list?search=`` lookup first, then probes the known
        root prefixes (including the relative ``Server`` / ``arkps`` aliases the
        web interface uses) and runs a breadth-first search under the first
        root that lists entries. Runs at most once per 10 minutes per client.
        """
        now = time.time()
        cached = getattr(self, "_fs_discover_ts", 0.0)
        if now - cached < 600:
            return getattr(self, "_fs_log_path", "") or ""
        self._fs_discover_ts = now
        found = self._search_log_path(filenames)
        if found:
            return found
        gs = self._server_gs() or {}
        user = str(gs.get("username") or "").strip()
        roots = ["/", "/games", "/ftproot", "Server", "arkps", "arkps/Server"]
        if user:
            roots += [f"/games/{user}", f"/games/{user}/ftproot", f"/{user}", f"/{user}/ftproot",
                      f"/games/{user}/Server", f"/games/{user}/arkps", "/games/{user}/Server/ShooterGame/Saved/Logs", f"arkps/ShooterGame/Saved/Logs"]
        seed = ""
        for r in roots:
            code, entries = self.file_server_list(r)
            n = len(entries) if isinstance(entries, list) else 0
            if code == 200:
                print(f"[nitrado-fs] root {r!r} HTTP=200 entries={n}", flush=True)
                if n and not seed:
                    seed = r.rstrip("/") or "/"
            else:
                print(f"[nitrado-fs] root {r!r} HTTP={code}", flush=True)
        if not seed:
            seed = "/"
            print("[nitrado-fs] all root probes empty — no file tree entries returned for this service", flush=True)
        if not seed:
            seed = "/"
            print("[nitrado-fs] all root probes empty — no file tree entries returned for this service", flush=True)
        queue = [seed]
        seen: set[str] = {seed}
        checked = 0
        try:
            while queue and checked < max_dirs:
                d = queue.pop(0)
                code, entries = self.file_server_list(d)
                if code != 200 or not isinstance(entries, list):
                    continue
                checked += 1
                for e in entries:
                    if not isinstance(e, dict):
                        continue
                    name = str(e.get("name") or "")
                    is_log = name in filenames or (name.startswith("ShooterGame") and name.endswith(".log"))
                    if e.get("type") == "file" and is_log:
                        path = str(e.get("path") or "")
                        if path:
                            self._fs_log_path = path
                            print(f"[nitrado-fs] DISCOVERED {name} => {path!r}", flush=True)
                            return path
                if checked >= max_dirs:
                    break
                for e in entries:
                    if isinstance(e, dict) and e.get("type") == "dir":
                        p = str(e.get("path") or "").rstrip("/") or "/"
                        if p not in seen:
                            seen.add(p)
                            queue.append(p)
        except Exception as ex:
            print(f"[nitrado-fs] file_server discovery error: {type(ex).__name__}: {ex}", flush=True)
        return ""

    def read_file_tail(self, file: str, tail_bytes: int = 1000000) -> str:
        """Read only the tail of a server file (last ~tail_bytes).

        Primary: file_server/seek with a negative offset (fast, no full
        download). Fallback: file download with a byte-range tail and trimming
        the full body locally if ranges are ignored. Returns None while a
        rate-limit cooldown is active (not a failure).
        """
        tail = ""
        if time.time() - self._seek_broken.get(file, 0) >= 300:
            tail = self.seek_tail(file, tail_bytes)
            if tail is None:
                return None
        if tail:
            return tail
        if time.monotonic() < _nitrado_cooldown_until:
            return None
        if not _begin_request():
            return None
        try:
            raw = requests.get(
                f"{NITRADO_BASE_URL}{self.fs_base()}/download",
                params={"file": file}, headers=self.headers, timeout=30,
            )
        except requests.RequestException:
            raw = None
        if raw is None:
            return ""
        if raw.status_code == 429:
            _mark_429(str(raw.status_code))
            return ""
        if raw.status_code != 200 or not raw.text.startswith("{"):
            if not getattr(self, "_dl_runtime_printed", False):
                self._dl_runtime_printed = True
                print(f"[nitrado-fs] download-list HTTP={raw.status_code} body={raw.text[:200]!r}", flush=True)
            else:
                print(f"[nitrado-fs] download-list HTTP={raw.status_code} file={file!r}", flush=True)
            return ""
        data = raw.json()
        token, url = self._extract_token_url(data)
        if not token or not url:
            return ""
        if time.monotonic() < _nitrado_cooldown_until:
            return ""
        try:
            resp = requests.get(url, params={"token": token}, headers={"Range": f"bytes=-{tail_bytes}"}, timeout=60)
        except requests.RequestException:
            return ""
        if resp.status_code == 429:
            _mark_429(str(resp.status_code))
            return ""
        if resp.status_code == 416:
            try:
                resp = requests.get(url, params={"token": token}, timeout=60)
            except requests.RequestException:
                return ""
        if resp.status_code in (200, 206):
            body = resp.text
            head = body.lstrip()[:32]
            if head and head.startswith(("<", "{")):
                if "just a moment" in head.lower() or "cloudflare" in head.lower():
                    _mark_429("Cloudflare challenge")
                return ""
            if len(body) > tail_bytes:
                body = body[-tail_bytes:]
            return body
        print(f"[nitrado-fs] download body HTTP={resp.status_code} file={file!r}", flush=True)
        return ""

    def _get_log_file_text(self, lines: int, tail_bytes: int = 1000000) -> str:
        now = time.time()
        backoff = 300  # seconds after a full probe round
        for filename in ("ShooterGame_Last.log", "ShooterGame.log"):
            last = self._log_fail_ts.get(filename)
            if last and now - last < backoff:
                continue
            paths = self._log_file_candidates(filename)
            if not getattr(self, "_log_cands_printed", False):
                self._log_cands_printed = True
                print(f"[nitrado-fs] probe-paths: {paths}", flush=True)
            idx = self._probe_next_idx.get(filename, 0)
            if idx >= len(paths):
                self._probe_next_idx[filename] = 0
                self._log_fail_ts[filename] = now
                print(f"[nitrado-fs] log file NOT found for {filename} ({len(paths)} paths)", flush=True)
                continue
            path = paths[idx]
            text = self.read_file_tail(path, tail_bytes)
            if text is None:
                return ""  # a cooldown is active — stay quiet this tick
            if text:
                self._probe_next_idx[filename] = 0
                self._log_fail_ts.pop(filename, None)
                print(f"[nitrado-fs] using log file path={path!r} chars={len(text)}", flush=True)
                return "\n".join(text.splitlines()[-lines:])
            # Failed this path — advance one step per tick to stay far below
            # Nitrado's rate limits (probing all paths at once re-tripped 429).
            self._probe_next_idx[filename] = idx + 1
            if idx + 1 >= len(paths):
                self._probe_next_idx[filename] = 0
                self._log_fail_ts[filename] = now
                print(f"[nitrado-fs] log file NOT found for {filename} ({len(paths)} paths)", flush=True)
            return ""
        return ""

    def _sftp_get_log_text(self, lines: int, tail_bytes: int = 3000000) -> str:
        """Read the ARK log tail over SFTP/FTP (used for PlayStation services,
        which Nitrado does not expose through the file/download API).

        Needs FTP/SFTP credentials configured in the dashboard Nitrado section
        (host + password; the user falls back to the gameserver FTP user).
        """
        if not getattr(self, "guild_id", None):
            return ""
        now = time.time()
        if self._sftp_fail_ts and now - self._sftp_fail_ts < 300:
            return ""
        try:
            import sftp_client
            cfg = sftp_client.get_sftp_config(self.guild_id)
        except Exception:
            return ""
        host = (cfg.get("host") or "").strip()
        password = (cfg.get("password") or "").strip()
        if not host or not password:
            if not getattr(self, "_sftp_creds_printed", False):
                self._sftp_creds_printed = True
                print(f"[nitrado-fs] sftp: FTP credentials NOT set for guild={self.guild_id} — add ftp_host/ftp_password in dashboard > Nitrado to read PS logs", flush=True)
            return ""
        gs = self._server_gs() or {}
        user = str(cfg.get("user") or gs.get("username") or "").strip()
        if not user:
            return ""
        sftp = sftp_client.SFTPClient(host, user, password, cfg.get("port") or 22)
        game = str(gs.get("game") or self._game_short() or "arkps").strip("/").strip("\ufeff").split("/")[0]
        for fname in ("ShooterGame_Last.log", "ShooterGame.log"):
            rel = f"ShooterGame/Saved/Logs/{fname}"
            guesses = []
            roots = [f"{game}", f"noftp/{game}", "noftp", f"/games/{user}/noftp/{game}",
                     f"/games/{user}/{game}", f"/games/{user}/noftp", f"/games/{user}"]
            for root in roots:
                base = root.rstrip("/")
                guess = f"/{base}/{rel}" if base else f"/{rel}"
                for variant in (guess, guess.lstrip("/")):
                    guesses.append(variant)
            guesses = list(dict.fromkeys(guesses))
            path, text = sftp.tail_first(guesses, tail_bytes)
            if not path:
                path = sftp.find_log_path(rel)
                if path:
                    _, text = sftp.tail_first([path], tail_bytes)
            if text:
                self._sftp_fail_ts = 0.0
                print(f"[nitrado-fs] sftp using log path={path!r} chars={len(text)}", flush=True)
                return "\n".join(text.splitlines()[-lines:])
        self._sftp_fail_ts = now
        print(f"[nitrado-fs] sftp: no log found for {user}@{host} (guesses + tree walk) — check ftp details in dashboard", flush=True)
        return ""

    def get_logs(self, lines: int = 200) -> str:
        """Get the last N lines of the server log.

        Preferred: read the live ARK log file (ShooterGame_Last.log) tail via the
        Nitrado file server. Fallback: REST latest_log endpoint per game slug.
        """
        gs = self._server_gs() or {}
        if str(gs.get("status") or "").lower() == "suspended":
            if not getattr(self, "_susp_printed", False):
                self._susp_printed = True
                print(f"[nitrado-gs] WARN service {self.service_id} is SUSPENDED — skipping log fetch (path format is fine)", flush=True)
            return ""
        text = self._get_log_file_text(lines)
        if text:
            return text
        # Discover the real filesystem path (root may be /games/<user>/ftproot)
        # instead of guessing — one BFS every 10 minutes, then direct reads.
        path = self._discover_log_path()
        if path:
            text = self.read_file_tail(path)
            if text:
                print(f"[nitrado-fs] using log file path={path!r} chars={len(text)}", flush=True)
                return "\n".join(text.splitlines()[-lines:])
        # The latest_log endpoint is not available for every game (PlayStation
        # services expose no file interface at all). Trying every game slug
        # fired hundreds of pointless 404 requests per tick — restrict the
        # fallback to the resolved game + ARK-family slugs only.
        candidates: list[str] = []
        try:
            real = self._game_short()
            if real and real not in candidates:
                candidates.append(real)
        except Exception:
            pass
        for slug in ("arkse", "arkps4", "arksa", "arkxb", "arkps", "ark", "asa"):
            if slug not in candidates:
                candidates.append(slug)
        if not getattr(self, "_log_slugs_printed", False):
            self._log_slugs_printed = True
            print(f"[nitrado] log candidate slugs: {candidates} (ARK-family only)", flush=True)
        for slug in candidates:
            data = self._request("GET", f"/services/{self.service_id}/gameservers/games/{slug}/latest_log")
            content = data.get("content", "") if isinstance(data, dict) else ""
            if content:
                return "\n".join(content.split("\n")[-lines:])
        text = self._sftp_get_log_text(lines)
        if text:
            return text
        gs = self._server_gs() or {}
        game = str(gs.get("game") or "").lower()
        if ("ps4" in game or "ps5" in game or game == "arkps") and not getattr(self, "_ps_hint_printed", False):
            self._ps_hint_printed = True
            print(f"[nitrado-fs] HINT game={game!r} is a PLAYSTATION service: Nitrado exposes no API file interface for PS servers (download + latest_log empty) — route log reading through SFTP/FTP (set ftp_host/ftp_user/ftp_password in the dashboard)", flush=True)
        now = time.time()
        if not getattr(self, "_log_empty_printed", False) or now - self._log_empty_printed >= 60:
            self._log_empty_printed = now
            print(f"[nitrado] get_logs EMPTY for file paths + ARK latest_log slugs", flush=True)
        return ""

    def restart_server(self) -> bool:
        """Restart the ARK server."""
        result = self._request("POST", f"/services/{self.service_id}/gameservers/restart")
        return bool(result)

    def stop_server(self) -> bool:
        """Stop the ARK server."""
        result = self._request("POST", f"/services/{self.service_id}/gameservers/stop")
        return bool(result)

    def start_server(self) -> bool:
        """Start the ARK server (game-start endpoint requires the Folder Short id)."""
        result = self._request(
            "POST",
            f"/services/{self.service_id}/gameservers/games/start",
            params={"game": self._game_short()},
        )
        return bool(result)

    def _game_short(self) -> str:
        """Resolve the game's Folder Short id (e.g. 'arkps4'/'arkxb') used by
        the Nitrado game-start endpoint, fetched from the gameserver object."""
        if getattr(self, "_game_short_cached", None):
            return self._game_short_cached
        short = ""
        try:
            info = self._server_gs()
            inner = info.get("data", info) if isinstance(info, dict) else {}
            gs = inner.get("gameserver", inner) if isinstance(inner, dict) else {}
            for k in ("folder_short", "folder", "game", "game_short"):
                if isinstance(gs, dict) and gs.get(k):
                    short = str(gs[k])
                    break
            if not short and isinstance(info, dict):
                for k in ("folder_short", "folder", "game", "game_short"):
                    if info.get(k):
                        short = str(info[k])
                        break
            if not short:
                raw_game = (gs.get("game") if isinstance(gs, dict) else "") or ""
                gl = str(raw_game).lower()
                if "ps4" in gl or "ps5" in gl:
                    short = "arkps4"
                elif "ascended" in gl or "asa" in gl:
                    short = "arksa"
                elif "xbox" in gl:
                    short = "arkxb"
                elif "survival" in gl:
                    short = "arkse"
                else:
                    short = "arkps4"
            print(f"[nitrado] game short resolved: {short!r}", flush=True)
        except Exception as e:
            print(f"[nitrado] game short error: {type(e).__name__}: {e}", flush=True)
            short = "arkps4"
        self._game_short_cached = short
        return short

    def get_game_short(self) -> str:
        """Public helper: get the resolved game Folder Short id."""
        return self._game_short()

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

    def get_settings(self) -> dict:
        """Read current server settings from Nitrado (GET settings)."""
        data = self._request(
            "GET",
            f"/services/{self.service_id}/gameservers/settings",
        )
        if not isinstance(data, dict):
            return {}
        inner = data.get("settings", data)
        return inner if isinstance(inner, dict) else {}

    def get_ark_settings(self) -> dict:
        """Flatten the Nitrado GET settings response into a dict of ARK-relevant
        values (map, multipliers, server name, passwords). Nitrado returns the
        ARK ini config organised by category; we walk every category and pick
        the keys the dashboard displays."""
        settings = {}
        try:
            raw = self._request(
                "GET",
                f"/services/{self.service_id}/gameservers/settings",
            )
            if not isinstance(raw, dict):
                raw = {}
            inner = raw.get("settings", raw)
            if not isinstance(inner, dict):
                inner = {}
            if not getattr(self, "_settings_diag_logged", False):
                import json as _json
                try:
                    print(f"[nitrado-settings] TOP keys: {list(inner.keys())}", flush=True)
                    print(f"[nitrado-settings] FULL: {_json.dumps(inner, default=str)[:4000]}", flush=True)
                except Exception:
                    pass
                self._settings_diag_logged = True

            def _is_meta(_v):
                return isinstance(_v, dict) and set(_v.keys()) <= {"value", "current", "current_value", "type", "min", "max", "step", "default", "unit", "description", "readonly", "name", "options"}

            def _walk(_node):
                if not isinstance(_node, dict):
                    return
                for _k, _v in _node.items():
                    if isinstance(_v, list):
                        for _item in _v:
                            if isinstance(_item, dict):
                                _walk(_item)
                        continue
                    if isinstance(_v, dict):
                        if _is_meta(_v):
                            _scalar = _v.get("value", _v.get("current", _v.get("current_value")))
                            if _scalar is not None:
                                settings.setdefault(str(_k), _scalar)
                        else:
                            _walk(_v)
                    else:
                        settings.setdefault(str(_k), _v)

            _walk(inner)
        except Exception as e:
            print(f"[nitrado-settings] error: {type(e).__name__}: {e}", flush=True)
        return settings


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
        token, url = self._extract_token_url(data)
        if not token or not url:
            return False
        return self._post_binary(url, token, content)

    def read_file(self, file: str) -> str:
        """Read a file's content from the server."""
        if not _begin_request():
            return ""
        raw = requests.get(f"{NITRADO_BASE_URL}{self.fs_base()}/download", params={"file": file}, headers=self.headers, timeout=30)
        if raw.status_code == 429:
            _mark_429(str(raw.status_code))
            return ""
        print(f"[nitrado-fs] download?file={file!r} HTTP={raw.status_code} text={raw.text[:300]!r}")
        data = raw.json() if raw.text.startswith("{") else {}
        token, url = self._extract_token_url(data)
        if not token or not url:
            return ""
        return self._get_binary(url, token)

    def base_roots(self) -> list[str]:
        """Candidate server-root prefixes used to resolve relative paths."""
        roots = [""]
        info = {}
        try:
            info = self._request("GET", f"/services/{self.service_id}/gameservers")
            if not isinstance(info, dict):
                info = {}
        except Exception as e:
            print(f"[nitrado-fs] gameservers info error: {type(e).__name__}: {e}")
        gs = info.get("gameserver") if isinstance(info, dict) else None
        if not isinstance(gs, dict):
            gs = {}
        print(f"[nitrado-fs] gameserver keys: {list(gs.keys())[:60]}")
        for k in ("folder_short", "folder", "game", "username", "base_path", "path", "home_path", "root", "server_username"):
            print(f"[nitrado-fs] gs.{k}={gs.get(k)!r}")
        fs = (
            gs.get("folder_short")
            or gs.get("folder")
            or gs.get("game")
            or info.get("folder_short")
            or info.get("folder")
            or info.get("game")
            or ""
        )
        uname = gs.get("username") or info.get("username") or gs.get("server_username") or ""
        base_path = gs.get("base_path") or gs.get("path") or gs.get("home_path") or gs.get("root") or ""
        if base_path:
            roots.append(base_path)
            roots.append(base_path.rstrip("/") + "/ShooterGame")
        if fs:
            roots.append(fs)
            if uname:
                roots.append("/games/{0}/{1}".format(uname, fs))
                roots.append("/games/{0}/noftp/{1}".format(uname, fs))
            else:
                roots.append("/games/xxx/" + fs)
        if uname:
            roots.append("/games/{0}/noftp".format(uname))
            roots.append("/games/{0}/ftproot".format(uname))
        if not fs:
            for g in ("arkps4", "arkxb", "arkse", "arksa", "ark"):
                roots.append(g)
        roots = [r for r in roots if r]
        print(f"[nitrado-fs] candidate roots: {roots}")
        return roots

    def find_file_tree(self, start: str, filename: str, max_depth: int = 5) -> str:
        """Recursively search the server's file tree for a file by name.
        Returns the full path (as used by download) or '' if not found."""
        filename_l = filename.lower()

        def _search(dir_val, depth):
            try:
                entries = self.list_file_entries(dir_val) or []
            except Exception:
                return None
            dir_val = (dir_val or "").strip("/")
            for e in entries:
                name = e.get("name") or ""
                if not name:
                    continue
                p = (dir_val + "/" + name) if dir_val else name
                if e.get("type") == "dir" or not e.get("type"):
                    if name.lower() == filename_l:
                        return p
                    if depth < max_depth:
                        found = _search(p, depth + 1)
                        if found:
                            return found
                elif name.lower() == filename_l:
                    return p
            return None

        for root in self.base_roots():
            r = (root or "").strip("/")
            found = _search(r or None, 0)
            if found:
                return "/" + found.lstrip("/")
        return ""

    def list_file_entries(self, directory: str) -> list[dict]:
        directory = (directory or "").strip()
        base = directory.lstrip("/")

        def variant(dir_val):
            try:
                return self._fs_list(dir_val)
            except Exception as e:
                print(f"[nitrado-fs] list error dir={dir_val!r}: {type(e).__name__}: {e}")
                return None

        # Direct absolute path (e.g. already a /games/.../noftp/... path we built).
        if directory.startswith("/games/"):
            e = variant(directory)
            if e:
                return e

        forms = [base, "/" + base] if base else []
        for f in forms:
            e = variant(f)
            if e:
                return e

        roots = self.base_roots()
        for root in roots:
            cand = root.rstrip("/") + ("/" + base if base else "")
            e = variant(cand)
            if e:
                return e

        last = None
        for root in roots:
            cand = root.rstrip("/") + ("/" + base if base else "")
            e = variant(cand)
            if e is not None:
                last = e
                break
            if not base:
                e = variant(root.rstrip("/") + "/")
                if e is not None:
                    last = e
                    break
        if last is None:
            raise RuntimeError("nitrado file list returned no readable directory")
        return last

    def _fs_list(self, directory: str) -> list[dict]:
        if not _begin_request():
            raise RuntimeError("Nitrado list error: HTTP 429 (throttled)")
        url = f"{NITRADO_BASE_URL}{self.fs_base()}/list"
        resp = requests.get(url, params={"dir": directory}, headers=self.headers, timeout=30)
        if resp.status_code == 429:
            _mark_429(str(resp.status_code))
            raise RuntimeError(f"Nitrado list error: HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise RuntimeError(f"Nitrado list error: HTTP {resp.status_code}")
        raw = resp.json()
        data = raw.get("data", {})
        if not isinstance(data, dict):
            raw_text = resp.text[:500]
            print(f"[nitrado-fs] _fs_list dir={directory!r} HTTP={resp.status_code} raw_top={list(raw.keys())} data_not_dict raw={raw_text}")
            raise RuntimeError("Nitrado list returned an unexpected response")
        entries = data.get("entries", [])
        if not entries:
            print(f"[nitrado-fs] _fs_list dir={directory!r} HTTP={resp.status_code} data_keys={list(data.keys())} entries=EMPTY raw_top={list(raw.keys())} raw_tail={resp.text[-250:]}")
        else:
            names = [e.get("name") for e in entries if isinstance(e, dict)]
            print(f"[nitrado-fs] _fs_list dir={directory!r} HTTP={resp.status_code} entries_count={len(entries)} names={names}")
        out = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            child_path = directory.rstrip("/") + "/" + (e.get("name") or "")
            out.append(
                {
                    "name": e.get("name"),
                    "size": e.get("size") or 0,
                    "type": e.get("type"),
                    "path": child_path,
                }
            )
        return out

    def download_file_bytes(self, file: str) -> bytes:
        """Download a file as raw bytes (binary-safe). Returns b'' on failure."""
        if not _begin_request():
            return b""
        raw = requests.get(f"{NITRADO_BASE_URL}{self.fs_base()}/download", params={"file": file}, headers=self.headers, timeout=30)
        if raw.status_code == 429:
            _mark_429(str(raw.status_code))
            return b""
        print(f"[nitrado-fs] download_bytes?file={file!r} HTTP={raw.status_code} text={raw.text[:200]!r}")
        data = raw.json() if raw.text.startswith("{") else {}
        token, url = self._extract_token_url(data)
        if not token or not url:
            return b""
        return self._get_bytes(url, token)

    def upload_file_bytes(self, path: str, filename: str, data: bytes) -> bool:
        """Upload a binary file to `path` on the server using multipart form-data."""
        url = f"{NITRADO_BASE_URL}{self.fs_base()}/upload"
        try:
            resp = requests.post(
                url,
                params={"path": path},
                files={"file": (filename, data)},
                headers=self.headers,
                timeout=180,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Nitrado binary upload error: {type(e).__name__}")
            return False

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


_heal_cache: dict[int, float] = {}
_HEAL_TTL = 300.0
_HEAL_BAD_STATUS = {"suspended", "decommissioned", "deleted", "closed"}


def _extract_gameserver_status(code, body) -> str:
    """Pull the gameserver status string out of a /gameservers response."""
    if code != 200 or not isinstance(body, dict):
        return ""
    inner = body.get("data", body)
    while isinstance(inner, dict):
        gs = inner.get("gameserver")
        if isinstance(gs, dict):
            inner = gs
        nxt = inner.get("data")
        if isinstance(nxt, dict) and not isinstance(gs, dict):
            inner = nxt
            continue
        break
    return str(inner.get("status") or "").lower()


def _ark_services_for_token(token: str, max_probes: int = 12) -> list[dict]:
    """Scan a Nitrado token's services for ARK gameservers (no guild context).

    Safe to call from get_client's self-heal path (no recursion).
    """
    if not token:
        return []
    probe = NitradoClient(token, "")
    ark_slugs = {"arkse", "arkps4", "arksa", "arkxb", "ark", "asa", "ase"}
    results = []
    try:
        services = probe.list_services()
    except Exception:
        return results
    for svc in services:
        if not isinstance(svc, dict) or len(results) >= max_probes:
            continue
        sid = str(svc.get("id") or "").strip()
        name = str(svc.get("name") or svc.get("game_name") or "").strip()
        game = str(svc.get("game") or svc.get("game_id") or "").strip()
        if not sid:
            continue
        low = game.lower()
        is_ark = (not game) or "ark" in low or low in ark_slugs
        if not is_ark:
            continue
        code, body = probe._raw("GET", f"/services/{sid}/gameservers")
        status = _extract_gameserver_status(code, body)
        ok = code == 200 and status not in ("suspended", "stopped", "decommissioned") and status != ""
        results.append({
            "service_id": sid,
            "name": name,
            "game": game,
            "status": status,
            "ok": ok,
            "code": code,
        })
    return results


def get_client(guild_id: int) -> NitradoClient | None:
    """Get a Nitrado client for a guild. Returns None if not configured.

    Self-heals: at most once every 5 minutes it re-checks the active service's
    gameserver status; if the service is suspended/decommissioned or the
    endpoint is erroring, it promotes a healthy ARK service under the same
    token and persists the choice, so every feature keeps working.
    """
    config = guild_settings.get_nitrado_config(guild_id)
    token = config.get("api_token")
    service_id = config.get("service_id")
    if not token or not service_id:
        return None
    now = time.time()
    last = _heal_cache.get(guild_id, 0.0)
    if now - last >= _HEAL_TTL:
        _heal_cache[guild_id] = now
        code, body = None, None
        try:
            probe = NitradoClient(token, service_id)
            code, body = probe._raw("GET", f"/services/{service_id}/gameservers")
        except Exception:
            code = None
        status = _extract_gameserver_status(code, body)
        unhealthy = bool(code and 400 <= code < 429) or status in _HEAL_BAD_STATUS
        if unhealthy:
            healthy = [s for s in _ark_services_for_token(token) if s.get("ok")]
            h = next((s for s in healthy if s), None)
            if h and str(h["service_id"]) != str(service_id):
                if guild_settings.promote_nitrado_service(guild_id, str(h["service_id"])):
                    print(f"[nitrado] guild={guild_id} auto-promoted service {service_id} -> {h['service_id']} (status={h.get('status') or '?'})", flush=True)
                    service_id = str(h["service_id"])
            elif not healthy:
                print(f"[nitrado] guild={guild_id} active service {service_id} unhealthy; no healthy ARK service under this token", flush=True)
    client = NitradoClient(token, service_id)
    client.guild_id = guild_id
    return client


def find_ark_services(guild_id: int) -> list[dict]:
    """Scan the token's Nitrado services and find the ARK gameserver.

    Probes /services/{id}/gameservers for every service that looks ARK-like
    and reports which ones actually respond (ok=True). The configured token
    must have access to the services list.
    """
    config = guild_settings.get_nitrado_config(guild_id)
    token = config.get("api_token")
    if not token:
        return []
    return _ark_services_for_token(token)


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


def get_ark_settings(guild_id: int) -> dict:
    """Flatten Nitrado settings for a guild into ARK-relevant values."""
    client = get_client(guild_id)
    if not client:
        return {}
    return client.get_ark_settings()


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
    tried = [
        "ShooterGame/Saved/Config/GameUserSettings.ini",
        "ShooterGame/Saved/Config/LinuxServer/GameUserSettings.ini",
    ]
    for path in tried:
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


def get_server_passwords(guild_id: int) -> dict:
    """Read the current admin and server (join) passwords.

    Sources in order: gameserver info (admin_password/server_password),
    Nitrado settings API, then GameUserSettings.ini via file server.

    Returns {"admin": str, "server": str}. Empty string means unset/not found.
    """
    client = get_client(guild_id)
    if not client:
        return {"admin": "", "server": ""}

    def _first(*sources):
        for s in sources:
            if s:
                return s
        return ""

    # 1) gameserver info: admin/server passwords live under the "settings" object
    #    (ARK [ServerSettings]) and sometimes "credentials".
    try:
        info = client.get_server_status()
        inner = info.get("data", info) if isinstance(info, dict) else {}
        gs = inner.get("gameserver", inner) if isinstance(inner, dict) else {}

        def _collect_pass(ref, into):
            if not isinstance(ref, dict):
                return
            for k, v in ref.items():
                key = str(k).lower().replace("-", "_")
                if isinstance(v, dict):
                    _collect_pass(v, into)
                    continue
                if not into["admin"] and key in ("adminpassword", "serveradminpassword", "admin_password", "current_admin_password") and v:
                    into["admin"] = str(v)
                elif not into["server"] and key in ("serverpassword", "server_password") and v:
                    into["server"] = str(v)

        found = {"admin": "", "server": ""}
        if isinstance(gs, dict):
            for sect in ("settings", "credentials", "game_specific"):
                _collect_pass(gs.get(sect), found)
            if not getattr(client, "_pw_diag_logged", False):
                import json as _json
                def _skim(v):
                    if isinstance(v, dict):
                        return {k: _skim(x) for k, x in list(v.items())[:40]}
                    return f"{type(v).__name__}:{str(v)[:60]}"
                print(f"[nitrado-pw] gameserver keys: {list(gs.keys())}", flush=True)
                for s in ("settings", "credentials", "game_specific"):
                    if isinstance(gs.get(s), dict):
                        print(f"[nitrado-pw] {s} skim: {_json.dumps(_skim(gs.get(s)), default=str)[:1200]}", flush=True)
                client._pw_diag_logged = True
            if found["admin"] or found["server"]:
                return found
    except Exception:
        pass

    # 2) Nitrado settings API
    try:
        settings = client.get_settings()
        admin = ""
        server = ""
        for section in settings.values():
            if not isinstance(section, dict):
                continue
            for k, v in section.items():
                key = str(k).lower()
                if not admin and key in ("adminpassword", "serveradminpassword"):
                    admin = str(v or "")
                elif not server and key == "serverpassword":
                    server = str(v or "")
        if admin or server:
            return {"admin": admin, "server": server}
    except Exception:
        pass

    # 3) GameUserSettings.ini via file server
    for path in [
        "ShooterGame/Saved/Config/GameUserSettings.ini",
        "ShooterGame/Saved/Config/LinuxServer/GameUserSettings.ini",
    ]:
        try:
            content = client.read_file(path)
            if not content:
                continue
            admin = ""
            server = ""
            for line in content.splitlines():
                line = line.strip()
                low = line.lower()
                if not admin and (low.startswith("adminpassword=") or low.startswith("serveradminpassword=")):
                    admin = line.split("=", 1)[1].strip().strip('"')
                if not server and low.startswith("serverpassword="):
                    server = line.split("=", 1)[1].strip().strip('"')
            return {"admin": admin, "server": server}
        except Exception:
            continue
    return {"admin": "", "server": ""}


_server_name_cache: dict[int, tuple[float, str]] = {}


def server_name(guild_id: int) -> str:
    """Best-effort 'real' ARK server name: GameUserSettings.ini first, then API info.

    Cached per guild so per-page renders don't hit the file server repeatedly.
    """
    now = time.time()
    cached = _server_name_cache.get(guild_id)
    if cached and now - cached[0] < 300:
        return cached[1]
    name = get_ark_server_name(guild_id)
    if not name:
        try:
            info = get_server_info(guild_id) or {}
            inner = info.get("gameserver", info) if isinstance(info, dict) else {}
            name = str(inner.get("name") or inner.get("server_name") or "") if isinstance(inner, dict) else ""
        except Exception:
            name = ""
    _server_name_cache[guild_id] = (time.time(), name)
    return name


def _game_api_result(client, method: str, action: str, name: str) -> str:
    """Call the Nitrado game whitelist/banlist endpoint (the API route that
    works for PlayStation servers, unlike the app_server console).

    Whitelist:   POST   .../games/whitelist?identifier=<psn>
    Ban/Unban:   POST/DELETE .../games/banlist?identifier=<psn>
    """
    code, body = client._raw(
        method,
        f"/services/{client.service_id}/gameservers/games/{action}",
        params={"identifier": name},
    )
    if code == 429 or (isinstance(body, dict) and body.get("throttled")):
        return "Rate limited, try again shortly"
    status = str(body.get("status", "")) if isinstance(body, dict) else ""
    msg = str(body.get("message", "")) if isinstance(body, dict) else ""
    if status == "success":
        return "OK"
    already = action == "whitelist" and msg == "Can't add the user to the whitelist."
    if already:
        return "OK"
    if msg == "User could not be found.":
        return "Player not found"
    return f"Failed{(': ' + msg) if msg else (f' (HTTP {code})' if code != 200 else '')}"


def ban_player(guild_id: int, name: str) -> str:
    """Ban a player on the Nitrado server. Uses the game banlist API (works on
    PlayStation), falling back to the console command when it's unavailable."""
    client = get_client(guild_id)
    if not client:
        return "Nitrado not configured"
    result = _game_api_result(client, "POST", "banlist", name)
    if result == "OK":
        return "Banned"
    try:
        client.send_command(f"Ban {name}")
        return "Banned"
    except Exception as e:
        return result if result != "Failed" else "Failed: " + type(e).__name__


def unban_player(guild_id: int, name: str) -> str:
    """Unban a player on the Nitrado server via the game banlist API."""
    client = get_client(guild_id)
    if not client:
        return "Nitrado not configured"
    result = _game_api_result(client, "DELETE", "banlist", name)
    if result == "OK":
        return "Unbanned"
    try:
        client.send_command(f"Unban {name}")
        return "Unbanned"
    except Exception as e:
        return result if result != "Failed" else "Failed: " + type(e).__name__


def whitelist_player(guild_id: int, name: str) -> str:
    """Add a player to the Nitrado whitelist via the game whitelist API
    (the route that works for PlayStation services). Returns a status message."""
    client = get_client(guild_id)
    if not client:
        return "Nitrado not configured"
    result = _game_api_result(client, "POST", "whitelist", name)
    if result == "OK":
        return "Whitelisted"
    return result

