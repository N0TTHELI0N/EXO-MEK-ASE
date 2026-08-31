import os
import io
import json
import secrets
import shutil
import tempfile
import zipfile
import requests
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from flask import Flask, redirect, request, session, render_template, jsonify, url_for, send_file, send_from_directory
from functools import wraps
import sys
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import guild_settings
import shop_db
import nitrado
from security import validate_path
from translations import TRANSLATIONS, DASHBOARD_DEFAULT_LANG, DASHBOARD_LANGS

def _lang_from_session():
    lang = session.get("_lang", DASHBOARD_DEFAULT_LANG)
    if lang not in DASHBOARD_LANGS:
        lang = DASHBOARD_DEFAULT_LANG
    return lang

# Cache of content overrides, loaded once per request for performance.
_CONTENT_OVERRIDES = {}

def _t(key, lang=None):
    lang = lang or _lang_from_session()
    override = _CONTENT_OVERRIDES.get(key, {})
    if override.get(lang):
        return override[lang]
    return TRANSLATIONS.get(key, {}).get(lang, TRANSLATIONS.get(key, {}).get(DASHBOARD_DEFAULT_LANG, key))

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("DASHBOARD_SECRET", secrets.token_hex(32))

# Official ARK: Survival Evolved maps -> PlayStation save folder names.
# Save files (.ark) live under ShooterGame/Saved/SavedArks/<folder>/
ARK_MAPS = [
    {"name": "The Island", "folder": "TheIsland_P"},
    {"name": "The Center", "folder": "TheCenter_P"},
    {"name": "Scorched Earth", "folder": "ScorchedEarth_P"},
    {"name": "Ragnarok", "folder": "Ragnarok_P"},
    {"name": "Aberration", "folder": "Aberration_P"},
    {"name": "Extinction", "folder": "Extinction_P"},
    {"name": "Valguero", "folder": "Valguero_P"},
    {"name": "Genesis Part 1", "folder": "Genesis_P"},
    {"name": "Genesis Part 2", "folder": "Gen2_P"},
    {"name": "Crystal Isles", "folder": "CrystalIsles_P"},
    {"name": "Lost Island", "folder": "LostIsland_P"},
    {"name": "Fjordur", "folder": "Fjordur_P"},
]


@app.before_request
def _load_content_overrides():
    global _CONTENT_OVERRIDES
    try:
        _CONTENT_OVERRIDES = guild_settings.get_all_content_overrides()
    except Exception:
        _CONTENT_OVERRIDES = {}

@app.before_request
def _set_template_globals():
    app.jinja_env.globals['t'] = _t
    app.jinja_env.globals['LANGS'] = DASHBOARD_LANGS
    app.jinja_env.globals['DASHBOARD_LANG'] = _lang_from_session()

app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "0"))

def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']

app.jinja_env.globals['csrf_token'] = generate_csrf_token
app.jinja_env.globals['BOT_OWNER_ID'] = BOT_OWNER_ID

