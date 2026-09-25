"""Gunicorn configuration — DASHBOARD SERVICE (Koyeb).

This service runs NO Discord bot: no post_worker_init hook, no gateway
thread. It is a pure web service, so it can be scaled horizontally
(threads, not workers, to keep the psycopg2 pool per-process stable).
"""

import os


def _port() -> int:
    raw = os.environ.get("PORT", "5000").strip() or "5000"
    try:
        return int(raw)
    except ValueError:
        return 5000


bind = f"0.0.0.0:{_port()}"
backlog = 2048

# Threads (not multiple workers) keep one process = one connection pool.
worker_class = "gthread"
workers = 1
threads = int(os.environ.get("WEB_CONCURRENCY", "8"))
worker_connections = 1000

# Dashboard requests can be slow (Nitrado API, SFTP, save downloads),
# so allow long requests but keep a sane ceiling.
timeout = int(os.environ.get("WEB_TIMEOUT", "180"))
graceful_timeout = 30
keepalive = 65
max_requests = 0

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")


def on_starting(server):
    if not os.environ.get("DATABASE_URL"):
        print(
            "[Startup] FATAL-ish: DATABASE_URL is not set — this service "
            "cannot reach the shared PostgreSQL database.",
            flush=True,
        )
    if not os.environ.get("DASHBOARD_SECRET"):
        print(
            "[Startup] WARNING: DASHBOARD_SECRET is not set; sessions will "
            "be invalidated on every restart.",
            flush=True,
        )
    if not os.environ.get("ENCRYPTION_KEY"):
        print(
            "[Startup] WARNING: ENCRYPTION_KEY is not set or invalid — "
            "encrypted Nitrado/API values cannot be decrypted. It MUST be "
            "identical to the Bot Service's ENCRYPTION_KEY.",
            flush=True,
        )
    print(f"[Dashboard] gunicorn binding to 0.0.0.0:{_port()}", flush=True)
