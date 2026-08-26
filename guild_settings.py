import os
import json
import secrets
import string
from datetime import datetime, timezone

import psycopg2
from cryptography.fernet import Fernet


DATABASE_URL = os.getenv("DATABASE_URL")
_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
_fernet = Fernet(_ENCRYPTION_KEY.encode()) if _ENCRYPTION_KEY else None

ENCRYPTED_FIELDS = {"rcon_password", "sftp_password", "nitrado_api_token"}


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


def get_all_embed_templates(guild_id: int) -> dict:
    templates = {}
    for key, default in DEFAULT_EMBEDS.items():
        custom = get_setting(guild_id, f"embed_{key}", {})
        merged = {**default, **custom}
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
               player_name=None, command=None, sub_type=None, details=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_logs (guild_id, log_type, sub_type, user_id, user_name, player_name, command, details)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """, (guild_id, log_type, sub_type, user_id, user_name, player_name, command,
                  json.dumps(details) if details else None))
        conn.commit()
    finally:
        conn.close()


def get_logs(guild_id: int, log_type=None, user_id=None, limit=50, offset=0):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            query = "SELECT id, log_type, sub_type, user_id, user_name, player_name, command, details, created_at FROM bot_logs WHERE guild_id = %s"
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
                 "player_name": r[5], "command": r[6], "details": r[7] if isinstance(r[7], dict) else json.loads(r[7]) if r[7] else None, "created_at": r[8]}
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
#  LICENSE
# ============================================================

def is_license_valid(guild_id: int) -> bool:
    from datetime import datetime, timezone, timedelta
    key = get_setting(guild_id, "license_key", "")
    days = get_setting(guild_id, "license_days", 0)
    if not key:
        return False
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


def generate_license_key(duration_days: int = 30) -> str:
    alphabet = string.ascii_uppercase + string.digits
    key = "ARK-" + "".join(secrets.choice(alphabet) for _ in range(16))
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
