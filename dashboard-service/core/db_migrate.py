"""Canonical database migration entry point.

Every schema change in this project is expressed as an idempotent
``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE`` block. There is no separate
migrations folder and no Alembic: these functions *are* the schema, and they
can be re-run against a populated database without doing anything.

Why this module exists
----------------------
The three migration entry points used to live in places that never execute
under a PaaS process manager:

* ``bot-service/run.py``          - only runs for ``python run.py``
* ``dashboard-service/app.py``    - only runs under ``if __name__ == "__main__"``

Both services are actually started by gunicorn as ``wsgi:application``, so
``__name__`` is ``"wsgi"`` and ``run.py`` is never imported. The result was a
fresh database that never got its schema, and every request failing with
``relation "guild_settings" does not exist``.

Both gunicorn configs now call :func:`run_all_migrations` from
``post_worker_init``, which runs *inside the worker process* - never in the
master, because the master forks and an inherited PostgreSQL socket is
exactly the failure mode that caused the earlier ``on_starting`` deadlock.
"""

import os
import sys


def _bootstrap_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (here, os.path.join(here, "core")):
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)


def _log(msg: str) -> None:
    print(f"[migrate] {msg}", flush=True)


def run_all_migrations() -> None:
    """Create or update every table this project owns. Safe to re-run."""
    if not os.environ.get("DATABASE_URL"):
        _log("SKIPPED: DATABASE_URL is not set.")
        return

    _bootstrap_path()

    import guild_settings
    import shop_db

    for label, fn in (
        ("guild_settings", guild_settings.init_db),
        ("shop_db", shop_db.init_shop_db),
        ("leaderboard", shop_db.init_leaderboard_db),
    ):
        try:
            fn()
            _log(f"ok: {label}")
        except Exception as exc:
            _log(f"FAILED: {label}: {exc!r}")

    # Tables owned by individual cogs. Those modules live only in the Bot
    # Service (bot-service/cogs/), so on the Dashboard Service they are
    # genuinely absent and the Bot Service creates them on its own deploy.
    for module, attr in (
        ("cogs.playerlog", "_init_db"),
        ("cogs.whitelist", "_init_whitelist_db"),
        ("cogs.server_backup", "_init_backup_db"),
    ):
        try:
            mod = __import__(module, fromlist=[attr])
        except ImportError:
            _log(f"skip: {module} (not present in this service)")
            continue
        try:
            getattr(mod, attr)()
            _log(f"ok: {module}.{attr}")
        except Exception as exc:
            _log(f"FAILED: {module}.{attr}: {exc!r}")

    _log("schema is up to date.")


if __name__ == "__main__":
    run_all_migrations()
