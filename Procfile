# Koyeb builds this as a single "web" process bound to $PORT.
# The Discord bot is started inside the gunicorn worker by
# post_worker_init in gunicorn.conf.py (single worker = bot singleton).
web: gunicorn --config gunicorn.conf.py wsgi:application
