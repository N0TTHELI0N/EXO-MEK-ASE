"""WSGI entry point for the dashboard (Koyeb / gunicorn).

The Discord bot and the Flask dashboard ship as ONE web service, so this module
only exposes the Flask app; the bot itself is started once per worker by the
``post_worker_init`` hook in ``gunicorn.conf.py``.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "dashboard"))

from dashboard.app import app as application  # noqa: E402
from dashboard.app import app  # noqa: E402,F401

__all__ = ["application", "app"]
