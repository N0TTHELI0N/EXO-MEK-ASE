"""WSGI entry point — DASHBOARD SERVICE (Koyeb).

Runs independently of the Discord bot. Talks to the same PostgreSQL
database and decrypts the same Fernet-encrypted settings as the Bot
Service, so both see one shared state.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "core"))

from app import app  # noqa: E402

# gunicorn accepts either name; expose both.
application = app

__all__ = ["app", "application"]
