"""Gunicorn configuration for Koyeb (and any single-process PaaS).

Why this file exists
--------------------
On Render this project ran as ``web: python run.py``, which meant a single
Python process that manually started a daemon thread for the Discord bot and
then served Flask with the built-in development server.

Koyeb works the same way conceptually (a single ``web`` process bound to
``$PORT``), but the bot must be started *from inside* the worker process,
otherwise gunicorn's master would fork workers that never run the bot and the
Discord gateway session would be tied to a process that gets reaped.

So: the bot is booted from ``post_worker_init`` (runs once, in the worker,
after the fork) and Flask is served by gunicorn's threaded worker class.
``workers=1`` is mandatory -- the Discord bot is a singleton, and a second
worker would cause "Privileged intent required"/duplicate-login errors.
"""

import multiprocessing
import os
import threading
import traceback

# ────────────────────────────────────────────────────────────
#  Socket binding (Koyeb injects $PORT automatically)
# ────────────────────────────────────────────────────────────
def _port() -> int:
    raw = os.environ.get("PORT", "5000").strip() or "5000"
    try:
        return int(raw)
    except ValueError:
        return 5000


bind = f"0.0.0.0:{_port()}"
backlog = 2048

# ────────────────────────────────────────────────────────────
#  Workers
# ────────────────────────────────────────────────────────────
#  1 worker (Discord bot is a singleton) + threaded handling so
#  long-running dashboard requests (Nitrado API, SFTP, backups)
#  do not block the health check or other requests.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("WEB_CONCURRENCY", "8"))
worker_connections = 1000

# ────────────────────────────────────────────────────────────
#  Timeouts
# ────────────────────────────────────────────────────────────
#  The bot holds a long-lived gateway connection, so a worker must never be
#  killed for being "slow". 0 disables the worker timeout entirely.
timeout = 0
graceful_timeout = 30
keepalive = 65

# Recycle workers to avoid leaks from long-lived processes.
max_requests = 0

# ────────────────────────────────────────────────────────────
#  Logging
# ────────────────────────────────────────────────────────────
#  Koyeb collects stdout/stderr, so never write access logs to a file.
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")

# ────────────────────────────────────────────────────────────
#  Bot bootstrap (runs once, inside the worker)
# ────────────────────────────────────────────────────────────
_bot_started = False
_bot_lock = threading.Lock()


def _bot_worker():
    """Run the Discord bot; never let it kill the web process."""
    try:
        import run as run_module

        run_module.run_bot()
    except SystemExit as e:
        print(f"[Bot] Bot exited: {e}", flush=True)
    except Exception:
        print(f"[Bot] FATAL error in bot thread:\n{traceback.format_exc()}", flush=True)


def start_bot():
    global _bot_started
    with _bot_lock:
        if _bot_started:
            return
        _bot_started = True
    print("[Bot] Starting Discord bot thread...", flush=True)
    t = threading.Thread(target=_bot_worker, name="discord-bot", daemon=True)
    t.start()


def post_worker_init(worker):
    """Gunicorn hook: fire the bot once per worker process."""
    start_bot()


def on_starting(server):
    # Fail fast and loudly on the two most common PaaS misconfigurations
    # instead of crashing later with a cryptic stack trace.
    if multiprocessing.cpu_count() and not os.environ.get("DATABASE_URL"):
        print(
            "[Startup] WARNING: DATABASE_URL is not set. "
            "The bot and dashboard will fail on first DB access.",
            flush=True,
        )
    print(f"[Startup] gunicorn binding to 0.0.0.0:{_port()}", flush=True)


def child_exit(server, worker):
    print(f"[Startup] worker {worker.pid} exited", flush=True)
