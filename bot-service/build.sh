# Koyeb: (builder defaults to this script when present at the service root)
# Render used a build command; Koyeb can run either, and this script is
# idempotent so it works on both platforms.
pip install --no-cache-dir -r requirements.txt
