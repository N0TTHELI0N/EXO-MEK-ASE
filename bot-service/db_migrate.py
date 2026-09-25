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

Why migrations get their own connection
---------------------------------------
``guild_settings.get_conn()`` returns a pooled ``_PooledConnection`` proxy
whose ``close()`` hands the socket back to the idle pool and then drops the
proxy. The six migration helpers each call ``conn.close()`` in a ``finally``
block, so running them back-to-back on pooled connections makes every helper
after the first fight over a connection the previous one just released, and
psycopg2 surfaces that as ``InterfaceError: cursor already closed``.

A migration must instead be one atomic unit on one connection. So this module
opens its own raw connection, hands out a *non-closing* shim around it, and
closes the real socket exactly once at the very end.
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


# Statements are all DDL guarded by IF NOT EXISTS, so a failed run leaves the
# database in a clean state and the retry is always safe.
_CONNECT_ATTEMPTS = 2
_STATEMENT_TIMEOUT_MS = 120_000


class _MigrationConnection:
    """Forwards to a raw psycopg2 connection but ignores ``close()``.

    The migration helpers in this project all end with ``conn.close()`` in a
    ``finally``. On a pooled connection that releases the socket, so the next
    helper runs against a connection the previous one just gave back - the
    source of ``InterfaceError: cursor already closed``. Here ``close()`` is a
    no-op and the real socket is closed once, by the caller.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw):
        object.__setattr__(self, "_raw", raw)

    # --- explicit pass-throughs (never via __getattr__, so that dunder
    #     lookups on the proxy cannot reach a dead socket) ---
    def __enter__(self):
        self._raw.__enter__()
        return self

    def __exit__(self, *exc):
        return self._raw.__exit__(*exc)

    def cursor(self, *a, **kw):
        return self._raw.cursor(*a, **kw)

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        """Deliberately does nothing - see the class docstring."""

    @property
    def closed(self):
        return self._raw.closed

    @property
    def autocommit(self):
        return self._raw.autocommit

    @autocommit.setter
    def autocommit(self, value):
        self._raw.autocommit = value


def _open_migration_connection():
    import psycopg2

    raw = psycopg2.connect(
        os.environ["DATABASE_URL"],
        connect_timeout=10,
        application_name="mersad-migrate",
        keepalives=1,
    )
    raw.autocommit = False
    # Fail loudly instead of hanging the worker boot on a lock.
    with raw.cursor() as cur:
        cur.execute(f"SET statement_timeout = {_STATEMENT_TIMEOUT_MS}")
    raw.commit()
    return raw


def _migration_targets():
    """(label, callable) pairs for every schema owner, in dependency order."""
    import guild_settings
    import shop_db

    targets = [
        ("guild_settings", guild_settings.init_db),
        ("shop_db", shop_db.init_shop_db),
        ("leaderboard", shop_db.init_leaderboard_db),
    ]
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
        targets.append((f"{module}.{attr}", getattr(mod, attr)))
    return targets


def _run_once() -> None:
    import guild_settings

    raw = _open_migration_connection()
    shim = _MigrationConnection(raw)
    original_get_conn = guild_settings.get_conn
    guild_settings.get_conn = lambda: shim
    try:
        for label, fn in _migration_targets():
            try:
                fn()
                _log(f"ok: {label}")
            except Exception as exc:
                _log(f"FAILED: {label}: {exc!r}")
                raise
        # One commit for the whole schema. Every statement is IF NOT EXISTS,
        # so this is atomic in the only way that matters here: either the
        # fresh database ends up fully migrated, or it is untouched and the
        # next attempt starts clean.
        raw.commit()
    except Exception:
        try:
            raw.rollback()
        except Exception:
            pass
        raise
    finally:
        guild_settings.get_conn = original_get_conn
        try:
            raw.close()
        except Exception:
            pass


def run_all_migrations() -> None:
    """Create or update every table this project owns. Safe to re-run."""
    if not os.environ.get("DATABASE_URL"):
        _log("SKIPPED: DATABASE_URL is not set.")
        return

    _bootstrap_path()

    for attempt in range(1, _CONNECT_ATTEMPTS + 1):
        try:
            _run_once()
            _log("schema is up to date.")
            return
        except Exception as exc:
            _log(f"attempt {attempt}/{_CONNECT_ATTEMPTS} failed: {exc!r}")
            if attempt == _CONNECT_ATTEMPTS:
                _log("giving up - the service will fail on first DB access.")
                raise
            _log("retrying with a fresh connection...")


if __name__ == "__main__":
    run_all_migrations()
