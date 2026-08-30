import os
import json
import hmac
import hashlib
import time
import secrets
import string
from datetime import datetime, timezone

import psycopg2
from cryptography.fernet import Fernet


DATABASE_URL = os.getenv("DATABASE_URL")
_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
_fernet = Fernet(_ENCRYPTION_KEY.encode()) if _ENCRYPTION_KEY else None

# Secret used to sign license keys. If not set, falls back to ENCRYPTION_KEY.
_LICENSE_SIGN_KEY = (os.getenv("LICENSE_SIGN_KEY", "") or _ENCRYPTION_KEY).encode()

ENCRYPTED_FIELDS = {"nitrado_api_token", "ftp_password"}


def _encrypt(value: str) -> str:
    if not _fernet or not value:
        return value
    return "enc:" + _fernet.encrypt(value.encode()).decode()


def _decrypt(value: str) -> str:
    if not value or not value.startswith("enc:"):
        return value
    if not _fernet:
        return value
    return _fernet.decrypt(value[4:].encode()).decode()


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id    BIGINT PRIMARY KEY,
                    settings    JSONB NOT NULL DEFAULT '{}'::jsonb
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS embed_templates (
                    embed_id    TEXT PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    template    JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shop_dinos (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    name        TEXT NOT NULL,
                    blueprint   TEXT NOT NULL,
                    min_level   INTEGER DEFAULT 1,
                    max_level   INTEGER DEFAULT 150,
                    price       INTEGER DEFAULT 0,
                    category    TEXT DEFAULT 'General'
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_points (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    tribe_name  TEXT NOT NULL,
                    points      INTEGER DEFAULT 0,
                    last_update TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE (guild_id, tribe_name)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS leaderboard_config (
                    guild_id                BIGINT PRIMARY KEY,
                    announcement_channel_id BIGINT,
                    announcement_message    TEXT,
                    update_interval         INTEGER DEFAULT 5,
                    last_update             TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS linked_players (
                    guild_id    BIGINT NOT NULL,
                    discord_id  BIGINT NOT NULL,
                    psn_id      TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    linked_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (guild_id, discord_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS restart_schedule (
                    guild_id        BIGINT PRIMARY KEY,
                    restart_hour    INTEGER DEFAULT 3,
                    restart_minute  INTEGER DEFAULT 0,
                    last_run_date   DATE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_log_config (
                    guild_id            BIGINT PRIMARY KEY,
                    enabled             BOOLEAN DEFAULT FALSE,
                    channel_id          BIGINT,
                    log_source          TEXT DEFAULT 'file',
                    log_path            TEXT DEFAULT '',
                    nitrado_token       TEXT DEFAULT '',
                    nitrado_user_id     TEXT DEFAULT '',
                    nitrado_service_id  TEXT DEFAULT ''
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS known_tribes (
                    guild_id    BIGINT NOT NULL,
                    tribe_name  TEXT NOT NULL,
                    tribe_game_id TEXT DEFAULT '',
                    PRIMARY KEY (guild_id, tribe_name)
                )
            """)
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
            cur.execute("""
                CREATE TABLE IF NOT EXISTS player_warnings (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    player_name TEXT NOT NULL,
                    player_id   TEXT,
                    reason      TEXT NOT NULL,
                    warned_by   BIGINT NOT NULL,
                    warned_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    expires_at  TIMESTAMP WITH TIME ZONE,
                    active      BOOLEAN DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS player_punishments (
                    id              SERIAL PRIMARY KEY,
                    guild_id        BIGINT NOT NULL,
                    player_name     TEXT NOT NULL,
                    player_id       TEXT,
                    tribe_name      TEXT,
                    punishment_type TEXT NOT NULL,
                    reason          TEXT NOT NULL,
                    issued_by       BIGINT NOT NULL,
                    scope           TEXT DEFAULT 'player',
                    issued_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    expires_at      TIMESTAMP WITH TIME ZONE,
                    executed        BOOLEAN DEFAULT FALSE,
                    appealed        BOOLEAN DEFAULT FALSE,
                    appeal_reason   TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS punishment_evidence (
                    id              SERIAL PRIMARY KEY,
                    punishment_id   INTEGER REFERENCES player_punishments(id) ON DELETE CASCADE,
                    guild_id        BIGINT NOT NULL,
                    filename        TEXT NOT NULL,
                    original_name   TEXT NOT NULL,
                    file_size       INTEGER,
                    uploaded_by     BIGINT NOT NULL,
                    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_members (
                    guild_id    BIGINT NOT NULL,
                    tribe_name  TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    player_id   TEXT,
                    joined_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (guild_id, tribe_name, player_name)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_logs (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    log_type    TEXT NOT NULL,
                    sub_type    TEXT,
                    user_id     BIGINT,
                    user_name   TEXT,
                    player_name TEXT,
                    command     TEXT,
                    details     JSONB,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            cur.execute("ALTER TABLE bot_logs ADD COLUMN IF NOT EXISTS log_category TEXT")
            cur.execute("ALTER TABLE bot_logs ADD COLUMN IF NOT EXISTS posted_forum BOOLEAN DEFAULT FALSE")
            cur.execute("ALTER TABLE bot_logs ADD COLUMN IF NOT EXISTS posted_shop_forum BOOLEAN DEFAULT FALSE")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS player_whitelist (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    player_name TEXT NOT NULL,
                    player_id   TEXT,
                    reason      TEXT,
                    issued_by   BIGINT NOT NULL,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    expires_at  TIMESTAMP WITH TIME ZONE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS player_playtime (
                    guild_id    BIGINT NOT NULL,
                    player_id   TEXT NOT NULL,
                    player_name TEXT NOT NULL,
                    seconds     BIGINT DEFAULT 0,
                    last_seen   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (guild_id, player_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS pending_actions (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    action      TEXT NOT NULL,
                    payload     JSONB,
                    status      TEXT DEFAULT 'pending',
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_logs_guild ON bot_logs(guild_id, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_logs_type ON bot_logs(guild_id, log_type, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_warnings_player ON player_warnings(guild_id, player_name, active)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_punishments_player ON player_punishments(guild_id, player_name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_pending_actions ON pending_actions(guild_id, status)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS command_permissions (
                    guild_id    BIGINT NOT NULL,
                    command     TEXT NOT NULL,
                    role_id     BIGINT NOT NULL,
                    PRIMARY KEY (guild_id, command, role_id)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cmd_perms ON command_permissions(guild_id, command)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS automod_custom_words (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    word        TEXT NOT NULL,
                    added_by    BIGINT,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE (guild_id, word)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_automod_words ON automod_custom_words(guild_id)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS content_overrides (
                    content_key TEXT NOT NULL,
                    lang        TEXT NOT NULL,
                    value       TEXT NOT NULL,
                    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    PRIMARY KEY (content_key, lang)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS custom_commands (
                    id             SERIAL PRIMARY KEY,
                    guild_id       BIGINT NOT NULL,
                    name           TEXT NOT NULL,
                    command_string TEXT NOT NULL,
                    category       TEXT DEFAULT 'dino_spawn',
                    enabled        BOOLEAN DEFAULT TRUE,
                    created_by     BIGINT,
                    created_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE (guild_id, name)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS forum_log_config (
                    guild_id       BIGINT PRIMARY KEY,
                    forum_id       BIGINT,
                    thread_dino    BIGINT,
                    thread_gfi     BIGINT,
                    thread_player  BIGINT,
                    thread_gcm     BIGINT,
                    created_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS shop_forum_config (
                    guild_id       BIGINT PRIMARY KEY,
                    forum_id       BIGINT,
                    thread_done    BIGINT,
                    thread_pending BIGINT,
                    created_at     TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_forum_config (
                    guild_id   BIGINT PRIMARY KEY,
                    forum_id   BIGINT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_forum_threads (
                    guild_id   BIGINT NOT NULL,
                    tribe_name TEXT NOT NULL,
                    thread_id  BIGINT NOT NULL,
                    PRIMARY KEY (guild_id, tribe_name)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_log_events (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    tribe_name  TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    posted_forum BOOLEAN DEFAULT FALSE
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tribe_events ON tribe_log_events(guild_id, tribe_name, created_at DESC)")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS nitrado_services (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    name        TEXT NOT NULL,
                    service_id  TEXT NOT NULL DEFAULT '',
                    api_token   TEXT NOT NULL DEFAULT '',
                    ftp_host    TEXT DEFAULT '',
                    ftp_port    TEXT DEFAULT '22',
                    ftp_user    TEXT DEFAULT '',
                    ftp_password TEXT DEFAULT '',
                    is_active   BOOLEAN DEFAULT FALSE,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    UNIQUE (guild_id, name)
                )
            """)
            cur.execute("CREATE INDEX IF NOT EXISTS idx_nitrado_services_guild ON nitrado_services(guild_id)")
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  KEY-VALUE HELPERS
# ============================================================

def get_settings(guild_id: int) -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT settings FROM guild_settings WHERE guild_id = %s", (guild_id,))
            row = cur.fetchone()
            if row is None:
                return {}
            raw = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            decrypted = {}
            for k, v in raw.items():
                if k in ENCRYPTED_FIELDS and isinstance(v, str):
                    decrypted[k] = _decrypt(v)
                else:
                    decrypted[k] = v
            return decrypted
    finally:
        conn.close()


def get_setting(guild_id: int, key: str, default=None):
    value = get_settings(guild_id).get(key, default)
    if key in ENCRYPTED_FIELDS and isinstance(value, str):
        return _decrypt(value)
    return value


def get_bool_setting(guild_id: int, key: str, default: bool = False) -> bool:
    value = get_settings(guild_id).get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes", "on")
    return bool(value)


def update_setting(guild_id: int, key: str, value):
    if key in ENCRYPTED_FIELDS and isinstance(value, str) and value:
        value = _encrypt(value)
    settings = get_settings(guild_id)
    settings[key] = value
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO guild_settings (guild_id, settings)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (guild_id) DO UPDATE SET settings = EXCLUDED.settings
            """, (guild_id, json.dumps(settings)))
        conn.commit()
    finally:
        conn.close()


def remove_setting(guild_id: int, key: str):
    settings = get_settings(guild_id)
    if key in settings:
        del settings[key]
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO guild_settings (guild_id, settings)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (guild_id) DO UPDATE SET settings = EXCLUDED.settings
                """, (guild_id, json.dumps(settings)))
            conn.commit()
        finally:
            conn.close()


def get_all_settings(guild_id: int = None) -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if guild_id is not None:
                cur.execute("SELECT settings FROM guild_settings WHERE guild_id = %s", (guild_id,))
                row = cur.fetchone()
                if row is None:
                    return {}
                return row[0] if isinstance(row[0], dict) else json.loads(row[0])
            cur.execute("SELECT guild_id, settings FROM guild_settings")
            return {row[0]: row[1] if isinstance(row[1], dict) else json.loads(row[1]) for row in cur.fetchall()}
    finally:
        conn.close()


def get_settings_by_prefix(prefix: str) -> dict:
    all_settings = get_all_settings()
    return {gid: s for gid, s in all_settings.items() if prefix in s}


def get_nitrado_config(guild_id: int) -> dict:
    """Return the Nitrado API config (token/service/user) for a guild.

    Prefers the currently-selected service from the nitrado_services table;
    falls back to the legacy single-service settings.
    """
    svc = get_active_nitrado_service(guild_id)
    if svc and svc.get("api_token"):
        return {
            "api_token": _decrypt(svc.get("api_token", "")),
            "service_id": svc.get("service_id", ""),
            "user_id": "",
            "ftp_host": svc.get("ftp_host", ""),
            "ftp_port": svc.get("ftp_port", "22"),
            "ftp_user": svc.get("ftp_user", ""),
            "ftp_password": _decrypt(svc.get("ftp_password", "")),
        }
    return {
        "api_token": get_setting(guild_id, "nitrado_api_token", ""),
        "service_id": get_setting(guild_id, "nitrado_service_id", ""),
        "user_id": get_setting(guild_id, "nitrado_user_id", ""),
        "ftp_host": get_setting(guild_id, "ftp_host", ""),
        "ftp_port": get_setting(guild_id, "ftp_port", "22"),
        "ftp_user": get_setting(guild_id, "ftp_user", ""),
        "ftp_password": get_setting(guild_id, "ftp_password", ""),
    }


def _svc_row_to_dict(row) -> dict:
    if row is None:
        return {}
    cols = ["id", "guild_id", "name", "service_id", "api_token", "ftp_host",
            "ftp_port", "ftp_user", "ftp_password", "is_active"]
    return {c: row[i] for i, c in enumerate(cols)}


def list_nitrado_services(guild_id: int) -> list[dict]:
    """List all configured Nitrado services for a guild (newest first)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, guild_id, name, service_id, api_token, ftp_host, ftp_port, ftp_user, ftp_password, is_active "
                "FROM nitrado_services WHERE guild_id = %s ORDER BY created_at ASC, id ASC",
                (guild_id,),
            )
            out = []
            for row in cur.fetchall():
                d = _svc_row_to_dict(row)
                d["has_token"] = bool(_decrypt(d.get("api_token", "")))
                d["api_token"] = "••••••••" if d["has_token"] else ""
                out.append(d)
            return out
    except Exception:
        return []
    finally:
        conn.close()


def get_active_nitrado_service(guild_id: int) -> dict:
    """Return the currently-selected (active) Nitrado service, if any."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, guild_id, name, service_id, api_token, ftp_host, ftp_port, ftp_user, ftp_password, is_active "
                "FROM nitrado_services WHERE guild_id = %s AND is_active = TRUE LIMIT 1",
                (guild_id,),
            )
            return _svc_row_to_dict(cur.fetchone())
    except Exception:
        return {}
    finally:
        conn.close()


def add_nitrado_service(guild_id: int, name: str, service_id: str, api_token: str = "",
                        ftp_host: str = "", ftp_port: str = "22", ftp_user: str = "",
                        ftp_password: str = "") -> bool:
    """Add a new Nitrado service (server) for a guild. First service becomes active."""
    name = (name or "").strip() or f"Server-{service_id or '?'}"
    service_id = (service_id or "").strip()
    api_token = _encrypt(api_token or "")
    ftp_password = _encrypt(ftp_password or "")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM nitrado_services WHERE guild_id = %s", (guild_id,))
            count = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO nitrado_services (guild_id, name, service_id, api_token, ftp_host, ftp_port, ftp_user, ftp_password, is_active) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (guild_id, name) DO UPDATE SET service_id = EXCLUDED.service_id, "
                "api_token = CASE WHEN EXCLUDED.api_token = '' THEN nitrado_services.api_token ELSE EXCLUDED.api_token END, "
                "ftp_host = EXCLUDED.ftp_host, ftp_port = EXCLUDED.ftp_port, ftp_user = EXCLUDED.ftp_user, "
                "ftp_password = CASE WHEN EXCLUDED.ftp_password = '' THEN nitrado_services.ftp_password ELSE EXCLUDED.ftp_password END",
                (guild_id, name, service_id, api_token, ftp_host, ftp_port, ftp_user, ftp_password, count == 0),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def set_active_nitrado_service(guild_id: int, service_record_id: int) -> bool:
    """Set which configured service is the active/selected one."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE nitrado_services SET is_active = FALSE WHERE guild_id = %s", (guild_id,))
            cur.execute(
                "UPDATE nitrado_services SET is_active = TRUE WHERE guild_id = %s AND id = %s",
                (guild_id, service_record_id),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def delete_nitrado_service(guild_id: int, service_record_id: int) -> bool:
    """Remove a configured service. If the active one is deleted, activate another."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM nitrado_services WHERE guild_id = %s AND id = %s",
                (guild_id, service_record_id),
            )
            cur.execute(
                "UPDATE nitrado_services SET is_active = TRUE WHERE guild_id = %s AND is_active = FALSE "
                "AND NOT EXISTS (SELECT 1 FROM nitrado_services s2 WHERE s2.guild_id = nitrado_services.guild_id AND s2.is_active = TRUE)",
                (guild_id,),
            )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


# Dashboard aliases
def set_setting(guild_id: int, key: str, value):
    update_setting(guild_id, key, value)


def delete_setting(guild_id: int, key: str):
    remove_setting(guild_id, key)


# ============================================================
#  EMBED TEMPLATES
# ============================================================

DEFAULT_EMBEDS = {
    "welcome": {"title": "Welcome!", "description": "Welcome to the server!", "color": "#FFD700"},
    "goodbye": {"title": "Goodbye!", "description": "See you next time!", "color": "#808080"},
    "shop": {"title": "Shop", "description": "Browse available items.", "color": "#00FF00"},
    "leaderboard": {"title": "Leaderboard", "description": "Top players.", "color": "#FFD700"},
    "automod": {"title": "Automod Alert", "description": "Rule violation detected.", "color": "#FF0000"},
    "tribelog": {"title": "Tribe Log", "description": "Recent tribe activity.", "color": "#0080FF"},
}


def get_embed_templates(guild_id: int) -> list:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embed_id, template, updated_at FROM embed_templates WHERE guild_id = %s",
                (guild_id,),
            )
            return [
                {"id": row[0], "template": row[1] if isinstance(row[1], dict) else json.loads(row[1]), "updated_at": row[2]}
                for row in cur.fetchall()
            ]
    finally:
        conn.close()


_EMBED_FIELDS = ["title", "description", "color", "image_url", "thumbnail_url", "footer_text", "author_name"]


def get_all_embed_templates(guild_id: int) -> dict:
    templates = {}
    for key, default in DEFAULT_EMBEDS.items():
        custom = get_setting(guild_id, f"embed_{key}", {})
        if not isinstance(custom, dict):
            custom = {}
        merged = {f: "" for f in _EMBED_FIELDS}
        merged.update(default)
        merged.update({k: (v or "") for k, v in custom.items() if k in _EMBED_FIELDS})
        templates[key] = merged
    return templates


def get_embed_template(guild_id: int, embed_key: str) -> dict:
    default = DEFAULT_EMBEDS.get(embed_key, {})
    custom = get_setting(guild_id, f"embed_{embed_key}", {})
    return {**default, **custom}


def save_embed_template(guild_id: int, embed_id: str, template: dict):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO embed_templates (embed_id, guild_id, template, updated_at)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT (embed_id)
                DO UPDATE SET template = EXCLUDED.template, updated_at = EXCLUDED.updated_at
            """, (embed_id, guild_id, json.dumps(template), datetime.now(timezone.utc)))
        conn.commit()
    finally:
        conn.close()


def set_embed_template(guild_id: int, embed_key: str, **kwargs):
    current = get_setting(guild_id, f"embed_{embed_key}", {})
    current.update(kwargs)
    update_setting(guild_id, f"embed_{embed_key}", current)


def reset_embed_template(guild_id: int, embed_key: str):
    remove_setting(guild_id, f"embed_{embed_key}")


def delete_embed_template(guild_id: int, embed_id: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM embed_templates WHERE guild_id = %s AND embed_id = %s", (guild_id, embed_id))
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  LOGGING
# ============================================================

LOG_TYPES = ["chat", "admin_command", "punishment", "leaderboard", "whitelist", "automod", "server", "tribe"]


def log_action(guild_id: int, log_type: str, user_id=None, user_name=None,
               player_name=None, command=None, sub_type=None, details=None, log_category=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_logs (guild_id, log_type, sub_type, user_id, user_name, player_name, command, details, log_category)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """, (guild_id, log_type, sub_type, user_id, user_name, player_name, command,
                  json.dumps(details) if details else None, log_category))
        conn.commit()
    finally:
        conn.close()


def get_logs(guild_id: int, log_type=None, user_id=None, limit=50, offset=0):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = "SELECT id, log_type, sub_type, user_id, user_name, player_name, command, details, created_at, log_category FROM bot_logs WHERE guild_id = %s"
            params = [guild_id]
            if log_type:
                query += " AND log_type = %s"
                params.append(log_type)
            if user_id:
                query += " AND user_id = %s"
                params.append(user_id)
            query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cur.execute(query, params)
            return [
                {"id": r[0], "log_type": r[1], "sub_type": r[2], "user_id": r[3], "user_name": r[4],
                 "player_name": r[5], "command": r[6], "details": r[7] if isinstance(r[7], dict) else json.loads(r[7]) if r[7] else None, "created_at": r[8], "log_category": r[9]}
                for r in cur.fetchall()
            ]
    finally:
        conn.close()


def get_log_count(guild_id: int, log_type=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = "SELECT COUNT(*) FROM bot_logs WHERE guild_id = %s"
            params = [guild_id]
            if log_type:
                query += " AND log_type = %s"
                params.append(log_type)
            cur.execute(query, params)
            return cur.fetchone()[0]
    finally:
        conn.close()


# ============================================================
#  PENDING ACTIONS
# ============================================================

def set_pending_action(guild_id: int, action: str, payload: dict = None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pending_actions (guild_id, action, payload)
                VALUES (%s, %s, %s::jsonb)
            """, (guild_id, action, json.dumps(payload) if payload else None))
        conn.commit()
    finally:
        conn.close()


def get_pending_actions(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, action, payload, created_at FROM pending_actions WHERE guild_id = %s AND status = 'pending' ORDER BY created_at",
                (guild_id,),
            )
            return [
                {"id": r[0], "action": r[1], "payload": r[2] if isinstance(r[2], dict) else json.loads(r[2]) if r[2] else None, "created_at": r[3]}
                for r in cur.fetchall()
            ]
    finally:
        conn.close()


def mark_action_done(action_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE pending_actions SET status = 'done' WHERE id = %s", (action_id,))
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  TRIBE MEMBERS
# ============================================================

def add_tribe_member(guild_id: int, tribe_name: str, player_name: str, player_id: str = None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tribe_members (guild_id, tribe_name, player_name, player_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (guild_id, tribe_name, player_name) DO NOTHING
            """, (guild_id, tribe_name, player_name, player_id))
        conn.commit()
    finally:
        conn.close()


def get_tribe_members(guild_id: int, tribe_name: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT player_name, player_id FROM tribe_members WHERE guild_id = %s AND tribe_name = %s",
                (guild_id, tribe_name),
            )
            return cur.fetchall()
    finally:
        conn.close()


def get_player_tribe(guild_id: int, player_name: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tribe_name FROM tribe_members WHERE guild_id = %s AND player_name = %s",
                (guild_id, player_name),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


def remove_tribe_member(guild_id: int, tribe_name: str, player_name: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tribe_members WHERE guild_id = %s AND tribe_name = %s AND player_name = %s",
                (guild_id, tribe_name, player_name),
            )
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  WARNINGS
# ============================================================

def add_warning(guild_id: int, player_name: str, reason: str, warned_by: int, player_id: str = None, expires_at=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO player_warnings (guild_id, player_name, player_id, reason, warned_by, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (guild_id, player_name, player_id, reason, warned_by, expires_at))
            warning_id = cur.fetchone()[0]
        conn.commit()
        return warning_id
    finally:
        conn.close()


def get_active_warning_count(guild_id: int, player_name: str) -> int:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM player_warnings
                WHERE guild_id = %s AND player_name = %s AND active = TRUE
                AND (expires_at IS NULL OR expires_at > NOW())
            """, (guild_id, player_name))
            return cur.fetchone()[0]
    finally:
        conn.close()


def get_warnings(guild_id: int, player_name: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, reason, warned_by, warned_at, expires_at, active
                FROM player_warnings WHERE guild_id = %s AND player_name = %s
                ORDER BY warned_at DESC
            """, (guild_id, player_name))
            return cur.fetchall()
    finally:
        conn.close()


def clear_warnings(guild_id: int, player_name: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE player_warnings SET active = FALSE WHERE guild_id = %s AND player_name = %s AND active = TRUE",
                (guild_id, player_name),
            )
        conn.commit()
    finally:
        conn.close()


def remove_warning(warning_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE player_warnings SET active = FALSE WHERE id = %s", (warning_id,))
        conn.commit()
    finally:
        conn.close()


def cleanup_expired_warnings():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE player_warnings SET active = FALSE
                WHERE active = TRUE AND expires_at IS NOT NULL AND expires_at <= NOW()
            """)
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  PUNISHMENTS
# ============================================================

PUNISHMENT_TYPES = ["ban", "tempban", "wipe_structures", "wipe_dinos", "wipe_both"]


def add_punishment(guild_id: int, player_name: str, punishment_type: str, reason: str,
                    issued_by: int, scope: str = "player", player_id: str = None,
                    tribe_name: str = None, expires_at=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO player_punishments (guild_id, player_name, player_id, tribe_name, punishment_type, reason, issued_by, scope, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (guild_id, player_name, player_id, tribe_name, punishment_type, reason, issued_by, scope, expires_at))
            punishment_id = cur.fetchone()[0]
        conn.commit()
        return punishment_id
    finally:
        conn.close()


def mark_punishment_executed(punishment_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE player_punishments SET executed = TRUE WHERE id = %s", (punishment_id,))
        conn.commit()
    finally:
        conn.close()


def get_punishments(guild_id: int, player_name: str = None, limit=50, offset=0):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = "SELECT id, player_name, player_id, tribe_name, punishment_type, reason, issued_by, scope, issued_at, expires_at, executed, appealed FROM player_punishments WHERE guild_id = %s"
            params = [guild_id]
            if player_name:
                query += " AND player_name = %s"
                params.append(player_name)
            query += " ORDER BY issued_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            cur.execute(query, params)
            return cur.fetchall()
    finally:
        conn.close()


def get_expired_tempbans():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, guild_id, player_name, player_id
                FROM player_punishments
                WHERE punishment_type = 'tempban' AND executed = TRUE
                AND expires_at IS NOT NULL AND expires_at <= NOW()
                AND appealed = FALSE
            """)
            return cur.fetchall()
    finally:
        conn.close()


def appeal_punishment(punishment_id: int, appeal_reason: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE player_punishments SET appealed = TRUE, appeal_reason = %s WHERE id = %s",
                (appeal_reason, punishment_id),
            )
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  EVIDENCE
# ============================================================

def add_evidence(punishment_id: int, guild_id: int, filename: str, original_name: str, file_size: int, uploaded_by: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO punishment_evidence (punishment_id, guild_id, filename, original_name, file_size, uploaded_by)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (punishment_id, guild_id, filename, original_name, file_size, uploaded_by))
        conn.commit()
    finally:
        conn.close()


def get_evidence(punishment_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, filename, original_name, file_size, uploaded_by, created_at FROM punishment_evidence WHERE punishment_id = %s",
                (punishment_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


# ============================================================
#  PLAYER WHITELIST (dashboard)
# ============================================================

def add_whitelist(guild_id: int, player_name: str, player_id: str = "", reason: str = "", issued_by: int = 0, expires_at=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO player_whitelist (guild_id, player_name, player_id, reason, issued_by, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (guild_id, player_name, player_id or None, reason or None, issued_by, expires_at))
            return cur.fetchone()[0]
    finally:
        conn.close()


def get_whitelists(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, player_name, player_id, reason, issued_by, created_at, expires_at
                FROM player_whitelist
                WHERE guild_id = %s
                ORDER BY created_at DESC
            """, (guild_id,))
            return cur.fetchall()
    finally:
        conn.close()


def remove_whitelist(entry_id: int, guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM player_whitelist WHERE id = %s AND guild_id = %s", (entry_id, guild_id))
            return cur.rowcount > 0
    finally:
        conn.close()


# ============================================================
#  LICENSE
# ============================================================

def generate_license_key() -> str:
    """Generate a purely random activation-license key, e.g. ARK-XXXXXX-XXXXXX-XXXXXX.
    The key carries no readable data; expiry is stored in the database."""
    alphabet = string.ascii_uppercase + string.digits
    # 3 groups of 6 => 18 random chars (~107 bits of entropy) - strong and easy to copy.
    groups = ["".join(secrets.choice(alphabet) for _ in range(6)) for _ in range(3)]
    return "ARK-" + "-".join(groups)


def is_license_valid(guild_id: int) -> bool:
    from datetime import datetime, timezone, timedelta
    key = get_setting(guild_id, "license_key", "")
    if not key:
        return False
    days = get_setting(guild_id, "license_days", 0)
    if days == 0:
        return True
    created = get_setting(guild_id, "license_created")
    if not created:
        return True
    try:
        if isinstance(created, str):
            created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
        else:
            created_dt = created
        expires = created_dt + timedelta(days=days)
        return datetime.now(timezone.utc) < expires
    except (ValueError, TypeError):
        return True


def get_license_expiry(guild_id: int) -> str:
    """Human-readable expiry for dashboard display."""
    from datetime import datetime, timezone, timedelta
    days = get_setting(guild_id, "license_days", 0)
    if not get_setting(guild_id, "license_key", ""):
        return ""
    if days == 0:
        return "Unlimited"
    created = get_setting(guild_id, "license_created")
    try:
        if isinstance(created, str):
            created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
        else:
            created_dt = created
        expires = created_dt + timedelta(days=days)
        return expires.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return "Unknown"


def parse_license_key(key: str) -> dict | None:
    """Simple format validation. Returns the key if it looks like a license key, else None.
    Real authorization is done by matching against the stored key in the database."""
    if not key or not key.startswith("ARK-"):
        return None
    body = key[4:]
    parts = body.split("-")
    if len(parts) != 3:
        return None
    if not all(len(p) == 6 and p.isalnum() for p in parts):
        return None
    return {"key": key}


def verify_license_key(guild_id: int, key: str) -> bool:
    """True only if the supplied key matches the one stored for this guild AND is not expired."""
    stored = get_setting(guild_id, "license_key", "")
    if not stored or not key:
        return False
    try:
        # compare as bytes to safely handle any input (incl. non-ASCII) without raising
        if not hmac.compare_digest(stored.strip().encode("utf-8"), key.strip().encode("utf-8")):
            return False
    except Exception:
        return False
    return is_license_valid(guild_id)


def get_all_licenses() -> list[dict]:
    from datetime import datetime, timezone, timedelta
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT guild_id, settings FROM guild_settings")
            rows = cur.fetchall()
        results = []
        for guild_id, settings in rows:
            if not isinstance(settings, dict):
                settings = json.loads(settings)
            key = settings.get("license_key", "")
            if not key:
                continue
            days = settings.get("license_days", 0)
            created = settings.get("license_created")
            expiry_str = "" if not key else ("Unlimited" if days == 0 else "Unknown")
            is_valid = False
            if key:
                if days == 0:
                    is_valid = True
                    expiry_str = "Unlimited"
                else:
                    try:
                        if isinstance(created, str):
                            created_dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                        elif created:
                            created_dt = created
                        else:
                            created_dt = datetime.now(timezone.utc)
                        expires = created_dt + timedelta(days=days)
                        is_valid = datetime.now(timezone.utc) < expires
                        expiry_str = expires.strftime("%Y-%m-%d %H:%M UTC")
                    except (ValueError, TypeError):
                        is_valid = False
                        expiry_str = "Unknown"
            results.append({
                "guild_id": guild_id,
                "key": key,
                "days": days,
                "created": created,
                "expiry": expiry_str,
                "valid": is_valid,
            })
        return results
    finally:
        conn.close()


def create_license_for_guild(guild_id: int, duration_days: int = 30) -> str:
    key = generate_license_key()
    update_setting(guild_id, "license_key", key)
    update_setting(guild_id, "license_days", duration_days)
    update_setting(guild_id, "license_created", datetime.now(timezone.utc).isoformat())
    return key


# ============================================================
#  LOG CHANNEL HELPERS (dashboard)
# ============================================================

def set_log_channel(guild_id: int, log_type: str, channel_id: int):
    update_setting(guild_id, f"log_channel_{log_type}", channel_id)


def get_all_log_channels(guild_id: int) -> dict:
    settings = get_settings(guild_id)
    return {k.replace("log_channel_", ""): v for k, v in settings.items() if k.startswith("log_channel_")}


def get_all_settings_for_guild(guild_id: int) -> dict:
    return get_settings(guild_id)


# ============================================================
#  COMMAND PERMISSIONS
# ============================================================

def set_command_permission(guild_id: int, command: str, role_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO command_permissions (guild_id, command, role_id)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (guild_id, command, role_id))
        conn.commit()
    finally:
        conn.close()


def remove_command_permission(guild_id: int, command: str, role_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM command_permissions WHERE guild_id = %s AND command = %s AND role_id = %s",
                (guild_id, command, role_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_command_permissions(guild_id: int, command: str) -> list:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role_id FROM command_permissions WHERE guild_id = %s AND command = %s",
                (guild_id, command),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_all_command_permissions(guild_id: int) -> dict:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT command, role_id FROM command_permissions WHERE guild_id = %s",
                (guild_id,),
            )
            result = {}
            for cmd, role_id in cur.fetchall():
                result.setdefault(cmd, []).append(role_id)
            return result
    finally:
        conn.close()


def clear_command_permissions(guild_id: int, command: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM command_permissions WHERE guild_id = %s AND command = %s",
                (guild_id, command),
            )
        conn.commit()
    finally:
        conn.close()


def has_command_permission(guild_id: int, command: str, member) -> bool:
    """Check if a member has permission to use a command.

    Rules:
    - Guild admins always have permission.
    - If no roles are configured for the command, anyone with default Discord perms can use it.
    - If roles ARE configured, the member must have at least one of those roles.
    """
    if member.guild_permissions.administrator:
        return True

    allowed_roles = get_command_permissions(guild_id, command)
    if not allowed_roles:
        return True  # no restriction — use default Discord perms

    member_role_ids = {r.id for r in member.roles}
    return bool(member_role_ids & set(allowed_roles))


# ============================================================
#  AUTOMOD CUSTOM WORDS
# ============================================================

def add_automod_word(guild_id: int, word: str, added_by: int = None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO automod_custom_words (guild_id, word, added_by)
                VALUES (%s, %s, %s)
                ON CONFLICT (guild_id, word) DO NOTHING
            """, (guild_id, word.lower().strip(), added_by))
        conn.commit()
    finally:
        conn.close()


def remove_automod_word(guild_id: int, word: str) -> bool:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM automod_custom_words WHERE guild_id = %s AND word = %s",
                (guild_id, word.lower().strip()),
            )
            deleted = cur.rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()


def get_automod_words(guild_id: int) -> list:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT word FROM automod_custom_words WHERE guild_id = %s ORDER BY word",
                (guild_id,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_automod_words_with_info(guild_id: int) -> list:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, word, added_by, created_at FROM automod_custom_words WHERE guild_id = %s ORDER BY word",
                (guild_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def clear_automod_words(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM automod_custom_words WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  CONTENT OVERRIDES (dashboard text customization)
# ============================================================

def set_content_override(content_key: str, lang: str, value: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO content_overrides (content_key, lang, value, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (content_key, lang)
                DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """, (content_key, lang, value))
        conn.commit()
    finally:
        conn.close()


def delete_content_override(content_key: str, lang: str = None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if lang is None:
                cur.execute("DELETE FROM content_overrides WHERE content_key = %s", (content_key,))
            else:
                cur.execute(
                    "DELETE FROM content_overrides WHERE content_key = %s AND lang = %s",
                    (content_key, lang),
                )
        conn.commit()
    finally:
        conn.close()


def get_all_content_overrides() -> dict:
    """Return {content_key: {lang: value}}"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content_key, lang, value FROM content_overrides")
            rows = cur.fetchall()
        result = {}
        for key, lang, value in rows:
            result.setdefault(key, {})[lang] = value
        return result
    finally:
        conn.close()


def get_content_override(content_key: str, lang: str) -> str:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value FROM content_overrides WHERE content_key = %s AND lang = %s",
                (content_key, lang),
            )
            row = cur.fetchone()
            return row[0] if row else None
    finally:
        conn.close()


# ============================================================
#  CUSTOM COMMANDS
# ============================================================

LOG_CATEGORIES = ["dino_spawn", "gfi", "player", "gcm"]

# Default keyword detection for auto-categorizing ARK commands.
DEFAULT_CATEGORY_RULES = {
    "dino_spawn": ["gmsummon", "summontamed", "summon ", "spawndino", "spawnactor", "sdf", "do injure", "force tame", "tame "],
    "gfi": ["gfi", "giveitemtoplayer", "giveitemnum", "giveitem ", "giveengrams", "giveresources"],
    "player": ["teleport", "tpname", "teleportplayername", "addexperience", "addexp", "addxp", "givecolors", "setplayername", "god", "infinitestats", "walk", "fly"],
    "gcm": ["gcm", "gmc", "cheatmenu", "setcheat", "setgm"],
}


def detect_log_category(command: str, custom_rules: dict = None) -> str:
    """Auto-detect a log category from an ARK command string, honoring custom rules."""
    lowered = (command or "").lower()
    rules = DEFAULT_CATEGORY_RULES
    if custom_rules:
        merged = {}
        for cat in LOG_CATEGORIES:
            merged[cat] = list(DEFAULT_CATEGORY_RULES.get(cat, []))
            merged[cat] += [r.lower() for r in custom_rules.get(cat, [])]
        rules = merged
    for cat in LOG_CATEGORIES:
        for keyword in rules.get(cat, []):
            if keyword in lowered:
                return cat
    return "gcm"


def detect_log_category_for_guild(guild_id: int, command: str) -> str:
    """Detect a log category using the guild's custom rules, falling back to defaults."""
    return detect_log_category(command, get_category_rules(guild_id))


def add_custom_command(guild_id: int, name: str, command_string: str, category: str = None, created_by: int = None) -> str:
    """Create a custom command. Returns 'ok' or an error string."""
    if category is None:
        category = detect_log_category(command_string)
    if category not in LOG_CATEGORIES:
        category = "gcm"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO custom_commands (guild_id, name, command_string, category, created_by)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (guild_id, name) DO UPDATE
                    SET command_string = EXCLUDED.command_string,
                        category = EXCLUDED.category,
                        enabled = TRUE
                RETURNING 1
            """, (guild_id, name, command_string, category, created_by))
        conn.commit()
        return "ok"
    finally:
        conn.close()


def get_custom_commands(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, command_string, category, enabled, created_at
                FROM custom_commands
                WHERE guild_id = %s
                ORDER BY name ASC
            """, (guild_id,))
            return [{"id": r[0], "name": r[1], "command_string": r[2], "category": r[3], "enabled": r[4], "created_at": r[5]} for r in cur.fetchall()]
    finally:
        conn.close()


def get_custom_command(guild_id: int, name: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, name, command_string, category, enabled
                FROM custom_commands
                WHERE guild_id = %s AND name = %s AND enabled = TRUE
            """, (guild_id, name))
            row = cur.fetchone()
            if not row:
                return None
            return {"id": row[0], "name": row[1], "command_string": row[2], "category": row[3], "enabled": row[4]}
    finally:
        conn.close()


def update_custom_command(guild_id: int, name: str, command_string: str = None, category: str = None, enabled: bool = None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT command_string, category FROM custom_commands WHERE guild_id = %s AND name = %s
            """, (guild_id, name))
            row = cur.fetchone()
            if not row:
                return False
            cur_cmd = command_string if command_string is not None else row[0]
            cur_cat = category if category is not None else row[1]
            if cur_cat not in LOG_CATEGORIES:
                cur_cat = detect_log_category(cur_cmd)
            cur_enabled = enabled if enabled is not None else True
            cur.execute("""
                UPDATE custom_commands
                SET command_string = %s, category = %s, enabled = %s
                WHERE guild_id = %s AND name = %s
            """, (cur_cmd, cur_cat, cur_enabled, guild_id, name))
        conn.commit()
        return True
    finally:
        conn.close()


def remove_custom_command(guild_id: int, name: str) -> bool:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM custom_commands WHERE guild_id = %s AND name = %s", (guild_id, name))
            deleted = cur.rowcount
        conn.commit()
        return deleted > 0
    finally:
        conn.close()


# ============================================================
#  FORUM LOG CONFIG
# ============================================================

def get_forum_log_config(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT forum_id, thread_dino, thread_gfi, thread_player, thread_gcm
                FROM forum_log_config WHERE guild_id = %s
            """, (guild_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "forum_id": row[0],
                "thread_dino": row[1],
                "thread_gfi": row[2],
                "thread_player": row[3],
                "thread_gcm": row[4],
            }
    finally:
        conn.close()


def set_forum_log_config(guild_id: int, forum_id: int, thread_dino: int = None,
                         thread_gfi: int = None, thread_player: int = None, thread_gcm: int = None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO forum_log_config (guild_id, forum_id, thread_dino, thread_gfi, thread_player, thread_gcm)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (guild_id) DO UPDATE SET
                    forum_id = EXCLUDED.forum_id,
                    thread_dino = COALESCE(EXCLUDED.thread_dino, forum_log_config.thread_dino),
                    thread_gfi = COALESCE(EXCLUDED.thread_gfi, forum_log_config.thread_gfi),
                    thread_player = COALESCE(EXCLUDED.thread_player, forum_log_config.thread_player),
                    thread_gcm = COALESCE(EXCLUDED.thread_gcm, forum_log_config.thread_gcm)
            """, (guild_id, forum_id, thread_dino, thread_gfi, thread_player, thread_gcm))
        conn.commit()
    finally:
        conn.close()


def get_unposted_forum_logs(guild_id: int, limit: int = 50):
    """Return categorized log entries not yet posted to the forum."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, log_type, sub_type, user_id, user_name, player_name, command, details, created_at, log_category
                FROM bot_logs
                WHERE guild_id = %s AND log_category IS NOT NULL AND posted_forum = FALSE
                ORDER BY id ASC
                LIMIT %s
            """, (guild_id, limit))
            return [
                {"id": r[0], "log_type": r[1], "sub_type": r[2], "user_id": r[3], "user_name": r[4],
                 "player_name": r[5], "command": r[6], "details": r[7] if isinstance(r[7], dict) else json.loads(r[7]) if r[7] else None, "created_at": r[8], "log_category": r[9]}
                for r in cur.fetchall()
            ]
    finally:
        conn.close()


def mark_log_posted(log_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE bot_logs SET posted_forum = TRUE WHERE id = %s", (log_id,))
        conn.commit()
    finally:
        conn.close()


def get_unposted_shop_logs(guild_id: int, limit: int = 50):
    """Return shop log entries (pending/delivered/cancelled) not yet posted to the shop forum."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, log_type, sub_type, user_id, user_name, player_name, command, details, created_at
                FROM bot_logs
                WHERE guild_id = %s
                  AND log_type = 'leaderboard'
                  AND sub_type IN ('purchase_pending', 'purchase_delivered', 'purchase_cancelled')
                  AND posted_shop_forum = FALSE
                ORDER BY id ASC
                LIMIT %s
            """, (guild_id, limit))
            return [
                {"id": r[0], "log_type": r[1], "sub_type": r[2], "user_id": r[3], "user_name": r[4],
                 "player_name": r[5], "command": r[6], "details": r[7] if isinstance(r[7], dict) else json.loads(r[7]) if r[7] else None, "created_at": r[8]}
                for r in cur.fetchall()
            ]
    finally:
        conn.close()


def mark_shop_log_posted(log_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE bot_logs SET posted_shop_forum = TRUE WHERE id = %s", (log_id,))
        conn.commit()
    finally:
        conn.close()


def get_shop_forum_config(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT forum_id, thread_done, thread_pending
                FROM shop_forum_config WHERE guild_id = %s
            """, (guild_id,))
            row = cur.fetchone()
            if not row:
                return None
            return {"forum_id": row[0], "thread_done": row[1], "thread_pending": row[2]}
    finally:
        conn.close()


def set_shop_forum_config(guild_id: int, forum_id: int, thread_done: int = None, thread_pending: int = None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shop_forum_config (guild_id, forum_id, thread_done, thread_pending)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (guild_id) DO UPDATE SET
                    forum_id = EXCLUDED.forum_id,
                    thread_done = COALESCE(EXCLUDED.thread_done, shop_forum_config.thread_done),
                    thread_pending = COALESCE(EXCLUDED.thread_pending, shop_forum_config.thread_pending)
            """, (guild_id, forum_id, thread_done, thread_pending))
        conn.commit()
    finally:
        conn.close()


# ============================================================
#  TRIBE FORUM / TRIBE LOG EVENTS
# ============================================================

def get_tribe_forum_config(guild_id: int):
    """Return {forum_id, threads: {tribe_name: thread_id}} or None."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT forum_id FROM tribe_forum_config WHERE guild_id = %s", (guild_id,))
            row = cur.fetchone()
            if not row:
                return None
            threads = {}
            cur.execute("SELECT tribe_name, thread_id FROM tribe_forum_threads WHERE guild_id = %s", (guild_id,))
            for t, tid in cur.fetchall():
                threads[t] = tid
            return {"forum_id": row[0], "threads": threads}
    finally:
        conn.close()


def set_tribe_forum_config(guild_id: int, forum_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tribe_forum_config (guild_id, forum_id) VALUES (%s, %s)
                ON CONFLICT (guild_id) DO UPDATE SET forum_id = EXCLUDED.forum_id
            """, (guild_id, forum_id))
        conn.commit()
    finally:
        conn.close()


def set_tribe_thread(guild_id: int, tribe_name: str, thread_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tribe_forum_threads (guild_id, tribe_name, thread_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (guild_id, tribe_name) DO UPDATE SET thread_id = EXCLUDED.thread_id
            """, (guild_id, tribe_name, thread_id))
        conn.commit()
    finally:
        conn.close()


def clear_tribe_threads(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tribe_forum_threads WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()


def add_tribe_log_event(guild_id: int, tribe_name: str, content: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tribe_log_events (guild_id, tribe_name, content) VALUES (%s, %s, %s)",
                (guild_id, tribe_name, content),
            )
        conn.commit()
    finally:
        conn.close()


def get_unposted_tribe_events(guild_id: int, limit: int = 50):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, tribe_name, content, created_at
                FROM tribe_log_events
                WHERE guild_id = %s AND posted_forum = FALSE
                ORDER BY id ASC
                LIMIT %s
            """, (guild_id, limit))
            return [
                {"id": r[0], "tribe_name": r[1], "content": r[2], "created_at": r[3]}
                for r in cur.fetchall()
            ]
    finally:
        conn.close()


def mark_tribe_event_posted(log_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE tribe_log_events SET posted_forum = TRUE WHERE id = %s", (log_id,))
        conn.commit()
    finally:
        conn.close()


def get_tribe_log_events(guild_id: int, tribe_name: str = None, limit: int = 100, offset: int = 0):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if tribe_name:
                cur.execute("""
                    SELECT id, tribe_name, content, created_at
                    FROM tribe_log_events
                    WHERE guild_id = %s AND tribe_name = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (guild_id, tribe_name, limit, offset))
            else:
                cur.execute("""
                    SELECT id, tribe_name, content, created_at
                    FROM tribe_log_events
                    WHERE guild_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (guild_id, limit, offset))
            return [
                {"id": r[0], "tribe_name": r[1], "content": r[2], "created_at": r[3]}
                for r in cur.fetchall()
            ]
    finally:
        conn.close()


def get_tribe_log_event_count(guild_id: int, tribe_name: str = None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if tribe_name:
                cur.execute("SELECT COUNT(*) FROM tribe_log_events WHERE guild_id = %s AND tribe_name = %s", (guild_id, tribe_name))
            else:
                cur.execute("SELECT COUNT(*) FROM tribe_log_events WHERE guild_id = %s", (guild_id,))
            return cur.fetchone()[0]
    finally:
        conn.close()


def get_tribe_event_counts(guild_id: int) -> dict:
    """Return {tribe_name: event_count}."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tribe_name, COUNT(*) FROM tribe_log_events WHERE guild_id = %s GROUP BY tribe_name", (guild_id,))
            return {r[0]: r[1] for r in cur.fetchall()}
    finally:
        conn.close()


# ============================================================
#  WIPE HELPERS
# ============================================================

def wipe_tribe_logs(guild_id: int):
    """Delete all stored tribe log events for a guild."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tribe_log_events WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()


def wipe_bot_logs(guild_id: int):
    """Delete all stored bot/action logs for a guild."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bot_logs WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()


def wipe_warnings(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM player_warnings WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()


def wipe_punishments(guild_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM player_punishments WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()


def get_category_rules(guild_id: int) -> dict:
    """Return per-guild custom keyword rules for log-category detection."""
    raw = get_setting(guild_id, "category_rules", None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return {}


def set_category_rules(guild_id: int, rules: dict):
    update_setting(guild_id, "category_rules", json.dumps(rules))


# ============================================================
#  PLAYER PLAYTIME TRACKING
# ============================================================

def record_playtime(guild_id: int, players: list, seconds: int):
    """Accumulate `seconds` of playtime only for currently-online players."""
    if not players or seconds <= 0:
        return
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for p in players:
                if not isinstance(p, dict):
                    continue
                if not p.get("online"):
                    continue
                pid = str(p.get("id") or p.get("name") or "unknown")
                pname = str(p.get("name") or "Unknown")
                cur.execute("""
                    INSERT INTO player_playtime (guild_id, player_id, player_name, seconds, last_seen)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (guild_id, player_id)
                    DO UPDATE SET
                        player_name = EXCLUDED.player_name,
                        seconds = player_playtime.seconds + EXCLUDED.seconds,
                        last_seen = NOW()
                """, (guild_id, pid, pname, seconds))
        conn.commit()
    finally:
        conn.close()


def get_playtime_map(guild_id: int) -> dict:
    """Return playtime lookups keyed by player_id and player_name, plus raw rows.

    shape: {"by_id": {...}, "by_name": {...}, "rows": [ ... ]}
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT player_id, player_name, seconds, last_seen
                FROM player_playtime
                WHERE guild_id = %s
                ORDER BY seconds DESC
            """, (guild_id,))
            rows = cur.fetchall()
        by_id = {}
        by_name = {}
        for pid, pname, seconds, last_seen in rows:
            key_id = str(pid or "")
            if key_id:
                by_id[key_id] = {"seconds": seconds, "last_seen": last_seen}
            if pname:
                by_name[pname.lower()] = {"seconds": seconds, "last_seen": last_seen}
        return {"by_id": by_id, "by_name": by_name, "rows": rows}
    finally:
        conn.close()


def get_top_players(guild_id: int, limit: int = 20):
    """Return the top players by accumulated playtime (seconds)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT player_id, player_name, seconds, last_seen
                FROM player_playtime
                WHERE guild_id = %s
                ORDER BY seconds DESC
                LIMIT %s
            """, (guild_id, limit))
            return [
                {
                    "player_id": r[0],
                    "player_name": r[1],
                    "seconds": r[2],
                    "last_seen": r[3],
                }
                for r in cur.fetchall()
            ]
    finally:
        conn.close()


def reset_playtime(guild_id: int = None):
    """Clear accumulated playtime. If guild_id is None, clears for all guilds.

    Used to wipe bogus data accumulated before the online-only tracking fix.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if guild_id is None:
                cur.execute("DELETE FROM player_playtime")
            else:
                cur.execute("DELETE FROM player_playtime WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()
