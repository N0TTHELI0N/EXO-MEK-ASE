"""WSGI entry point — BOT SERVICE (Koyeb).

The Discord bot used to be co-hosted with the Flask dashboard in a single
Render container. The dashboard is now its own service (``dashboard-service/``),
so this service no longer serves any dashboard routes: it exposes only a
health/status surface so the platform can probe it, plus a pointer to the
dashboard.

The bot itself is started by the ``post_worker_init`` hook in
``gunicorn.conf.py`` (inside the worker, so it lives as long as the process).
"""

import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

_STARTED_AT = time.time()

# The dashboard lives in a separate service now. Optional: falls back to the
# Koyeb-provided domain of whichever service is running.
DASHBOARD_URL = os.environ.get("DASHBOARD_BASE_URL", "").rstrip("/")


def _info():
    return {
        "status": "ok",
        "service": "mersad-bot",
        "role": "bot",
        "runtime_seconds": int(time.time() - _STARTED_AT),
        "dashboard": DASHBOARD_URL or None,
    }


def application(environ, start_response):
    """Minimal WSGI app — no Flask needed for the bot service."""
    path = environ.get("PATH_INFO", "/")

    if path == "/health":
        body = json.dumps(_info()).encode()
        status = "200 OK"
        ctype = "application/json"
    elif path == "/":
        dash = DASHBOARD_URL
        html = (
            "<!doctype html><meta charset=utf-8>"
            "<title>Mersad — Bot Service</title>"
            "<style>body{{font-family:system-ui;background:#0f1115;color:#e6e6e6;"
            "display:grid;place-items:center;height:100vh;margin:0}}"
            "div{{text-align:center;max-width:32rem;padding:2rem}}"
            "a{{color:#6ea8fe}}</style>"
            "<div><h1>Mersad — Bot Service</h1>"
            "<p>The Discord bot runs here. The web dashboard was moved to its "
            "own service.</p>"
            + (f'<p><a href="{dash}">Open the dashboard →</a></p>' if dash else
               "<p>Set <code>DASHBOARD_BASE_URL</code> to link the dashboard.</p>")
            + "<p><a href='/health'>/health</a></p></div>"
        )
        body = html.encode()
        status = "200 OK"
        ctype = "text/html; charset=utf-8"
    else:
        body = b'{"error":"not found"}'
        status = "404 Not Found"
        ctype = "application/json"

    start_response(
        status,
        [
            ("Content-Type", ctype),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
        ],
    )
    return [body]


# gunicorn accepts either name.
app = application

__all__ = ["app", "application"]