def validate_csrf(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in ("POST", "PUT", "DELETE"):
            token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
            if not token or token != session.get('_csrf_token'):
                return "CSRF token missing or invalid", 403
        return f(*args, **kwargs)
    return decorated

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")
DISCORD_API_BASE = "https://discord.com/api/v10"
BOT_TOKEN = os.environ.get("DISCORD_TOKEN", "")


# ────────────────────────────────────────────────────────────
#  Simple Rate Limiter
# ────────────────────────────────────────────────────────────
from collections import defaultdict
import time

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 30

def check_rate_limit(key: str) -> bool:
    now = time.time()
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[key]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit_store[key].append(now)
    return True


# ────────────────────────────────────────────────────────────
#  Auth Helpers
# ────────────────────────────────────────────────────────────

def get_current_user():
    return session.get("user")


def get_user_guilds():
    token = session.get("access_token")
    if not token:
        return []
    resp = requests.get(
        f"{DISCORD_API_BASE}/users/@me/guilds",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    return [g for g in resp.json() if int(g.get("permissions", 0)) & 0x20]


def get_bot_guilds():
    if not BOT_TOKEN:
        return []
    resp = requests.get(
        f"{DISCORD_API_BASE}/users/@me/guilds",
        headers={"Authorization": f"Bot {BOT_TOKEN}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    return resp.json()


def get_mutual_guilds():
    user_guilds = {g["id"]: g for g in get_user_guilds()}
    bot_guilds = {g["id"]: g for g in get_bot_guilds()}
    return [user_guilds[gid] for gid in set(user_guilds) & set(bot_guilds)]


def get_guild_roles(guild_id):
    if not BOT_TOKEN:
        return []
    resp = requests.get(
        f"{DISCORD_API_BASE}/guilds/{guild_id}/roles",
        headers={"Authorization": f"Bot {BOT_TOKEN}"},
        timeout=10,
    )
    if resp.status_code != 200:
        return []
    roles = resp.json()
    roles.sort(key=lambda r: r.get("position", 0), reverse=True)
    return [{"id": int(r["id"]), "name": r["name"]} for r in roles if r.get("name") != "@everyone"]


def get_guild_name(guild_id):
    bot_guilds = get_bot_guilds()
    for g in bot_guilds:
        if str(g["id"]) == str(guild_id):
            return g.get("name", f"Server {guild_id}")
    return f"Server {guild_id}"


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def guild_admin_required(f):
    @wraps(f)
    def decorated(guild_id, *args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect(url_for("login"))
        user_id = str(user.get("id", ""))
        is_owner = bool(BOT_OWNER_ID) and user_id == str(BOT_OWNER_ID)

        user_guilds = {g["id"]: g for g in get_user_guilds()}
        admin_guilds = {g["id"]: g for g in get_bot_guilds()}

        # Owner gains access to any of the bot's servers (bypasses flaky user-token checks)
        if is_owner and str(guild_id) in admin_guilds:
            return f(guild_id, *args, **kwargs)

        if str(guild_id) not in admin_guilds:
            app.logger.warning(
                "guild_admin_required: guild %s not in bot's servers (raise_bot_or_check_bot_token)",
                guild_id,
            )

        if str(guild_id) not in user_guilds:
            return "You don't have access to this server.", 403

        guild_perms = int(user_guilds[str(guild_id)].get("permissions", 0))
        ADMINISTRATOR_FLAG = 0x8
        if not (guild_perms & ADMINISTRATOR_FLAG):
            return "You need Administrator permission to access this.", 403

        return f(guild_id, *args, **kwargs)
    return decorated


def nitrado_client_for(guild_id):
    cfg = guild_settings.get_nitrado_config(guild_id)
    token = cfg.get("api_token")
    service_id = cfg.get("service_id")
    if not token or not service_id:
        return None
    from nitrado import NitradoClient
    return NitradoClient(token, service_id)


def owner_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user or int(user.get("id", 0)) != BOT_OWNER_ID:
            return "Access denied.", 403
        return f(*args, **kwargs)
    return decorated


# ────────────────────────────────────────────────────────────
#  Auth Routes
# ────────────────────────────────────────────────────────────

@app.route("/login")
def login():
    if not DISCORD_CLIENT_ID:
        return "DISCORD_CLIENT_ID is not configured. Set it in your environment variables.", 500
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state
    redirect_uri = DISCORD_REDIRECT_URI
    if not redirect_uri or redirect_uri.startswith("http://localhost"):
        redirect_uri = request.url_root.rstrip("/") + "/callback"
    session["oauth_redirect_uri"] = redirect_uri
    from urllib.parse import quote
    return redirect(
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={quote(redirect_uri)}"
        f"&response_type=code"
        f"&scope=identify+guilds"
        f"&state={state}"
    )


@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    if error:
        error_desc = request.args.get("error_description", error)
        return f"Discord OAuth error: {error_desc}", 403
    if not code:
        return "No authorization code received from Discord.", 400
    if state != session.get("oauth_state"):
        return "Invalid state parameter. Please try logging in again.", 403
    redirect_uri = session.get("oauth_redirect_uri")
    if not redirect_uri:
        redirect_uri = DISCORD_REDIRECT_URI
        if not redirect_uri or redirect_uri.startswith("http://localhost"):
            redirect_uri = request.url_root.rstrip("/") + "/callback"
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    resp = requests.post("https://discord.com/api/oauth2/token", data=data, timeout=10)
    if resp.status_code != 200:
        return f"Failed to authenticate with Discord (HTTP {resp.status_code}). Check your DISCORD_CLIENT_SECRET.", 403
    token_data = resp.json()
    if "access_token" not in token_data:
        return f"Discord did not return an access token. Error: {token_data.get('error', 'unknown')}", 403
    session["access_token"] = token_data["access_token"]
    user_resp = requests.get(
        f"{DISCORD_API_BASE}/users/@me",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
        timeout=10,
    )
    if user_resp.status_code == 200:
        session["user"] = user_resp.json()
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/lang/<lang>")
def set_language(lang):
    if lang in DASHBOARD_LANGS:
        session["_lang"] = lang
    return redirect(request.referrer or url_for("home"))


# ────────────────────────────────────────────────────────────
#  Admin License Management (Owner Only)
# ────────────────────────────────────────────────────────────

@app.route("/admin/licenses")
@login_required
@owner_required
@validate_csrf
def admin_licenses():
    licenses = guild_settings.get_all_licenses()
    return render_template(
        "licenses.html",
        user=get_current_user(),
        licenses=licenses,
        message=request.args.get("message", ""),
        message_type=request.args.get("type", "success"),
    )


@app.route("/admin/licenses/create", methods=["POST"])
@login_required
@owner_required
@validate_csrf
def admin_license_create():
    guild_id_str = request.form.get("guild_id", "").strip()
    duration = request.form.get("duration", "30").strip()
    if not guild_id_str or not guild_id_str.isdigit():
        return redirect(url_for("admin_licenses", message="Invalid Guild ID.", type="error"))
    guild_id = int(guild_id_str)
    try:
        days = max(1, min(3650, int(duration)))
    except ValueError:
        days = 30
    key = guild_settings.create_license_for_guild(guild_id, days)
    return redirect(url_for("admin_licenses", message=f"License created: {key} ({days} days)", type="success"))


@app.route("/admin/licenses/revoke", methods=["POST"])
@login_required
@owner_required
@validate_csrf
def admin_license_revoke():
    guild_id_str = request.form.get("guild_id", "").strip()
    if not guild_id_str or not guild_id_str.isdigit():
        return redirect(url_for("admin_licenses", message="Invalid Guild ID.", type="error"))
    guild_id = int(guild_id_str)
    guild_settings.update_setting(guild_id, "license_key", "")
    guild_settings.update_setting(guild_id, "license_days", 0)
    guild_settings.update_setting(guild_id, "license_created", None)
    return redirect(url_for("admin_licenses", message=f"License revoked for guild {guild_id}.", type="success"))


# ────────────────────────────────────────────────────────────
#  Admin Content Customization (Owner Only)
#  Lets the owner edit any dashboard text (Arabic/English)
#  live from the database, without redeploying.
# ────────────────────────────────────────────────────────────

@app.route("/admin/content")
@login_required
@owner_required
def admin_content():
    overrides = guild_settings.get_all_content_overrides()
    # Build a list of all known keys from defaults + any custom override keys
    known = set(TRANSLATIONS.keys())
    known |= set(overrides.keys())
    keys = sorted(known)
    return render_template(
        "content_admin.html",
        user=get_current_user(),
        keys=keys,
        overrides=overrides,
        message=request.args.get("message", ""),
        message_type=request.args.get("type", "success"),
    )


@app.route("/admin/content/save", methods=["POST"])
@login_required
@owner_required
@validate_csrf
def admin_content_save():
    content_key = request.form.get("content_key", "").strip()
    lang = request.form.get("lang", "").strip()
    value = request.form.get("value", "").strip()
    if not content_key or lang not in DASHBOARD_LANGS:
        return redirect(url_for("admin_content", message="Invalid key or language.", type="error"))
    guild_settings.set_content_override(content_key, lang, value)
    return redirect(url_for("admin_content", message=f"Saved ({content_key}) in {lang}.", type="success"))


@app.route("/admin/content/delete", methods=["POST"])
@login_required
@owner_required
@validate_csrf
def admin_content_delete():
    content_key = request.form.get("content_key", "").strip()
    lang = request.form.get("lang", "").strip()
    if not content_key:
        return redirect(url_for("admin_content", message="Missing key.", type="error"))
    guild_settings.delete_content_override(content_key, lang or None)
    return redirect(url_for("admin_content", message=f"Reset ({content_key}) to default.", type="success"))


# ────────────────────────────────────────────────────────────
#  Main Routes
# ────────────────────────────────────────────────────────────

@app.route("/")
def home():
    return render_template("home.html", user=get_current_user())


@app.route("/setup")
def setup():
    invite = (
        f"https://discord.com/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
        f"&permissions=8&scope=bot"
        if DISCORD_CLIENT_ID
        else "#"
    )
    return render_template("setup.html", user=get_current_user(), invite_url=invite)


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "servers.html",
        user=get_current_user(),
        guilds=get_mutual_guilds(),
    )


@app.route("/dashboard/<int:guild_id>")
@login_required
@guild_admin_required
def guild_overview(guild_id):
    return redirect(url_for("section_overview", guild_id=guild_id))


# ────────────────────────────────────────────────────────────
#  Section Routes
# ────────────────────────────────────────────────────────────

@app.route("/dashboard/<int:guild_id>/overview")
@login_required
@guild_admin_required
def section_overview(guild_id):
    settings = guild_settings.get_settings(guild_id)
    conn = guild_settings.get_conn()
    stats = {"total_dinos": 0, "linked_players": 0, "active_warnings": 0, "total_backups": 0}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM shop_dinos WHERE guild_id = %s", (guild_id,))
            stats["total_dinos"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM linked_players WHERE guild_id = %s", (guild_id,))
            stats["linked_players"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM warnings WHERE guild_id = %s AND active = true", (guild_id,))
            stats["active_warnings"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM backup_records WHERE guild_id = %s", (guild_id,))
            stats["total_backups"] = cur.fetchone()[0]
    except Exception:
        pass
    finally:
        conn.close()
    return render_template(
        "sections/overview.html",
        user=get_current_user(),
        guild_id=guild_id,
        guild_name=get_guild_name(guild_id),
        active_section="overview",
        settings=settings,
        license_valid=guild_settings.is_license_valid(guild_id),
        stats=stats,
    )


@app.route("/dashboard/<int:guild_id>/nitrado", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_nitrado(guild_id):
    if request.method == "POST":
        action = request.form.get("service_action", "")
        if action == "add":
            guild_settings.add_nitrado_service(
                guild_id,
                request.form.get("svc_name", ""),
                request.form.get("svc_service_id", ""),
                request.form.get("svc_api_token", ""),
            )
        elif action == "select":
            try:
                guild_settings.set_active_nitrado_service(guild_id, int(request.form.get("svc_id", "0")))
            except Exception:
                pass
        elif action == "rename":
            try:
                guild_settings.update_nitrado_display_name(
                    guild_id,
                    int(request.form.get("svc_id", "0")),
                    request.form.get("svc_display_name", ""),
                )
            except Exception:
                pass
        elif action == "delete":
            try:
                guild_settings.delete_nitrado_service(guild_id, int(request.form.get("svc_id", "0")))
            except Exception:
                pass
        elif action == "legacy":
            nitrado_token = request.form.get("nitrado_api_token", "")
            if nitrado_token:
                guild_settings.update_setting(guild_id, "nitrado_api_token", nitrado_token)
            guild_settings.update_setting(guild_id, "nitrado_service_id", request.form.get("nitrado_service_id", ""))
            guild_settings.update_setting(guild_id, "nitrado_display_name", request.form.get("nitrado_display_name", ""))
        return redirect(url_for("section_nitrado", guild_id=guild_id))
    services = guild_settings.list_nitrado_services(guild_id)
    return render_template(
        "sections/nitrado.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="nitrado",
        settings=guild_settings.get_settings(guild_id),
        services=services,
        services_count=len(services),
    )


@app.route("/dashboard/<int:guild_id>/license", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_license(guild_id):
    if request.method == "POST":
        key = request.form.get("license_key", "").strip()
        if guild_settings.verify_license_key(guild_id, key):
            # Valid key that matches the stored one - nothing to overwrite, just confirm.
            pass
        else:
            # The supplied key is not the valid license for this server.
            return redirect(url_for("section_license", guild_id=guild_id, license_error="invalid"))
        return redirect(url_for("section_license", guild_id=guild_id, license_ok="1"))
    return render_template(
        "sections/license.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="license",
        settings=guild_settings.get_settings(guild_id),
        license_valid=guild_settings.is_license_valid(guild_id),
        license_expiry=guild_settings.get_license_expiry(guild_id),
        license_error=request.args.get("license_error", ""),
        license_ok=request.args.get("license_ok", ""),
    )


@app.route("/dashboard/<int:guild_id>/shop", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_shop(guild_id):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            shop_db.add_shop_dino(
                guild_id,
                request.form.get("name", ""),
                request.form.get("blueprint", ""),
                int(request.form.get("min_level", 1)),
                int(request.form.get("max_level", 150)),
                int(request.form.get("price", 0)),
                request.form.get("category", "General"),
            )
        elif action == "remove":
            shop_db.remove_shop_dino(guild_id, request.form.get("name", ""))
        elif action in ("deliver_pending", "cancel_pending"):
            try:
                purchase_id = int(request.form.get("purchase_id", 0))
            except (TypeError, ValueError):
                purchase_id = 0
            _handle_pending_shop_action(guild_id, action, purchase_id)
        return redirect(url_for("section_shop", guild_id=guild_id))
    return render_template(
        "sections/shop.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="shop",
        dinos=shop_db.get_all_shop_dinos(guild_id),
        pending=shop_db.get_pending_purchases(guild_id),
        pending_channel_set=bool(guild_settings.get_setting(guild_id, "shop_pending_channel", 0)),
        done_channel_set=bool(guild_settings.get_setting(guild_id, "shop_done_channel", 0)),
    )


def _handle_pending_shop_action(guild_id: int, action: str, purchase_id: int):
    """Deliver or cancel a pending purchase from the dashboard (sync-friendly)."""
    purchase = shop_db.get_purchase_by_id(guild_id, purchase_id)
    if not purchase:
        return
    if action == "deliver_pending":
        class_name = purchase["blueprint"]
        if "Blueprint'" in class_name:
            class_name = class_name.split('.')[-1].rstrip("'").strip()
        if not class_name.endswith("_C"):
            class_name += "_C"
        cmd = f'GMSummon "{class_name}" {purchase["level"]}'
        result = nitrado.send_rcon(guild_id, cmd)
        if result is None:
            return  # failed to reach server; leave pending for retry
        shop_db.mark_purchase_done(guild_id, purchase_id)
        guild_settings.log_action(guild_id, "leaderboard", None, None, purchase["dino_name"],
                                  sub_type="purchase_delivered", details={"level": purchase["level"], "purchase_id": purchase_id, "source": "dashboard", "command": cmd})
    elif action == "cancel_pending":
        if shop_db.cancel_purchase(guild_id, purchase_id):
            shop_db.add_points(guild_id, purchase["user_name"], purchase["price"])
        guild_settings.log_action(guild_id, "leaderboard", None, None, purchase["dino_name"],
                                  sub_type="purchase_cancelled", details={"purchase_id": purchase_id, "refund": purchase["price"], "source": "dashboard"})


@app.route("/dashboard/<int:guild_id>/custom-commands", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_custom_commands(guild_id):
    if request.method == "POST":
        app_action = request.form.get("app_action")
        if app_action == "toggle_runner":
            current = guild_settings.get_bool_setting(guild_id, "runner_enabled", False)
            guild_settings.update_setting(guild_id, "runner_enabled", "0" if current else "1")
        elif app_action == "add_custom":
            name = request.form.get("name", "").strip().lower().replace(" ", "-")
            command_string = request.form.get("command_string", "").strip()
            category = request.form.get("category") or None
            if name and command_string:
                guild_settings.add_custom_command(guild_id, name, command_string, category)
        elif app_action == "update_custom":
            name = request.form.get("name", "").strip()
            command_string = request.form.get("command_string", "").strip() or None
            category = request.form.get("category") or None
            enabled = request.form.get("enabled")
            guild_settings.update_custom_command(guild_id, name, command_string, category,
                                                 True if enabled != "0" else False)
        elif app_action == "delete_custom":
            name = request.form.get("name", "").strip()
            guild_settings.remove_custom_command(guild_id, name)
        elif app_action == "toggle_enable":
            name = request.form.get("name", "").strip()
            enabled_str = request.form.get("enabled", "")
            enabled = enabled_str != "0"
            guild_settings.update_custom_command(guild_id, name, enabled=enabled)
        elif app_action == "save_rules":
            rules = {}
            for cat in ["dino_spawn", "gfi", "player", "gcm"]:
                raw = request.form.get(f"rules_{cat}", "").strip()
                if raw:
                    rules[cat] = [k.strip() for k in raw.split(",") if k.strip()]
            guild_settings.set_category_rules(guild_id, rules)
        return redirect(url_for("section_custom_commands", guild_id=guild_id))
    return render_template(
        "sections/custom_commands.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="custom-commands",
        runner_enabled=guild_settings.get_bool_setting(guild_id, "runner_enabled", False),
        custom_commands=guild_settings.get_custom_commands(guild_id),
        category_rules=guild_settings.get_category_rules(guild_id),
        forum_cfg=guild_settings.get_forum_log_config(guild_id),
        shop_forum_cfg=guild_settings.get_shop_forum_config(guild_id),
    )


@app.route("/dashboard/<int:guild_id>/points", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_points(guild_id):
    if request.method == "POST":
        action = request.form.get("action")
        tribe = request.form.get("tribe_name", "").strip()
        amount = int(request.form.get("amount", 0))
        if action == "add" and tribe and amount > 0:
            shop_db.add_points(guild_id, tribe, amount)
        elif action == "remove" and tribe and amount > 0:
            shop_db.remove_points(guild_id, tribe, amount)
        return redirect(url_for("section_points", guild_id=guild_id))
    search = request.args.get("search", "").strip()
    leaderboard = shop_db.get_leaderboard(guild_id, limit=100)
    return render_template(
        "sections/points.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="points",
        leaderboard=leaderboard,
        search=search,
    )


@app.route("/dashboard/<int:guild_id>/whitelist", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_whitelist(guild_id):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "set_restart_time":
            hour = int(request.form.get("hour", 3))
            minute = int(request.form.get("minute", 0))
            guild_settings.update_setting(guild_id, "restart_schedule", {"hour": hour, "minute": minute})
        elif action == "set_whitelist_path":
            guild_settings.update_setting(guild_id, "whitelist_path", request.form.get("whitelist_path", ""))
        return redirect(url_for("section_whitelist", guild_id=guild_id))
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT discord_id, psn_id, status, linked_at FROM linked_players WHERE guild_id = %s", (guild_id,))
            linked_players = cur.fetchall()
    finally:
        conn.close()
    return render_template(
        "sections/whitelist.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="whitelist",
        settings=guild_settings.get_settings(guild_id),
        linked_players=linked_players,
    )


@app.route("/dashboard/<int:guild_id>/tribelog", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_tribelog(guild_id):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "config":
            conn = guild_settings.get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO tribe_log_config (guild_id) VALUES (%s) ON CONFLICT (guild_id) DO NOTHING", (guild_id,))
                    cur.execute("UPDATE tribe_log_config SET enabled=%s WHERE guild_id=%s",
                                (request.form.get("enabled") in ("on", "1", "true"), guild_id))
                    cur.execute("UPDATE tribe_log_config SET channel_id=%s WHERE guild_id=%s",
                                (int(request.form["channel_id"]) if request.form.get("channel_id") else None, guild_id))
                    source = request.form.get("source_type") or request.form.get("log_source", "file")
                    cur.execute("UPDATE tribe_log_config SET log_source=%s WHERE guild_id=%s",
                                (source, guild_id))
                    path = request.form.get("log_file_path") or request.form.get("log_path", "")
                    cur.execute("UPDATE tribe_log_config SET log_path=%s WHERE guild_id=%s",
                                (path, guild_id))
                conn.commit()
            finally:
                conn.close()
        elif action == "add_tribe":
            tribe_name = request.form.get("tribe_name", "").strip()
            if tribe_name:
                conn = guild_settings.get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO known_tribes (guild_id, tribe_name) VALUES (%s, %s) ON CONFLICT DO NOTHING", (guild_id, tribe_name))
                    conn.commit()
                finally:
                    conn.close()
        elif action == "remove_tribe":
            tribe_name = request.form.get("tribe_name", "").strip()
            if tribe_name:
                conn = guild_settings.get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM known_tribes WHERE guild_id = %s AND tribe_name = %s", (guild_id, tribe_name))
                    conn.commit()
                finally:
                    conn.close()
        elif action == "wipe_tribe_logs":
            if session.get("user", {}).get("id") != BOT_OWNER_ID:
                return redirect(url_for("section_tribelog", guild_id=guild_id) + "?notice=" + "owner only").replace(" ", "+")
            guild_settings.wipe_tribe_logs(guild_id)
            return redirect(url_for("section_tribelog", guild_id=guild_id) + "?notice=wiped")
        return redirect(url_for("section_tribelog", guild_id=guild_id))
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT enabled, channel_id, log_source, log_path FROM tribe_log_config WHERE guild_id = %s", (guild_id,))
            row = cur.fetchone()
            cur.execute("SELECT tribe_name FROM known_tribes WHERE guild_id = %s", (guild_id,))
            known_tribes = [r[0] for r in cur.fetchall()]
    finally:
        conn.close()
    tribe_config = {
        "enabled": bool(row[0]) if row else False,
        "channel_id": row[1] if row else None,
        "source_type": (row[2] if row else None) or "file",
        "log_file_path": (row[3] if row else None) or "",
    }
    forum_cfg = guild_settings.get_tribe_forum_config(guild_id) or {}
    tribe_counts = guild_settings.get_tribe_event_counts(guild_id)
    tribe_events = guild_settings.get_tribe_log_events(guild_id, limit=200)
    return render_template(
        "sections/tribelog.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="tribelog",
        tribe_config=tribe_config,
        tribes=known_tribes,
        tribe_forum=forum_cfg,
        tribe_threads=forum_cfg.get("threads", {}),
        tribe_counts=tribe_counts,
        tribe_events=tribe_events,
        is_owner=(get_current_user() or {}).get("id") == BOT_OWNER_ID,
    )


@app.route("/dashboard/<int:guild_id>/automod", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_automod(guild_id):
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "add_word":
            new_word = request.form.get("new_word", "").strip()
            if new_word:
                guild_settings.add_automod_word(guild_id, new_word, session.get("user", {}).get("id"))
                guild_settings.log_action(
                    guild_id, "automod", session.get("user", {}).get("id"),
                    session.get("user", {}).get("username"), None,
                    sub_type="word_added", details={"word": new_word}
                )
        elif action == "remove_word":
            word_id = request.form.get("word_id")
            if word_id:
                conn = guild_settings.get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT word FROM automod_custom_words WHERE id = %s AND guild_id = %s", (word_id, guild_id))
                        row = cur.fetchone()
                        if row:
                            guild_settings.remove_automod_word(guild_id, row[0])
                            guild_settings.log_action(
                                guild_id, "automod", session.get("user", {}).get("id"),
                                session.get("user", {}).get("username"), None,
                                sub_type="word_removed", details={"word": row[0]}
                            )
                finally:
                    conn.close()
        else:
            # Default save settings
            guild_settings.update_setting(guild_id, "automod_enabled", request.form.get("automod_enabled") == "on")
            guild_settings.update_setting(guild_id, "automod_log_channel_id",
                                           int(request.form["automod_log_channel_id"]) if request.form.get("automod_log_channel_id") else None)
            guild_settings.update_setting(guild_id, "automod_language", request.form.get("automod_language", "en"))
        
        return redirect(url_for("section_automod", guild_id=guild_id))
    
    # Get custom words for display
    custom_words = guild_settings.get_automod_words_with_info(guild_id)
    
    return render_template(
        "sections/automod.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="automod",
        settings=guild_settings.get_settings(guild_id),
        custom_words=custom_words,
    )


@app.route("/dashboard/<int:guild_id>/punishments", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_punishments(guild_id):
    if request.method == "POST":
        action = request.form.get("action")
        if action == "set_threshold":
            guild_settings.update_setting(guild_id, "warning_threshold", int(request.form.get("threshold", 3)))
            guild_settings.update_setting(guild_id, "warning_punishment", request.form.get("warning_punishment", "ban"))
        elif action == "set_log_channel":
            guild_settings.update_setting(guild_id, "punishment_log_channel_id",
                                           int(request.form["punishment_log_channel_id"]) if request.form.get("punishment_log_channel_id") else None)
        elif action == "clear_warnings":
            player = request.form.get("player", "").strip()
            if player:
                guild_settings.clear_warnings(guild_id, player)
        return redirect(url_for("section_punishments", guild_id=guild_id))
    search_player = request.args.get("player", "").strip()
    warnings = []
    punishments = []
    if search_player:
        warnings = guild_settings.get_warnings(guild_id, search_player)
        punishments = guild_settings.get_punishments(guild_id, search_player)
    return render_template(
        "sections/punishments.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="punishments",
        settings=guild_settings.get_settings(guild_id),
        warnings=warnings,
        punishments=punishments,
        search_player=search_player,
    )


@app.route("/dashboard/<int:guild_id>/embeds", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_embeds(guild_id):
    if request.method == "POST":
        embed_key = request.form.get("embed_key")
        if embed_key:
            guild_settings.set_embed_template(
                guild_id,
                embed_key,
                title=request.form.get("title", ""),
                description=request.form.get("description", ""),
                color=request.form.get("color", "#FFD700"),
                image_url=request.form.get("image_url", ""),
                thumbnail_url=request.form.get("thumbnail_url", ""),
                footer_text=request.form.get("footer_text", ""),
                author_name=request.form.get("author_name", ""),
            )
        return redirect(url_for("section_embeds", guild_id=guild_id))
    return render_template(
        "sections/embeds.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="embeds",
        embeds=guild_settings.get_all_embed_templates(guild_id) or {},
        embed_keys=list(guild_settings.DEFAULT_EMBEDS.keys()),
    )


def _create_local_backup(guild_id, created_by):
    """Dump the bot's public DB tables to a zip under ./backups and record it."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"local_backup_{guild_id}_{ts}"
    base = os.path.abspath("./backups")
    os.makedirs(base, exist_ok=True)
    out_path = os.path.join(base, f"{name}.zip")

    conn = guild_settings.get_conn()
    tmpdir = tempfile.mkdtemp()
    tables = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name"
            )
            tables = [r[0] for r in cur.fetchall()]
        for tbl in tables:
            fpath = os.path.join(tmpdir, f"{tbl}.csv")
            with open(fpath, "w", newline="", encoding="utf-8") as f, conn.cursor() as cur:
                cur.copy_expert(f'COPY public."{tbl}" TO STDOUT WITH (FORMAT csv, HEADER)', f)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for tbl in tables:
                zf.write(os.path.join(tmpdir, f"{tbl}.csv"), f"db/{tbl}.csv")
            zf.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "guild_id": guild_id,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "table_count": len(tables),
                    },
                    ensure_ascii=False,
                ),
            )
    finally:
        try:
            conn.close()
        except Exception:
            pass
        shutil.rmtree(tmpdir, ignore_errors=True)

    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO backup_records (guild_id, name, created_by, file_path) VALUES (%s, %s, %s, %s)",
                (guild_id, name, created_by, out_path),
            )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return name


def _select_backup_record(guild_id, backup_id):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, file_path FROM backup_records WHERE guild_id = %s AND id = %s",
                (guild_id, backup_id),
            )
            row = cur.fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return row


def _delete_backup_record(guild_id, backup_id):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT file_path FROM backup_records WHERE guild_id = %s AND id = %s",
                (guild_id, backup_id),
            )
            row = cur.fetchone()
            if row:
                cur.execute(
                    "DELETE FROM backup_records WHERE guild_id = %s AND id = %s",
                    (guild_id, backup_id),
                )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if row and row[0]:
        try:
            if os.path.isfile(row[0]):
                os.remove(row[0])
        except Exception:
            pass


@app.route("/dashboard/<int:guild_id>/backup", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_backup(guild_id):
    user = get_current_user() or {}
    is_owner = int(user.get("id", 0)) == BOT_OWNER_ID

    if request.method == "POST":
        action = request.form.get("action")
        notice = "wiped"
        if action == "local_create":
            try:
                _create_local_backup(guild_id, user.get("id"))
                notice = "backup_created"
            except Exception as e:
                notice = "backup_failed"
        elif action == "local_delete":
            _delete_backup_record(guild_id, request.form.get("backup_id", type=int))
            notice = "backup_deleted"
        elif action == "cloud_create":
            if not is_owner:
                return redirect(url_for("section_backup", guild_id=guild_id) + "?notice=owner")
            client = nitrado_client_for(guild_id)
            if client and client.backup_create("game"):
                notice = "cloud_created"
            else:
                notice = "cloud_failed"
        elif action == "cloud_restore":
            if not is_owner:
                return redirect(url_for("section_backup", guild_id=guild_id) + "?notice=owner")
            client = nitrado_client_for(guild_id)
            name = request.form.get("backup_name")
            if client and name and client.backup_restore(name):
                notice = "cloud_restored"
            else:
                notice = "cloud_failed"
        elif action == "cloud_delete":
            if not is_owner:
                return redirect(url_for("section_backup", guild_id=guild_id) + "?notice=owner")
            client = nitrado_client_for(guild_id)
            name = request.form.get("backup_name")
            if client and name:
                client.backup_delete(name)
                notice = "cloud_deleted"
            else:
                notice = "cloud_failed"
        elif action == "save_browse":
            save_dir = (request.form.get("save_dir") or "").strip().replace("\\", "/")
            if save_dir:
                guild_settings.update_setting(guild_id, "save_dir", save_dir)
            import urllib.parse as _u
            return redirect(url_for("section_backup", guild_id=guild_id) + "?savedir=" + _u.quote(save_dir or "ShooterGame/Saved/SavedArks"))
        elif action == "save_upload":
            save_dir = (request.form.get("save_dir") or "").strip().replace("\\", "/") or "ShooterGame/Saved/SavedArks"
            notice = "save_upload_failed"
            import urllib.parse as _u
            return redirect(url_for("section_backup", guild_id=guild_id) + "?savedir=" + _u.quote(save_dir) + "&notice=" + notice)
        elif action == "save_map":
            folder = (request.form.get("map_folder") or "").strip().replace("\\", "/")
            save_dir = f"ShooterGame/Saved/SavedArks/{folder}" if folder else "ShooterGame/Saved/SavedArks"
            if folder:
                guild_settings.update_setting(guild_id, "save_dir", save_dir)
            import urllib.parse as _u
            return redirect(url_for("section_backup", guild_id=guild_id) + "?savedir=" + _u.quote(save_dir) + "&map=" + _u.quote(folder))
        return redirect(url_for("section_backup", guild_id=guild_id) + "?notice=" + notice)

    conn = guild_settings.get_conn()
    local = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, created_at, created_by, file_path FROM backup_records WHERE guild_id = %s ORDER BY created_at DESC",
                (guild_id,),
            )
            for r in cur.fetchall():
                local.append(
                    {
                        "id": r[0],
                        "name": r[1],
                        "created_at": r[2],
                        "created_by": r[3],
                        "file_path": r[4],
                        "date": r[2].strftime("%Y-%m-%d %H:%M") if r[2] else "",
                    }
                )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    client = nitrado_client_for(guild_id)
    cloud = []
    cloud_configured = client is not None
    cloud_error = None
    if client:
        try:
            for b in client.backup_list() or []:
                if isinstance(b, dict):
                    raw_size = b.get("size") or b.get("size_kb") or 0
                    try:
                        raw_size = int(raw_size)
                    except Exception:
                        raw_size = 0
                    if raw_size and raw_size < 1000:
                        size_s = f"{raw_size} B"
                    elif raw_size < 1024 * 1024:
                        size_s = f"{raw_size/1024:.1f} KB"
                    elif raw_size < 1024 * 1024 * 1024:
                        size_s = f"{raw_size/1024/1024:.1f} MB"
                    else:
                        size_s = f"{raw_size/1024/1024/1024:.2f} GB"
                    created = b.get("createdAt") or b.get("created_at") or b.get("date") or b.get("timestamp") or ""
                    cloud.append(
                        {
                            "name": b.get("name") or b.get("backup") or b.get("id") or str(b),
                            "created_at": created,
                            "date": str(created),
                            "size": raw_size,
                            "size_s": size_s,
                        }
                    )
                else:
                    cloud.append({"name": str(b), "created_at": None, "date": "", "size": 0, "size_s": ""})
        except Exception as e:
            cloud_error = str(e)

    # Save-file browser is not supported on PlayStation servers: Nitrado's
    # file-server API does not expose game files for PlayStation services, and
    # FTP access is restricted. Show a notice instead of attempting a browse.
    save_dir = request.args.get("savedir") or ""
    save_browsed = bool(request.args.get("savedir"))
    if save_dir:
        save_dir = save_dir.replace("\\", "/")
        save_dir = save_dir.lstrip("/")
    if not save_dir:
        save_dir = guild_settings.get_setting(guild_id, "save_dir", "ShooterGame/Saved/SavedArks") or "ShooterGame/Saved/SavedArks"
        save_dir = str(save_dir).lstrip("/")
    save_files = []
    save_error = None
    save_not_supported = True

    current_map_folder = ""
    for _m in ARK_MAPS:
        if save_dir.rstrip("/").endswith("/" + _m["folder"]):
            current_map_folder = _m["folder"]
            break

    return render_template(
        "sections/backup.html",
        user=user,
        guild_id=guild_id,
        active_section="backup",
        local_backups=local,
        cloud_backups=cloud,
        cloud_configured=cloud_configured,
        cloud_error=cloud_error,
        is_owner=is_owner,
        notice=request.args.get("notice", ""),
        save_dir=save_dir,
        save_browsed=save_browsed,
        save_files=save_files,
        ark_maps=ARK_MAPS,
        current_map_folder=current_map_folder,
        save_error=save_error,
        save_not_supported=save_not_supported,
    )


@app.route("/api/guild/<int:guild_id>/backup/save-download")
@login_required
@guild_admin_required
def api_save_download(guild_id):
    return "Save file downloads are not supported on PlayStation servers due to Nitrado restrictions.", 501


@app.route("/dashboard/<int:guild_id>/leaderboard", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_leaderboard(guild_id):
    if request.method == "POST":
        action = request.form.get("action") or "config"
        if action == "config":
            enabled = request.form.get("enabled") in ("on", "1", "true")
            channel_id = request.form.get("channel_id")
            interval = request.form.get("update_interval") or request.form.get("interval", 5)
            guild_settings.update_setting(guild_id, "leaderboard_config", {
                "enabled": enabled,
                "channel_id": int(channel_id) if channel_id else None,
                "interval": int(interval),
            })
        return redirect(url_for("section_leaderboard", guild_id=guild_id))
    cfg = shop_db.get_leaderboard_config(guild_id) or {}
    kv = guild_settings.get_setting(guild_id, "leaderboard_config", {}) or {}
    settings = {
        "enabled": bool(kv.get("enabled", False)),
        "channel_id": cfg.get("channel_id") or kv.get("channel_id"),
        "update_interval": cfg.get("interval") or kv.get("interval") or 5,
    }
    raw = shop_db.get_leaderboard(guild_id, limit=25)
    leaderboard = [
        {"player_name": tribe, "tribe_name": tribe, "level": points}
        for tribe, points in raw
    ]
    return render_template(
        "sections/leaderboard.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="leaderboard",
        settings=settings,
        leaderboard=leaderboard,
    )


@app.route("/dashboard/<int:guild_id>/server-control", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_server_control(guild_id):
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "select_server":
            try:
                guild_settings.set_active_nitrado_service(guild_id, int(request.form.get("svc_id", "0")))
            except Exception:
                pass
            return redirect(url_for("section_server_control", guild_id=guild_id))
        notice = ""
        notice_type = "error"
        user_id = int((get_current_user() or {}).get("id", 0) or 0)

        def _save_evidence_image(punishment_id, fimg):
            if not fimg or not fimg.filename:
                return
            try:
                safe_ext = os.path.splitext(fimg.filename)[1].lower()[:10]
                if safe_ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                    safe_ext = ".png"
                fname = f"{uuid4().hex}{safe_ext}"
                ev_dir = os.path.join("evidence", str(guild_id), str(punishment_id))
                os.makedirs(ev_dir, exist_ok=True)
                fimg.save(os.path.join(ev_dir, fname))
                guild_settings.add_evidence(punishment_id, guild_id, fname, fimg.filename, 0, user_id)
            except Exception:
                pass

        if action == "change_passwords":
            admin_pw = request.form.get("password_admin", "")
            server_pw = request.form.get("password_server", "")
            results = []
            if admin_pw:
                try:
                    results.append("Admin: " + nitrado.change_admin_password(guild_id, admin_pw))
                except Exception as e:
                    results.append("Admin: Failed (" + type(e).__name__ + ")")
            if server_pw:
                try:
                    results.append("Join: " + nitrado.change_server_password(guild_id, server_pw))
                except Exception as e:
                    results.append("Join: Failed (" + type(e).__name__ + ")")
            if results:
                notice = " | ".join(results)
                notice_type = "ok" if all("Applied" in r for r in results) else "error"
        elif action in ("start", "stop", "restart"):
            try:
                client = nitrado.get_client(guild_id)
                if not client:
                    notice = "Nitrado not configured"
                elif action == "start":
                    client.start_server()
                    notice = "Start requested"
                    notice_type = "ok"
                elif action == "stop":
                    client.stop_server()
                    notice = "Stop requested"
                    notice_type = "ok"
                else:
                    client.restart_server()
                    notice = "Restart requested"
                    notice_type = "ok"
            except Exception as e:
                notice = "Failed: " + type(e).__name__
        elif action == "ban_player":
            pname = request.form.get("player_name", "").strip()
            reason = request.form.get("reason", "").strip() or "No reason"
            duration_h = request.form.get("duration_hours", "").strip()
            fimg = request.files.get("evidence_image")
            if pname:
                rmsg = nitrado.ban_player(guild_id, pname) if nitrado.get_client(guild_id) else "Nitrado not configured"
                expires = None
                ptype = "ban"
                if duration_h:
                    try:
                        hours = float(duration_h)
                        if hours > 0:
                            expires = datetime.now(timezone.utc) + timedelta(hours=hours)
                            ptype = "tempban"
                    except Exception:
                        expires = None
                pid = guild_settings.add_punishment(guild_id, pname, ptype, reason, user_id, player_id=request.form.get("player_id", ""))
                _save_evidence_image(pid, fimg)
                notice = f"{pname}: {rmsg}"
                notice_type = "ok" if "Banned" in rmsg else "error"
        elif action == "unban_player":
            pname = request.form.get("player_name", "").strip()
            if pname:
                rmsg = nitrado.unban_player(guild_id, pname) if nitrado.get_client(guild_id) else "Nitrado not configured"
                notice = f"{pname}: {rmsg}"
                notice_type = "ok" if "Unbanned" in rmsg else "error"
        elif action == "whitelist_player":
            pname = request.form.get("player_name", "").strip()
            reason = request.form.get("reason", "").strip()
            duration_h = request.form.get("duration_hours", "").strip()
            if pname:
                rmsg = nitrado.whitelist_player(guild_id, pname) if nitrado.get_client(guild_id) else "Nitrado not configured"
                expires = None
                if duration_h:
                    try:
                        hours = float(duration_h)
                        if hours > 0:
                            expires = datetime.now(timezone.utc) + timedelta(hours=hours)
                    except Exception:
                        expires = None
                guild_settings.add_whitelist(guild_id, pname, request.form.get("player_id", ""), reason, user_id, expires)
                notice = f"{pname}: {rmsg}"
                notice_type = "ok" if "Whitelisted" in rmsg else "error"
        elif action == "remove_whitelist":
            entry_id = request.form.get("entry_id", "")
            try:
                if guild_settings.remove_whitelist(int(entry_id), guild_id):
                    notice = "Whitelist entry removed"
                    notice_type = "ok"
            except Exception:
                notice = "Failed to remove entry"
        elif action == "reset_playtime":
            try:
                guild_settings.reset_playtime(guild_id)
                notice = "Playtime tracking data reset"
                notice_type = "ok"
            except Exception:
                notice = "Failed to reset playtime"
        return redirect(url_for("section_server_control", guild_id=guild_id, notice=notice, notice_type=notice_type))
    notice = request.args.get("notice", "")
    notice_type = request.args.get("notice_type", "ok")
    raw = {}
    try:
        raw = nitrado.get_server_info(guild_id) or {}
    except Exception:
        raw = {}
    info = {}
    if isinstance(raw, dict):
        info = raw.get("data", raw)
        if isinstance(info, dict):
            source = info
            nested = info.get("gameserver")
            if isinstance(nested, dict):
                source = dict(info)
                source.update(nested)
                info = source
            q = info.get("query") or info.get("query_info")
            if isinstance(q, dict):
                info = dict(info)
                info.update({k: v for k, v in q.items() if v not in (None, "", {})})

    def _pick(*keys, default=""):
        for k in keys:
            v = info.get(k)
            if v not in (None, "", {}):
                return v
        return default

    blocked_keys = ("settings", "credentials", "quota", "hostsystems", "modpacks")
    for _bk in blocked_keys:
        info.pop(_bk, None)

    settings_flat = {}
    try:
        settings_flat = nitrado.get_ark_settings(guild_id) or {}
    except Exception:
        settings_flat = {}

    def _sval(*keys, default=""):
        for k in keys:
            v = settings_flat.get(k)
            if v not in (None, "", {}):
                return v
        return default

    def _flt(v, default):
        try:
            f = float(v)
            return f if f > 0 else default
        except Exception:
            return default

    def _fmt_map(raw):
        raw = str(raw or "")
        if not raw:
            return ""
        if "preinstalled," in raw or ("preinstalled" in raw and raw.count(",") >= 2):
            parts = [p for p in raw.split(",") if p and p != "preinstalled"]
            for p in parts:
                if not p.isdigit():
                    return p.strip()
        return raw.strip()

    _map = _fmt_map(_sval("MapPlayerDedicatedServer", "MapName", "map", "Map", default=""))
    if not _map:
        _map = _fmt_map(_pick("map", "map_name", "current_map", default=""))

    _server_name = ""
    try:
        _server_name = nitrado.server_name(guild_id)
    except Exception:
        _server_name = ""
    if not _server_name:
        _server_name = str(_sval("SessionName", "ServerName", "server_name", "server-name", default=""))
    if not _server_name:
        _server_name = _pick("server_name", "name", "display_name", "hostname", "session_name", default="")
    # Owner-picked display name applies ONLY to the Server Status card below.
    _status_display_name = ""
    try:
        _svc = guild_settings.get_active_nitrado_service(guild_id)
        if _svc:
            _status_display_name = (_svc.get("display_name") or "").strip() or (_svc.get("name") or "").strip()
        if not _status_display_name:
            _status_display_name = str(guild_settings.get_setting(guild_id, "nitrado_display_name", "") or "").strip()
    except Exception:
        _status_display_name = ""
    if _status_display_name:
        _server_name = _status_display_name

    _cond = _sval("DayCycleSpeedScale", "DayNightSpeedScale", default=None)
    _taming = _sval("TamingSpeedMultiplier", "TamingSpeed", default=None)
    _harvest = _sval("HarvestAmountMultiplier", "HarvestAmount", default=None)
    _xp = _sval("XPMultiplier", "XPAmountMultiplier", default=None)
    if _cond is None:
        _cond = _pick("day_night_cycle", default=None)
    if _taming is None:
        _taming = _pick("taming_speed", default=None)
    if _harvest is None:
        _harvest = _pick("harvest_amount", default=None)
    if _xp is None:
        _xp = _pick("xp_multiplier", default=None)

    players_list = []
    try:
        client = nitrado.get_client(guild_id)
        if client:
            players_list = client.get_player_list()
    except Exception:
        players_list = []

    _playtime_map = {}
    try:
        _playtime_map = guild_settings.get_playtime_map(guild_id)
    except Exception:
        _playtime_map = {}

    _by_id = _playtime_map.get("by_id", {}) if isinstance(_playtime_map, dict) else {}
    _by_name = _playtime_map.get("by_name", {}) if isinstance(_playtime_map, dict) else {}

    def _fmt_secs(_secs):
        _secs = int(_secs or 0)
        _parts = []
        _d, _rem = divmod(_secs, 86400)
        _h, _rem = divmod(_rem, 3600)
        _m, _s = divmod(_rem, 60)
        if _d:
            _parts.append(f"{_d}d")
        if _h:
            _parts.append(f"{_h}h")
        if _m:
            _parts.append(f"{_m}m")
        if not _parts:
            _parts.append(f"{_s}s")
        return " ".join(_parts)

    for _p in players_list:
        _pt = None
        _pid = str(_p.get("steam_id") or _p.get("id") or "")
        if _pid and _pid in _by_id:
            _pt = _by_id[_pid]
        else:
            _pn = str(_p.get("name") or "")
            if _pn:
                _pt = _by_name.get(_pn.lower())
        _p["playtime_display"] = _fmt_secs(_pt["seconds"]) if _pt else None
        _p["playtime_last_seen"] = _pt.get("last_seen") if _pt else None

    online_players = [p for p in players_list if p.get("online")]
    _status_raw = str(info.get("status") or (info.get("game_status") or ""))
    _status_l = _status_raw.lower()
    _online = _status_l in ("online", "running", "started", "active") or bool(info.get("is_running"))
    _starting = _online or ("install" in _status_l or "start" in _status_l or "boot" in _status_l)
    if not getattr(app, "_sc_diag_logged", False):
        try:
            print("[sc-settings] resolved map=%r name=%r cond=%r taming=%r harvest=%r xp=%r" % (
                _map, _server_name, _cond, _taming, _harvest, _xp), flush=True)
            print("[sc-settings] flat keys sample: %s" % [k for k in list(settings_flat.keys())[:40]], flush=True)
            app._sc_diag_logged = True
        except Exception:
            pass

    server_status = {
        "online": _online,
        "status_text": _status_raw or ("On" if _online else "Off"),
        "starting": _starting,
        "map": _map or "Unknown",
        "players": _pick("player_count", "players_current", "player_current", "players", default=len(online_players)),
        "max_players": _pick("slots", "max_players", "maxplayers", "player_max", default=70),
        "ping": _pick("ping", "query_ping", default="-"),
        "uptime": _pick("uptime", default="-"),
        "server_name": _server_name,
        "day_night_cycle": _flt(_cond, 1),
        "taming_speed": _flt(_taming, 1),
        "harvest_amount": _flt(_harvest, 1),
        "xp_multiplier": _flt(_xp, 1),
        "players_list": players_list,
        "online_players": online_players,
    }

    banned_players = []
    try:
        for row in guild_settings.get_punishments(guild_id, limit=500, offset=0):
            ptype, pname, preason = row[4], row[1], row[5]
            if ptype not in ("ban", "tempban"):
                continue
            pid = row[0]
            evidence = []
            for ev in guild_settings.get_evidence(pid):
                evidence.append({"filename": ev[1], "original_name": ev[2]})
            banned_players.append({
                "punishment_id": pid,
                "player_name": pname,
                "player_id": row[2] or "",
                "type": ptype,
                "reason": preason,
                "issued_at": row[8],
                "expires_at": row[9],
                "executed": row[10],
                "evidence": evidence,
            })
    except Exception:
        banned_players = []

    whitelisted_players = []
    try:
        for row in guild_settings.get_whitelists(guild_id):
            whitelisted_players.append({
                "id": row[0],
                "player_name": row[1],
                "player_id": row[2] or "",
                "reason": row[3] or "",
                "created_at": row[5],
                "expires_at": row[6],
            })
    except Exception:
        whitelisted_players = []

    current_passwords = {"admin": "", "server": ""}
    try:
        current_passwords = nitrado.get_server_passwords(guild_id)
    except Exception:
        current_passwords = {"admin": "", "server": ""}

    return render_template(
        "sections/server_control.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="server-control",
        server_status=server_status,
        banned_players=banned_players,
        whitelisted_players=whitelisted_players,
        current_passwords=current_passwords,
        services=guild_settings.list_nitrado_services(guild_id),
        notice=notice,
        notice_type=notice_type,
    )


@app.route("/dashboard/<int:guild_id>/evidence/<path:filename>")
@login_required
@guild_admin_required
def serve_evidence(guild_id, filename):
    base = os.path.abspath(os.path.join("evidence", str(guild_id)))
    fpath = os.path.abspath(os.path.join(base, filename))
    if not fpath.startswith(base) or not os.path.isfile(fpath):
        return "Not found", 404
    return send_file(fpath)


@app.route("/dashboard/<int:guild_id>/logs", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_logs(guild_id):
    if request.method == "POST":
        action = request.form.get("action")
        if session.get("user", {}).get("id") != BOT_OWNER_ID:
            return redirect(url_for("section_logs", guild_id=guild_id) + "?notice=owner")
        if action == "wipe_logs":
            guild_settings.wipe_bot_logs(guild_id)
        elif action == "wipe_warnings":
            guild_settings.wipe_warnings(guild_id)
        elif action == "wipe_punishments":
            guild_settings.wipe_punishments(guild_id)
        elif action == "wipe_purchases":
            import shop_db
            shop_db.wipe_purchases(guild_id)
        return redirect(url_for("section_logs", guild_id=guild_id) + "?notice=wiped")
    page = int(request.args.get("page", 1))
    per_page = 50
    offset = (page - 1) * per_page
    log_type_filter = request.args.get("log_type", "")
    logs = guild_settings.get_logs(guild_id, log_type=log_type_filter or None, limit=per_page, offset=offset)
    total = guild_settings.get_log_count(guild_id, log_type=log_type_filter or None)
    log_settings = {lt: True for lt in guild_settings.LOG_TYPES}
    return render_template(
        "sections/logs.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="logs",
        logs=logs,
        log_types=guild_settings.LOG_TYPES,
        log_type_filter=log_type_filter,
        page=page,
        total=total,
        per_page=per_page,
        log_count=total,
        log_settings=log_settings,
        is_owner=(get_current_user() or {}).get("id") == BOT_OWNER_ID,
    )


@app.route("/dashboard/<int:guild_id>/settings", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_settings(guild_id):
    if request.method == "POST":
        for key in ["bot_language", "whitelist_path", "save_dir"]:
            value = request.form.get(key)
            if value is not None:
                guild_settings.update_setting(guild_id, key, value)
        for key in request.form:
            if key.startswith("log_channel_"):
                log_type = key.replace("log_channel_", "")
                channel_id = request.form.get(key, "").strip()
                if channel_id:
                    guild_settings.update_setting(guild_id, f"log_channel_{log_type}", int(channel_id))
                else:
                    guild_settings.remove_setting(guild_id, f"log_channel_{log_type}")
        return redirect(url_for("section_settings", guild_id=guild_id))
    return render_template(
        "sections/settings.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="settings",
        settings=guild_settings.get_settings(guild_id),
        log_channels=guild_settings.get_all_log_channels(guild_id),
    )


# ── Permissions ─────────────────────────────────────────────

ALL_COMMANDS_LIST = [
    "activate", "help", "top-servers",
    "set-nitrado-token",
    "set-log-channel", "set-license", "ban-user", "view-guilds", "force-sync-guild",
    "set-command-permission", "remove-command-permission", "view-command-permissions", "clear-command-permissions",
    "shop-add", "shop-remove", "shop-list", "shop-edit",
    "points-add", "points-remove", "points-check", "points-leaderboard",
    "whitelist-add", "whitelist-remove", "whitelist-restart", "whitelist-link", "whitelist-unlink",
    "tribelog-config", "tribelog-test", "setup-tribe-forum", "add-tribe-name", "set-tribe-log-source", "set-tribelog-enabled", "set-tribe-log-channel", "set-tribe-log-config", "view-tribelog",
    "automod-config", "automod-list", "automod-remove",
    "backup-create", "backup-list", "backup-restore",
    "leaderboard-config", "leaderboard-set-channel", "leaderboard-toggle", "leaderboard-force", "leaderboard-sync",
    "warn", "tempwarn", "warnings", "clear-warnings", "remove-warning",
    "punish-ban", "punish-tempban", "punish-wipe",
    "punishment-history", "set-warning-threshold", "set-warning-punishment",
    "set-warning-tempban-duration", "set-warning-default-expiry", "set-punishment-log",
    "add-tribe-member", "server-status", "server-restart", "server-stop",
    "custom", "custom-list", "custom-add", "custom-remove", "ark-command", "setup-forum-logs", "setup-shop-forum",
]


# Category grouping for the Commands page (matches help menu categories)
COMMAND_CATEGORY_ORDER = ["general", "server", "custom", "moderation", "shop", "whitelist",
                          "tribelog", "leaderboard", "automod", "admin", "other"]

# command -> (category, default description)
COMMANDS_META = {
    "help": ("general", "Show all available commands"),
    "activate": ("general", "Activate / verify the bot licence for your server"),
    "top-servers": ("general", "Show the top servers leaderboard"),
    "set-language": ("general", "Set the bot language for the server"),
    "set-help-text": ("general", "Override the description of a slash command"),
    "custom": ("custom", "Run a custom server command"),
    "custom-list": ("custom", "List all custom commands"),
    "custom-add": ("custom", "Create a custom server command"),
    "custom-remove": ("custom", "Delete a custom command"),
    "ark-command": ("custom", "Run a raw ARK console command"),
    "setup-forum-logs": ("custom", "Create the server-log forum with 4 category threads"),
    "setup-shop-forum": ("custom", "Create the shop-logs forum with Done + Pending threads"),
    "add-shop-dino": ("shop", "Add a dino to the shop"),
    "remove-shop-dino": ("shop", "Remove a dino from the shop"),
    "list-dinos": ("shop", "List all shop dinos"),
    "buy-dino": ("shop", "Buy a dino from the shop"),
    "balance": ("shop", "Check your point balance"),
    "add-points": ("shop", "Add points to a member"),
    "remove-points": ("shop", "Remove points from a member"),
    "set-min-level": ("shop", "Set the minimum level for shop dinos"),
    "pending-purchases": ("shop", "List pending shop purchases"),
    "spawn-pending": ("shop", "Spawn a pending purchase"),
    "cancel-pending": ("shop", "Cancel a pending purchase"),
    "set-shop-channels": ("shop", "Set the shop pending/done channels"),
    "shop-add": ("shop", "Add an item to the shop"),
    "shop-remove": ("shop", "Remove an item from the shop"),
    "shop-list": ("shop", "List shop items"),
    "shop-edit": ("shop", "Edit a shop item"),
    "points-add": ("shop", "Add points to a member"),
    "points-remove": ("shop", "Remove points from a member"),
    "points-check": ("shop", "Check a point balance"),
    "points-leaderboard": ("shop", "Show the points leaderboard"),
    "whitelist": ("whitelist", "Show whitelist status"),
    "whitelist-add": ("whitelist", "Add a player to the whitelist"),
    "whitelist-remove": ("whitelist", "Remove a player from the whitelist"),
    "whitelist-restart": ("whitelist", "Restart the whitelist"),
    "whitelist-link": ("whitelist", "Link your PSN gamertag to your Discord"),
    "whitelist-unlink": ("whitelist", "Unlink your PSN gamertag"),
    "linkpsn": ("whitelist", "Link your PSN gamertag"),
    "unlinkpsn": ("whitelist", "Unlink your PSN gamertag"),
    "wl-status": ("whitelist", "Show your whitelist status"),
    "wl-list": ("whitelist", "List whitelisted players"),
    "set-wl-path": ("whitelist", "Set the whitelist file path"),
    "set-restart-time": ("whitelist", "Set the whitelist restart time"),
    "ban": ("moderation", "Ban a member"),
    "kick": ("moderation", "Kick a member"),
    "mute": ("moderation", "Mute a member"),
    "unmute": ("moderation", "Unmute a member"),
    "warn": ("moderation", "Warn a member"),
    "warnings": ("moderation", "List a member's warnings"),
    "clear-warnings": ("moderation", "Clear a member's warnings"),
    "banplayer": ("moderation", "Ban a player on the ARK server"),
    "unbanplayer": ("moderation", "Unban a player on the ARK server"),
    "wipe-player": ("moderation", "Wipe a player's data"),
    "tempwarn": ("moderation", "Issue a temporary warning"),
    "remove-warning": ("moderation", "Remove a specific warning"),
    "punish-ban": ("moderation", "Ban a member via the punishment system"),
    "punish-tempban": ("moderation", "Temp-ban a member"),
    "punish-wipe": ("moderation", "Wipe a member's punishments"),
    "punishment-history": ("moderation", "Show a member's punishment history"),
    "set-warning-threshold": ("moderation", "Set the warning threshold"),
    "set-warning-punishment": ("moderation", "Set the punishment for reaching a threshold"),
    "set-warning-tempban-duration": ("moderation", "Set the temp-ban duration"),
    "set-warning-default-expiry": ("moderation", "Set the default warning expiry"),
    "set-punishment-log": ("moderation", "Set the punishment log channel"),
    "tribelog-config": ("tribelog", "Configure the tribe log"),
    "tribelog-test": ("tribelog", "Test the tribe log"),
    "setup-tribe-forum": ("tribelog", "Create the tribe log forum"),
    "add-tribe-name": ("tribelog", "Add a tribe name for logging"),
    "set-tribe-log-source": ("tribelog", "Set the tribe log source"),
    "set-tribelog-enabled": ("tribelog", "Enable or disable the tribe log"),
    "set-tribe-log-channel": ("tribelog", "Set the tribe log channel"),
    "set-tribe-log-config": ("tribelog", "Set the tribe log config"),
    "view-tribelog": ("tribelog", "View the tribe log"),
    "add-tribe-member": ("tribelog", "Add a member to a tribe"),
    "set-tribe-owner": ("tribelog", "Set a tribe's owner"),
    "add-tribe-points": ("tribelog", "Add points to a tribe"),
    "remove-tribe-points": ("tribelog", "Remove points from a tribe"),
    "tribe-log": ("tribelog", "View the tribe log"),
    "enable-tribe-log": ("tribelog", "Enable the tribe log"),
    "disable-tribe-log": ("tribelog", "Disable the tribe log"),
    "leaderboard": ("leaderboard", "Show the leaderboard"),
    "setup-leaderboard": ("leaderboard", "Set up the leaderboard"),
    "leaderboard-preview": ("leaderboard", "Preview the leaderboard"),
    "leaderboard-config": ("leaderboard", "Configure the leaderboard"),
    "leaderboard-set-channel": ("leaderboard", "Set the leaderboard channel"),
    "leaderboard-toggle": ("leaderboard", "Toggle the leaderboard"),
    "leaderboard-force": ("leaderboard", "Force a leaderboard update"),
    "leaderboard-sync": ("leaderboard", "Sync the leaderboard"),
    "automod-config": ("automod", "Configure auto-moderation"),
    "automod-list": ("automod", "List auto-mod settings"),
    "automod-remove": ("automod", "Remove an auto-mod setting"),
    "automod-toggle": ("automod", "Toggle auto-mod"),
    "automod-set-log-channel": ("automod", "Set the auto-mod log channel"),
    "automod-set-log-path": ("automod", "Set the auto-mod log path"),
    "automod-add-word": ("automod", "Add a filtered word"),
    "automod-remove-word": ("automod", "Remove a filtered word"),
    "automod-list-words": ("automod", "List filtered words"),
    "automod-clear-words": ("automod", "Clear filtered words"),
    "set-nitrado-token": ("admin", "Set the Nitrado API token"),
    "set-log-channel": ("admin", "Set a log channel"),
    "set-license": ("admin", "Set the licence key"),
    "ban-user": ("admin", "Ban a user from the bot"),
    "view-guilds": ("admin", "View bot guilds"),
    "force-sync-guild": ("admin", "Force-sync a guild"),
    "set-command-permission": ("admin", "Set a command permission for a role"),
    "remove-command-permission": ("admin", "Remove a command permission"),
    "view-command-permissions": ("admin", "View command permissions"),
    "clear-command-permissions": ("admin", "Clear command permissions"),
    "backup-create": ("server", "Create a server backup"),
    "backup-list": ("server", "List server backups"),
    "backup-restore": ("server", "Restore a server backup"),
    "backup-rollback": ("server", "Roll back a server backup"),
    "backup-download": ("server", "Download a server backup"),
    "server-status": ("server", "Show the ARK server status"),
    "server-restart": ("server", "Restart the ARK server"),
    "server-stop": ("server", "Stop the ARK server"),
}


def _command_default_desc(cmd: str) -> str:
    return COMMANDS_META.get(cmd, ("other", "Slash command"))[1]


@app.route("/dashboard/<int:guild_id>/commands", methods=["GET", "POST"])
@login_required
@guild_admin_required
@validate_csrf
def section_commands(guild_id):
    guild_roles = get_guild_roles(guild_id)
    permissions = _build_permissions_dict(guild_id, guild_roles)
    disabled = set(guild_settings.get_disabled_commands(guild_id))
    descriptions = guild_settings.get_command_descriptions(guild_id)
    custom_commands = guild_settings.get_custom_commands(guild_id)

    if request.method == "POST":
        cmd_action = request.form.get("cmd_action", "")
        command = request.form.get("command", "").strip()
        if cmd_action == "set_description" and command:
            guild_settings.set_command_description(guild_id, command, request.form.get("description", ""))
        elif cmd_action == "toggle_disabled" and command:
            guild_settings.set_command_disabled(guild_id, command, request.form.get("disabled", "0") == "1")
        elif cmd_action == "add_permission" and command:
            role_id = request.form.get("role_id", "").strip()
            if role_id.isdigit():
                guild_settings.set_command_permission(guild_id, command, int(role_id))
        elif cmd_action == "remove_permission" and command:
            role_id = request.form.get("role_id", "").strip()
            if role_id.isdigit():
                guild_settings.remove_command_permission(guild_id, command, int(role_id))
        elif cmd_action == "clear_permissions" and command:
            guild_settings.clear_command_permissions(guild_id, command)
        elif cmd_action == "update_custom" and command:
            command_string = request.form.get("command_string", "").strip() or None
            category = request.form.get("category") or None
            enabled_flag = request.form.get("enabled")
            guild_settings.update_custom_command(guild_id, command, command_string, category,
                                                 True if enabled_flag != "0" else False)
        elif cmd_action == "toggle_custom_enabled" and command:
            guild_settings.update_custom_command(
                guild_id, command,
                enabled=True if request.form.get("enabled", "0") == "1" else False)
        return redirect(url_for("section_commands", guild_id=guild_id))

    # Build the command list (all known commands) ordered by category.
    ordered = []
    for cat in COMMAND_CATEGORY_ORDER:
        for cmd in ALL_COMMANDS_LIST:
            if (COMMANDS_META.get(cmd, ("other",))[0]) == cat:
                ordered.append(cmd)
    # include any custom commands (they live under the 'custom' category)
    commands = []
    for cmd in ordered:
        cat = COMMANDS_META.get(cmd, ("other",))[0]
        commands.append({
            "name": cmd,
            "category": cat,
            "description": descriptions.get(cmd, _command_default_desc(cmd)),
            "disabled": cmd in disabled,
            "permissions": permissions.get(cmd, []),
        })
    # user-defined custom commands grouped under their own section, with
    # role-permission controls keyed by the custom command's name.
    custom_perms = []
    for cc in custom_commands:
        cname = cc.get("name", "")
        enabled_flag = bool(cc.get("enabled", True))
        custom_perms.append({
            "name": cname,
            "command_string": cc.get("command_string", ""),
            "category": cc.get("category", ""),
            "enabled": enabled_flag,
            "disabled": not enabled_flag,
            "permissions": permissions.get(cname, []),
        })
    return render_template(
        "sections/commands.html",
        user=get_current_user(),
        guild_id=guild_id,
        active_section="commands",
        commands=commands,
        custom_perms=custom_perms,
        guild_roles=guild_roles,
        custom_commands=custom_commands,
        category_order=COMMAND_CATEGORY_ORDER,
        cat_labels={
            "general": "General", "server": "Server", "custom": "Custom Commands",
            "moderation": "Moderation", "shop": "Shop", "whitelist": "Whitelist",
            "tribelog": "Tribe Log", "leaderboard": "Leaderboard", "automod": "Auto-Mod",
            "admin": "Admin", "other": "Other",
        },
        custom_cat_labels={
            "dino_spawn": "🦖 Dino Spawning",
            "gfi": "🎁 GFI Commands",
            "player": "🧍 Player Features",
            "gcm": "🎮 GCM",
        },
    )


def _build_permissions_dict(guild_id, guild_roles):
    raw = guild_settings.get_all_command_permissions(guild_id)
    role_map = {r["id"]: r["name"] for r in guild_roles}
    result = {}
    for cmd, role_ids in raw.items():
        result[cmd] = [{"id": rid, "name": role_map.get(rid, str(rid))} for rid in role_ids]
    return result


@app.route("/dashboard/<int:guild_id>/permissions", methods=["GET"])
@login_required
@guild_admin_required
def section_permissions(guild_id):
    return redirect(url_for("section_commands", guild_id=guild_id))


@app.route("/dashboard/<int:guild_id>/permissions/add", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def permissions_add(guild_id):
    return redirect(url_for("section_commands", guild_id=guild_id))


@app.route("/dashboard/<int:guild_id>/permissions/remove", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def permissions_remove(guild_id):
    return redirect(url_for("section_commands", guild_id=guild_id))


@app.route("/dashboard/<int:guild_id>/permissions/clear", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def permissions_clear(guild_id):
    return redirect(url_for("section_commands", guild_id=guild_id))


# ────────────────────────────────────────────────────────────
#  API Endpoints
# ────────────────────────────────────────────────────────────

@app.route("/api/guild/<int:guild_id>/shop/add", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_shop_add(guild_id):
    rate_key = f"api:{guild_id}:{request.remote_addr}"
    if not check_rate_limit(rate_key):
        return jsonify({"error": "rate limit exceeded"}), 429
    data = request.get_json(force=True)
    name = str(data.get("name", ""))[:100]
    blueprint = str(data.get("blueprint", ""))[:500]
    if not name or not blueprint:
        return jsonify({"error": "name and blueprint required"}), 400
    try:
        min_level = max(1, min(999, int(data.get("min_level", 1))))
        max_level = max(1, min(999, int(data.get("max_level", 150))))
        price = max(0, min(999999999, int(data.get("price", 0))))
    except (ValueError, TypeError):
        return jsonify({"error": "invalid numeric values"}), 400
    category = str(data.get("category", "General"))[:50]
    shop_db.add_shop_dino(guild_id, name, blueprint, min_level, max_level, price, category)
    return jsonify({"ok": True})


@app.route("/api/guild/<int:guild_id>/shop/remove", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_shop_remove(guild_id):
    data = request.get_json(force=True)
    name = str(data.get("name", ""))[:100]
    if not name:
        return jsonify({"error": "name required"}), 400
    shop_db.remove_shop_dino(guild_id, name)
    return jsonify({"ok": True})


@app.route("/api/guild/<int:guild_id>/points/add", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_points_add(guild_id):
    data = request.get_json(force=True)
    tribe_name = str(data.get("tribe_name", ""))[:100]
    if not tribe_name:
        return jsonify({"error": "tribe_name required"}), 400
    try:
        amount = max(0, min(999999999, int(data.get("amount", 0))))
    except (ValueError, TypeError):
        return jsonify({"error": "invalid amount"}), 400
    shop_db.add_points(guild_id, tribe_name, amount)
    return jsonify({"ok": True, "balance": shop_db.get_points(guild_id, tribe_name)})


@app.route("/api/guild/<int:guild_id>/points/remove", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_points_remove(guild_id):
    data = request.get_json(force=True)
    tribe_name = str(data.get("tribe_name", ""))[:100]
    if not tribe_name:
        return jsonify({"error": "tribe_name required"}), 400
    try:
        amount = max(0, min(999999999, int(data.get("amount", 0))))
    except (ValueError, TypeError):
        return jsonify({"error": "invalid amount"}), 400
    shop_db.remove_points(guild_id, tribe_name, amount)
    return jsonify({"ok": True, "balance": shop_db.get_points(guild_id, tribe_name)})


@app.route("/api/guild/<int:guild_id>/logs", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_logs(guild_id):
    data = request.get_json(force=True)
    logs = guild_settings.get_logs(
        guild_id,
        log_type=data.get("log_type"),
        user_id=data.get("user_id"),
        limit=int(data.get("limit", 50)),
        offset=int(data.get("offset", 0)),
    )
    for log in logs:
        if log.get("created_at"):
            log["created_at"] = log["created_at"].isoformat()
    return jsonify({"ok": True, "logs": logs})


@app.route("/api/guild/<int:guild_id>/backup/create", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_backup_create(guild_id):
    rate_key = f"backup:{guild_id}:{request.remote_addr}"
    if not check_rate_limit(rate_key):
        return jsonify({"error": "rate limit exceeded"}), 429
    data = request.get_json(force=True) if request.data else {}
    name = data.get("name", "")
    return jsonify({"ok": False,         "error": "Backup creation must be performed via the bot Nitrado API."})


@app.route("/api/guild/<int:guild_id>/backup/download/<int:backup_id>")
@login_required
@guild_admin_required
def api_backup_download(guild_id, backup_id):
    conn = guild_settings.get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT name, file_path FROM backup_records WHERE guild_id = %s AND id = %s", (guild_id, backup_id))
            record = cur.fetchone()
    finally:
        conn.close()
    if not record or not record[1] or not os.path.exists(record[1]):
        return jsonify({"ok": False, "error": "Backup not found."}), 404
    
    backup_base = os.path.abspath("./backups")
    if not validate_path(record[1], backup_base):
        return jsonify({"ok": False, "error": "Invalid backup path."}), 403
    
    return send_file(record[1], as_attachment=True, download_name=f"{record[0]}.zip")


@app.route("/api/guild/<int:guild_id>/backup/restore/<int:backup_id>", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_backup_restore(guild_id, backup_id):
    return jsonify({"ok": False,         "error": "Restore must be performed via the bot Nitrado API."})


@app.route("/api/guild/<int:guild_id>/server/restart", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_server_restart(guild_id):
    rate_key = f"control:{guild_id}:{request.remote_addr}"
    if not check_rate_limit(rate_key):
        return jsonify({"error": "rate limit exceeded"}), 429
    client = nitrado_client_for(guild_id)
    if not client:
        return jsonify({"ok": False, "error": "Nitrado API not configured."}), 400
    result = client.restart_server()
    if result:
        guild_settings.log_action(guild_id, "server", session.get("user", {}).get("id"), session.get("user", {}).get("username"), None, sub_type="restart")
    return jsonify({"ok": result})


@app.route("/api/guild/<int:guild_id>/server/stop", methods=["POST"])
@login_required
@guild_admin_required
@validate_csrf
def api_server_stop(guild_id):
    rate_key = f"control:{guild_id}:{request.remote_addr}"
    if not check_rate_limit(rate_key):
        return jsonify({"error": "rate limit exceeded"}), 429
    client = nitrado_client_for(guild_id)
    if not client:
        return jsonify({"ok": False, "error": "Nitrado API not configured."}), 400
    result = client.stop_server()
    if result:
        guild_settings.log_action(guild_id, "server", session.get("user", {}).get("id"), session.get("user", {}).get("username"), None, sub_type="stop")
    return jsonify({"ok": result})


@app.route("/api/guild/<int:guild_id>/server/status")
@login_required
@guild_admin_required
def api_server_status(guild_id):
    client = nitrado_client_for(guild_id)
    if not client:
        return jsonify({"ok": False, "error": "Nitrado API not configured."})
    status = client.get_server_status()
    return jsonify({"ok": True, "status": status})


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


# ────────────────────────────────────────────────────────────
#  Init
# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    guild_settings.init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
