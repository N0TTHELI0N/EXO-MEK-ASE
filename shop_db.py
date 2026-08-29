import os
import json
from datetime import datetime, timezone

import psycopg2


DATABASE_URL = os.getenv("DATABASE_URL")


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


def init_shop_db():
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
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
                CREATE TABLE IF NOT EXISTS pending_purchases (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    user_id     BIGINT NOT NULL,
                    user_name   TEXT NOT NULL,
                    dino_name   TEXT NOT NULL,
                    blueprint   TEXT NOT NULL,
                    level       INTEGER NOT NULL,
                    price       INTEGER NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    message_id  BIGINT,
                    delivered_by BIGINT,
                    delivered_at TIMESTAMP WITH TIME ZONE,
                    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
        conn.commit()
    finally:
        conn.close()


def init_leaderboard_db():
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tribe_points (
                    id          SERIAL PRIMARY KEY,
                    guild_id    BIGINT NOT NULL,
                    tribe_name  TEXT NOT NULL,
                    points      INTEGER DEFAULT 0,
                    last_update TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS leaderboard_config (
                    guild_id        BIGINT PRIMARY KEY,
                    announcement_channel_id BIGINT,
                    announcement_message TEXT,
                    update_interval INTEGER DEFAULT 5,
                    last_update     TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """)
        conn.commit()
    finally:
        conn.close()


# ---------- Shop Dinosaurs ----------

def add_shop_dino(guild_id: int, name: str, blueprint: str, min_level: int = 1, max_level: int = 150, price: int = 0, category: str = "General"):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO shop_dinos (guild_id, name, blueprint, min_level, max_level, price, category)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (guild_id, name, blueprint, min_level, max_level, price, category))
        conn.commit()
    finally:
        conn.close()


def remove_shop_dino(guild_id: int, name: str):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM shop_dinos WHERE guild_id = %s AND name = %s", (guild_id, name))
        conn.commit()
    finally:
        conn.close()


def get_shop_dinos(guild_id: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, blueprint, min_level, max_level, price, category FROM shop_dinos WHERE guild_id = %s", (guild_id,))
            return cur.fetchall()
    finally:
        conn.close()


def get_all_shop_dinos(guild_id: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, blueprint, min_level, max_level, price, category FROM shop_dinos WHERE guild_id = %s", (guild_id,))
            return [{"id": r[0], "name": r[1], "blueprint": r[2], "min_level": r[3], "max_level": r[4], "price": r[5], "category": r[6]} for r in cur.fetchall()]
    finally:
        conn.close()


def search_shop_dinos(guild_id: int, query: str):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, blueprint, min_level, max_level, price, category FROM shop_dinos WHERE guild_id = %s AND LOWER(name) LIKE LOWER(%s)", (guild_id, f"%{query}%"))
            return cur.fetchall()
    finally:
        conn.close()


def get_shop_dino_by_name(guild_id: int, name: str):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, blueprint, min_level, max_level, price, category FROM shop_dinos WHERE guild_id = %s AND name = %s", (guild_id, name))
            return cur.fetchone()
    finally:
        conn.close()


# ---------- Points / Leaderboard ----------

def get_points(guild_id: int, tribe_name: str) -> int:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM tribe_points WHERE guild_id = %s AND tribe_name = %s", (guild_id, tribe_name))
            row = cur.fetchone()
            return row[0] if row else 0
    finally:
        conn.close()


def add_points(guild_id: int, tribe_name: str, amount: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tribe_points (guild_id, tribe_name, points, last_update)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (guild_id, tribe_name)
                DO UPDATE SET points = tribe_points.points + EXCLUDED.points, last_update = NOW()
            """, (guild_id, tribe_name, amount))
        conn.commit()
    finally:
        conn.close()


def remove_points(guild_id: int, tribe_name: str, amount: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tribe_points
                SET points = points - %s, last_update = NOW()
                WHERE guild_id = %s AND tribe_name = %s
            """, (amount, guild_id, tribe_name))
        conn.commit()
    finally:
        conn.close()


def update_tribe_points(guild_id: int, tribe_name: str, new_points: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tribe_points (guild_id, tribe_name, points, last_update)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (guild_id, tribe_name)
                DO UPDATE SET points = EXCLUDED.points, last_update = NOW()
            """, (guild_id, tribe_name, new_points))
        conn.commit()
    finally:
        conn.close()


def get_leaderboard(guild_id: int, limit: int = 10):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tribe_name, points FROM tribe_points WHERE guild_id = %s ORDER BY points DESC LIMIT %s", (guild_id, limit))
            return cur.fetchall()
    finally:
        conn.close()


def get_leaderboard_config(guild_id: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT announcement_channel_id, announcement_message, update_interval, last_update FROM leaderboard_config WHERE guild_id = %s", (guild_id,))
            row = cur.fetchone()
            if row:
                return {"channel_id": row[0], "message": row[1], "interval": row[2], "last_update": row[3]}
            return None
    finally:
        conn.close()


def update_leaderboard_config(guild_id: int, channel_id=None, message=None, interval=None):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO leaderboard_config (guild_id, announcement_channel_id, announcement_message, update_interval, last_update)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (guild_id)
                DO UPDATE SET
                    announcement_channel_id = COALESCE(EXCLUDED.announcement_channel_id, leaderboard_config.announcement_channel_id),
                    announcement_message = COALESCE(EXCLUDED.announcement_message, leaderboard_config.announcement_message),
                    update_interval = COALESCE(EXCLUDED.update_interval, leaderboard_config.update_interval),
                    last_update = NOW()
            """, (guild_id, channel_id, message, interval))
        conn.commit()
    finally:
        conn.close()


# ---------- Pending Purchases ----------

def create_purchase(guild_id: int, user_id: int, user_name: str, dino_name: str, blueprint: str, level: int, price: int) -> int:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pending_purchases (guild_id, user_id, user_name, dino_name, blueprint, level, price)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (guild_id, user_id, user_name, dino_name, blueprint, level, price))
            purchase_id = cur.fetchone()[0]
        conn.commit()
        return purchase_id
    finally:
        conn.close()


def get_pending_purchases(guild_id: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, user_name, dino_name, blueprint, level, price, created_at, message_id
                FROM pending_purchases
                WHERE guild_id = %s AND status = 'pending'
                ORDER BY created_at ASC
            """, (guild_id,))
            return [{
                "id": r[0],
                "user_id": r[1],
                "user_name": r[2],
                "dino_name": r[3],
                "blueprint": r[4],
                "level": r[5],
                "price": r[6],
                "created_at": r[7],
                "message_id": r[8],
            } for r in cur.fetchall()]
    finally:
        conn.close()


def get_purchase_by_id(guild_id: int, purchase_id: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, user_name, dino_name, blueprint, level, price, created_at, message_id
                FROM pending_purchases
                WHERE guild_id = %s AND id = %s AND status = 'pending'
            """, (guild_id, purchase_id))
            row = cur.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "user_id": row[1],
                "user_name": row[2],
                "dino_name": row[3],
                "blueprint": row[4],
                "level": row[5],
                "price": row[6],
                "created_at": row[7],
                "message_id": row[8],
            }
    finally:
        conn.close()


def set_purchase_message(guild_id: int, purchase_id: int, message_id: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE pending_purchases
                SET message_id = %s
                WHERE guild_id = %s AND id = %s
            """, (message_id, guild_id, purchase_id))
        conn.commit()
    finally:
        conn.close()


def mark_purchase_done(guild_id: int, purchase_id: int, delivered_by: int = None):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE pending_purchases
                SET status = 'done', delivered_by = %s, delivered_at = NOW()
                WHERE guild_id = %s AND id = %s
            """, (delivered_by, guild_id, purchase_id))
        conn.commit()
    finally:
        conn.close()


def cancel_purchase(guild_id: int, purchase_id: int) -> bool:
    """Mark a purchase as cancelled. Returns True if a pending row was affected."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE pending_purchases
                SET status = 'cancelled'
                WHERE guild_id = %s AND id = %s AND status = 'pending'
            """, (guild_id, purchase_id))
            affected = cur.rowcount > 0
        conn.commit()
        return affected
    finally:
        conn.close()


def get_resolved_purchases_with_message(guild_id: int):
    """Return done/cancelled purchases that still have a posted Discord message, so it can be cleaned up."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, user_name, dino_name, blueprint, level, price, created_at, message_id, status
                FROM pending_purchases
                WHERE guild_id = %s AND status <> 'pending' AND message_id IS NOT NULL
                ORDER BY created_at DESC
            """, (guild_id,))
            return [{
                "id": r[0],
                "user_id": r[1],
                "user_name": r[2],
                "dino_name": r[3],
                "blueprint": r[4],
                "level": r[5],
                "price": r[6],
                "created_at": r[7],
                "message_id": r[8],
                "status": r[9],
            } for r in cur.fetchall()]
    finally:
        conn.close()


def wipe_purchases(guild_id: int):
    """Delete all shop purchase records for a guild."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM pending_purchases WHERE guild_id = %s", (guild_id,))
        conn.commit()
    finally:
        conn.close()
