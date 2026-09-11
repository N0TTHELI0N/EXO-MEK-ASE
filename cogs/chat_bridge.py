import re
import time
from collections import deque
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks
from discord import app_commands

import guild_settings
import nitrado
import config
import bot_i18n
from security import sanitize_rcon_name


CHAT_BRIDGE_INTERVAL_SECONDS = 30
MAX_SEEN = 20000
ECHO_FINGERPRINT_TTL = 120

# Tolerant matchers for ARK ShooterGame.log chat lines.
# Chat lines generally look like:
#   [2024.01.02-03.04.05:123][456]LogChatMessage:  PlayerName: hello
#   [2024.01.02-03.04.05:123][456]LogChatMessage: [Global][PlayerName]: hello
#   [2024.01.02-03.04.05:123][456]LogChatMessage: [TribeName][PlayerName]: hello
#   LogChatMessage: ... [Alliance][Tribe]Name : text  (alliance)
_TS_CAT = re.compile(r"^\[[^\]]+\]\[[^\]]+\]\s*[^:]*?:\s*(.*)$")
_PLAIN_CAT = re.compile(r"^[^:]+:\s*(.*)$")
_CHAT_BODY = re.compile(r"^(?:\[(?P<channel>[^\]]+)\]\s*)?(?P<player>[^:\]]+?)\s*:\s*(?P<msg>.+)$")

# Player join / leave the server, detected in the same ARK log stream.
# PS hosts phrase it as "<name> left this ARK!", "<name> joined the server"
# (plus legacy formats), so we match the phrase and take the name from the
# text that precedes it:
#   [..][848]2026.09.11_00.08.24: VxV-818 left this ARK!
#   [..][ 4]LogServerPlayerJoined: 'Name' joined the server
_JOIN_PHRASE = re.compile(r"\bjoined\s+(?:this\s+|the\s+)?(?:ARK|server|game|world)\b", re.I)
_LEAVE_PHRASE = re.compile(r"\b(?:left|disconnected(?:\s+from)?|quit)\s+(?:this\s+|the\s+)?(?:ARK|server|game|world)\b", re.I)
_NAME_JUNK_BR = re.compile(r"^(?:\[[^\]]*\]\s*)+")
_NAME_JUNK_TS = re.compile(
    r"^\d{4}[.\-/]\d{2}[.\-/]\d{2}_\d{2}[.\-/]\d{2}[.\-/]\d{2}\s*:\s*"
    r"|^Log[A-Za-z]*Player(?:Joined|Left)\s*[:#]?\s*",
    re.I,
)


def _detect_join_leave(line: str):
    """Return (event_type, player_name) if the line is a player join/leave event."""
    m = _JOIN_PHRASE.search(line)
    if m:
        ev_type = "join"
        prefix = line[: m.start()]
    else:
        m = _LEAVE_PHRASE.search(line)
        if m:
            ev_type = "leave"
            prefix = line[: m.start()]
        else:
            return None
    name = _NAME_JUNK_BR.sub("", prefix)
    name = _NAME_JUNK_TS.sub("", name)
    name = name.strip().strip("'\"()[]{}").strip()
    if not name or len(name) < 2 or len(name) > 40:
        return None
    return ev_type, name


# System/tribe announcements (raid/death/tame/timeline broadcasts always end up
# in the shared log stream) are NOT player chat. Detected by content markers or
# the in-game timeline prefix "Tribe X, ID N: Day N, HH:MM:SS:".
_SYS_RICH = re.compile(r"<richcolor", re.I)
_SYS_DAILY = re.compile(r":\s*day\s+\d{1,2},\s*\d{1,2}:\d{2}:\d{2}\s*:", re.I)
_SYS_MARKERS = (
    "<richcolor", "tamed a ", "tamed an ", "was killed by", "was tamed by",
    "killed your", "destroyed your", "destroyed their", "was destroyed by",
    "added to the tribe", "was added to the tribe", "left the tribe ",
    "froze a ", "froze an ", "was frozen", "-> ", "[killed]", "[tamed]",
)
_LOG_HEADER = re.compile(r"^(?:\[[^\]]*\]\s*)+|^\d{4}[.\-/]\d{2}[.\-/]\d{2}_\d{2}[.\-/]\d{2}[.\-/]\d{2}\s*:\s*", re.I)


def _classify_system_line(text: str) -> str | None:
    """Classify a non-chat log line: 'admin', 'tribe' — or None if it is player chat.

    Admin echoes (AdminCmd → rename/destroy/ban...) go to the admin forum; tribe
    broadcasts (Tribe timeline, tame/kill/freeze/destroy announcements) go to the
    tribe forum. Anything else is left to the chat parser.
    """
    body = _LOG_HEADER.sub("", text or "").strip()
    low = body.lower()
    if "admincmd" in low:
        return "admin"
    if _SYS_RICH.search(low) or _SYS_DAILY.search(body):
        return "tribe"
    for m in _SYS_MARKERS:
        if m in low:
            return "tribe"
    if re.search(r"\btribe\b[^:]{0,80}:\s*day\s+\d", body, re.I):
        return "tribe"
    return None


def _detect_console_command(line: str):
    """Try to parse a line as an in-game admin/console command.

    Returns (command_string, log_category) or None. Commands typed in the
    server console usually start with '?' / 'cheat' / 'admincheat', or echo a
    known ARK command keyword without a prefix.
    """
    text = (line or "").strip()
    if not text:
        return None
    m = _TS_CAT.match(text)
    if m:
        text = m.group(1).strip()
    else:
        m = _PLAIN_CAT.match(text)
        if m:
            text = m.group(1).strip()
    text = text.strip()
    low = (text or "").lower()
    if not low:
        return None
    if _CHAT_BODY.match(text):
        return None
    if any(x in low for x in ("chat command sent to server", "serverchatmessage", "?setadminpassword", "?adminpassword")):
        return None
    cmd = None
    if low.startswith("?"):
        cmd = text.lstrip("?").strip()
    elif low.startswith(("cheat ", "admincheat ", "adminenabledcheats ")):
        cmd = text.split(None, 1)[1].strip() if " " in text else text
    else:
        rules = guild_settings.DEFAULT_CATEGORY_RULES
        for cat in rules:
            for kw in rules[cat]:
                if kw and kw in low:
                    cmd = text
                    break
            if cmd:
                break
    if not cmd:
        return None
    cl = cmd.lower()
    if cl.startswith(("cheat ", "admincheat ")):
        cmd = cmd.split(None, 1)[1].strip()
    if not cmd:
        return None
    cat = guild_settings.detect_command_category(cmd)
    return cmd, cat


def _parse_chat_line(line: str):
    text = line
    m = _TS_CAT.match(text)
    if m:
        text = m.group(1)
    else:
        m = _PLAIN_CAT.match(text)
        if m:
            text = m.group(1)
    text = text.strip()
    if not text:
        return None
    m = _CHAT_BODY.match(text)
    if not m:
        return None
    channel = (m.group("channel") or "global").strip()
    player = m.group("player").strip()
    message = m.group("msg").strip()
    if not player or not message:
        return None
    if _is_noise(player, message, channel):
        return None
    return channel, player, message


def _is_noise(player: str, message: str, channel: str) -> bool:
    low_p = (player or "").lower()
    low_m = (message or "").lower()
    if low_p in ("server", "console", "admin"):
        return True
    if any(x in low_p for x in ("[developer]", "[dev]", "serverchatmessage")):
        return True
    if (player or "").startswith("/") or "?name=" in low_p or "$" in low_p:
        return True
    if low_m.startswith(("serverchatmessage", "?setadminpassword", "?adminpassword")):
        return True
    if "frozen by id" in low_m:
        return True
    if "chat command sent to server" in low_m:
        return True
    return False


class ChatBridge(commands.Cog):
    """In-game ARK chat bridge & log."""

    def __init__(self, bot):
        self.bot = bot
        self.seen_lines = {}
        # avoid re-forwarding our own ServerChatMessage echoes
        self._echo_guard = deque(maxlen=200)
        # never re-capture/re-post the same chat line within a short window,
        # even if the cursor is lost (restart / log rotation).
        self._capture_guard = {}
        self._event_guard = {}
        # avoid flooding a Discord channel during a log burst
        self._post_guard = deque(maxlen=100)
        # chat auto-detection: rules cache + per (guild, player, word) cooldown
        self._auto_rules_cache = {}
        self._auto_rules_cache_ts = {}
        self._auto_cooldown = {}
        # auto service fallback: when the configured Nitrado service can't be read,
        # scan the account once every 10 minutes and pick a working ARK service.
        self._auto_service = {}
        self._auto_service_ts = {}
        self._hb_ts = {}
        self._empty_ts = {}
        self._diag_ts = {}
        self.chat_monitor.start()

    # ── helpers ──────────────────────────────────────────────

    @staticmethod
    def _fp(channel, player, message):
        return (channel or "global", (player or "").strip().lower(), (message or "").strip().lower())

    def _is_echo(self, channel, player, message):
        fp = self._fp(channel, player, message)
        now = time.time()
        for saved in self._echo_guard:
            if saved[0] == fp and now - saved[1] < ECHO_FINGERPRINT_TTL:
                return True
        return False

    def _remember_sent(self, channel, player, message):
        self._echo_guard.append((self._fp(channel, player, message), time.time()))

    def _capture_seen(self, guild_id: int, fp: tuple, now: float = None, window: float = 300.0) -> bool:
        """True if this chat fingerprint was already captured within `window` s."""
        now = time.time() if now is None else now
        seen = self._capture_guard.setdefault(guild_id, {})
        if fp in seen and now - seen[fp] < window:
            return True
        seen[fp] = now
        if len(seen) > 1500:
            cutoff = now - window
            for k in [k for k in seen if now - seen[k] > cutoff]:
                seen.pop(k, None)
        return False

    def _event_seen(self, guild_id: int, kind: str, name: str, now: float = None, window: float = 120.0) -> bool:
        """True if a join/leave/admin line for (kind, name) was seen recently."""
        now = time.time() if now is None else now
        seen = self._event_guard.setdefault(guild_id, {})
        fp = (kind, name.strip().lower())
        if fp in seen and now - seen[fp] < window:
            return True
        seen[fp] = now
        if len(seen) > 1500:
            cutoff = now - window
            for k in [k for k in seen if now - seen[k] > cutoff]:
                seen.pop(k, None)
        return False

    def _is_new_line(self, guild_id, text):
        last = self.seen_lines.get(guild_id)
        if last is None:
            self.seen_lines[guild_id] = text
            return True
        if text == last:
            return False
        self.seen_lines[guild_id] = text
        return True

    def _split_new_lines(self, guild_id: int, lines: list[str]) -> list[str]:
        """Return only the lines that are NEW since the last poll.

        The ARK tail re-reads the same lines every tick, so a naive cursor
        compare would re-process (and re-post) the whole tail forever. We keep a
        single cursor line and return everything strictly after it.
        """
        if not lines:
            return []
        cursor = self.seen_lines.get(guild_id)
        if cursor is None:
            self.seen_lines[guild_id] = lines[-1]
            return []
        try:
            idx = lines.index(cursor)
        except ValueError:
            # cursor not in this tail (log rotated or >N lines since last poll).
            # replay only a bounded chunk so a big offline gap can't flood Discord.
            self.seen_lines[guild_id] = lines[-1]
            return lines[-60:]
        self.seen_lines[guild_id] = lines[-1]
        return lines[idx + 1:]

    def _pick_auto_service(self, guild_id: int) -> str | None:
        """Pick a working ARK service id for this guild, with a 10-minute cache.

        Promotes a healthy service to active when the configured one is stale,
        suspended, or missing, so every feature resolves the right service.
        """
        now = time.time()
        if guild_id in self._auto_service and now - self._auto_service_ts.get(guild_id, 0) < 600:
            return self._auto_service.get(guild_id)
        self._auto_service_ts[guild_id] = now
        current = str((guild_settings.get_nitrado_config(guild_id) or {}).get("service_id") or "")
        healthy = [s for s in nitrado.find_ark_services(guild_id) if s.get("ok")]
        promoted = None
        chosen = None
        for svc in healthy:
            s = str(svc.get("service_id"))
            if current and s == current:
                chosen = current
                break
            if not chosen:
                chosen = s
                promoted = svc
        if chosen and chosen != current:
            try:
                if guild_settings.promote_nitrado_service(guild_id, chosen):
                    print(f"[ChatBridge] guild={guild_id} auto-promoted Nitrado service {current or '?'} -> {chosen} (status={promoted.get('status') if promoted else '?'})", flush=True)
            except Exception:
                pass
        self._auto_service[guild_id] = chosen
        return chosen

    @staticmethod
    async def _send_to_game(guild_id, sender_name: str, message: str) -> bool:
        # Try the standard ServerChatMessage RCON broadcast first, then fallbacks.
        attempts = [
            f"ServerChatMessage 0 [Discord]{sender_name} {message}",
            f"ServerChatMessage 0 [Discord] {sender_name}: {message}",
        ]
        for cmd in attempts:
            resp = await asyncio_to_thread(nitrado.send_rcon, guild_id, cmd)
            if resp is not None:
                return True
        return False

    # ── background monitor: game -> Discord/log ─────────────
    #
    # All of the blocking work (Nitrado HTTP + Postgres reads/writes) runs in a
    # worker thread via asyncio_to_thread; only the Discord sends stay on the
    # event loop. Running this synchronously on the loop stalled the gateway
    # heartbeat for 10-30s and caused "The application did not respond".
    def _monitor_cycle_sync(self, guild):
        cfg = guild_settings.get_chat_bridge_config(guild.id)
        if not cfg or cfg.get("enabled") is False:
            return None
        client = nitrado.get_client(guild.id)
        if client is None:
            return None
        try:
            raw = nitrado.get_logs_cached(client, 250)
        except Exception:
            raw = None
        if not raw:
            sid = self._pick_auto_service(guild.id)
            if sid is not None and str(sid) != str(client.service_id):
                client = nitrado.NitradoClient(client.api_token, sid)
                try:
                    raw = nitrado.get_logs_cached(client, 250)
                except Exception:
                    raw = None
        if not raw:
            now_empty = time.time()
            if guild.id not in self._empty_ts or now_empty - self._empty_ts[guild.id] >= 60:
                self._empty_ts[guild.id] = now_empty
                print(f"[ChatBridge] guild={guild.id} service={client.service_id} NO_LOG_DATA (file + latest_log empty)", flush=True)
            return None
        now5 = time.time()
        if guild.id not in self._hb_ts or now5 - self._hb_ts[guild.id] >= 300:
            self._hb_ts[guild.id] = now5
            print(f"[ChatBridge] guild={guild.id} service={client.service_id} log_lines={len(raw.splitlines())}", flush=True)
        lines = [(l or "").strip() for l in (raw or "").splitlines()]
        posts = []
        stats = {"join": 0, "leave": 0, "admin": 0, "tribe": 0, "chat": 0, "unparsed": []}
        for text in self._split_new_lines(guild.id, [l for l in lines if l]):
            if not text:
                continue
            joined = _detect_join_leave(text)
            if joined:
                if not self._event_seen(guild.id, joined[0], joined[1], now5):
                    guild_settings.add_server_event(guild.id, joined[0], joined[1], text)
                    stats[joined[0]] += 1
                continue
            kind = _classify_system_line(text)
            if kind == "admin":
                if not self._event_seen(guild.id, "admin", text[:80], now5):
                    guild_settings.add_server_event(
                        guild.id, "admin", "Server", text,
                    )
                    stats["admin"] += 1
                    if len(stats.setdefault("adm_samples", [])) < 3:
                        stats["adm_samples"].append(text[:140])
                continue
            if kind == "tribe":
                # Tribe events (kills/tames/raids) are handled by the dedicated
                # tribelog cog into per-tribe threads; posting them here too
                # would duplicate every event.
                stats["tribe"] += 1
                continue
            parsed = _parse_chat_line(text)
            if not parsed:
                cmd_detect = _detect_console_command(text)
                if cmd_detect:
                    cmd, cat = cmd_detect
                    guild_settings.log_action(
                        guild.id, "admin_command", None, "Server Console", None,
                        command=cmd, sub_type="console",
                        details={"command": cmd, "source": "game console"},
                        log_category=cat,
                    )
                elif len(stats["unparsed"]) < 3:
                    stats["unparsed"].append(text[:160])
                continue
            channel, player, message = parsed
            if self._is_echo(channel, player, message):
                continue
            if _is_noise(player, message, channel):
                continue
            cap_fp = (channel or "", (player or "").strip().lower(), (message or "").strip().lower())
            if self._capture_seen(guild.id, cap_fp, now5):
                continue
            guild_settings.add_chat_log(
                guild.id, channel, player, message,
                tribe_name=player, raw_line=text, direction="in",
            )
            posts.append({"channel": channel, "player": player, "message": message})
            stats["chat"] += 1
        if stats["join"] or stats["leave"] or stats["admin"] or stats["tribe"] or stats["unparsed"]:
            if guild.id not in self._diag_ts or now5 - self._diag_ts[guild.id] >= 60:
                self._diag_ts[guild.id] = now5
                print(
                    f"[ChatBridge] guild={guild.id} new lines: chat={stats['chat']} join={stats['join']} leave={stats['leave']} admin={stats['admin']} tribe={stats['tribe']} unparsed={len(stats['unparsed'])}",
                    flush=True,
                )
                if stats["unparsed"]:
                    print("[ChatBridge] unparsed sample: " + " || ".join(stats["unparsed"]), flush=True)
                if stats.get("adm_samples"):
                    print("[ChatBridge] admin sample: " + " || ".join(stats["adm_samples"]), flush=True)
        return {"cfg": cfg, "posts": posts}

    @staticmethod
    def _resolve_target(guild, cfg, post):
        relay_channel = guild.get_channel(cfg.get("relay_channel_id") or 0)
        log_channel = guild.get_channel(cfg.get("log_channel_id") or 0)
        if cfg.get("relay_out") and isinstance(relay_channel, discord.TextChannel):
            return relay_channel
        if isinstance(log_channel, discord.TextChannel):
            return log_channel
        return None

    @tasks.loop(seconds=CHAT_BRIDGE_INTERVAL_SECONDS)
    async def chat_monitor(self):
        for guild in self.bot.guilds:
            try:
                plan = await asyncio_to_thread(self._monitor_cycle_sync, guild)
            except Exception as e:
                print(f"[ChatBridge] guild={guild.id} monitor error: {type(e).__name__}: {e}", flush=True)
                continue
            if not plan:
                continue
            cfg = plan["cfg"]
            posts = plan["posts"]
            # Auto-detection runs for every parsed chat line (unchanged).
            for post in posts:
                try:
                    await self._check_auto_rules(guild.id, post["player"], post["message"])
                except Exception:
                    pass
            # Forward to the one-way log channel (capped at 15/tick, rate-guarded).
            # If the target is the same thread the server_logs forum posts to,
            # skip it — the forum post is the canonical copy (else each line is
            # sent twice to the same thread).
            try:
                slcfg = guild_settings.get_server_log_config(guild.id) or {}
            except Exception:
                slcfg = {}
            forum_chat_tid = int(slcfg.get("chat_thread_id") or 0)
            posts_this_tick = 0
            for post in posts:
                target = self._resolve_target(guild, cfg, post)
                if target is None:
                    continue
                if forum_chat_tid and isinstance(target, discord.Thread) and target.id == forum_chat_tid:
                    continue
                if posts_this_tick >= 15:
                    break
                if self._post_guard and time.time() - self._post_guard[0][1] < 0.6:
                    continue
                self._post_guard.append((1, time.time()))
                try:
                    await target.send(
                        bot_i18n.t(guild.id, "chat_forward_line", channel=post["channel"], player=post["player"], message=post["message"][:1900])
                    )
                    posts_this_tick += 1
                except Exception:
                    continue

    @chat_monitor.before_loop
    async def before_chat_monitor(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            cfg = guild_settings.get_chat_bridge_config(guild.id)
            if cfg and cfg.get("last_log_line"):
                self.seen_lines[guild.id] = cfg["last_log_line"]

    # ── auto-detection: word -> punishment ──────────────────
    def _get_auto_rules(self, guild_id: int):
        now = time.time()
        if guild_id in self._auto_rules_cache and now - self._auto_rules_cache_ts.get(guild_id, 0) < 60:
            return self._auto_rules_cache[guild_id]
        rules = guild_settings.get_enabled_chat_auto_rules(guild_id)
        self._auto_rules_cache[guild_id] = rules
        self._auto_rules_cache_ts[guild_id] = now
        return rules

    async def _check_auto_rules(self, guild_id: int, player: str, message: str):
        rules = self._get_auto_rules(guild_id)
        if not rules:
            return
        msg_l = (message or "").lower()
        cooldown_min = int(guild_settings.get_setting(guild_id, "chat_auto_cooldown_minutes", 5) or 5)
        for rule in rules:
            word = rule["word"]
            if not word or word not in msg_l:
                continue
            if not self._allow_auto_punish(guild_id, player, word, cooldown_min):
                continue
            self._auto_cooldown[(guild_id, (player or "").lower(), word)] = time.time()
            await self._apply_auto_punishment(guild_id, player, rule)

    def _allow_auto_punish(self, guild_id: int, player: str, word: str, cooldown_min: int) -> bool:
        key = (guild_id, (player or "").lower(), word)
        last = self._auto_cooldown.get(key)
        if last is None:
            return True
        return time.time() - last >= (cooldown_min * 60) if last else True

    async def _apply_auto_punishment(self, guild_id: int, player: str, rule: dict):
        punishment = rule["punishment"]
        safe = sanitize_rcon_name(player)
        reason = f"Auto-detected banned word in chat: '{rule['word']}'"
        try:
            if punishment == "warn":
                guild_settings.add_warning(guild_id, player, reason, 0)
                await self._send_punish_alert(guild_id, bot_i18n.t(guild_id, "auto_warned_chat", player=player, reason=reason))
            elif punishment == "blacklist":
                await asyncio_to_thread(nitrado.ban_player, guild_id, player)
                guild_settings.add_blacklist(guild_id, player, reason, 0, scope="player")
                guild_settings.add_punishment(guild_id, player, "ban", reason, 0, scope="player")
                await self._send_punish_alert(guild_id, bot_i18n.t(guild_id, "auto_blacklisted_chat", player=player, reason=reason))
            elif punishment == "tempban":
                hours = int(rule.get("tempban_hours") or guild_settings.get_setting(guild_id, "warning_tempban_hours", 24) or 24)
                expires = datetime.now(timezone.utc) + timedelta(hours=hours)
                resp = await asyncio_to_thread(nitrado.ban_player, guild_id, player)
                pid = guild_settings.add_punishment(guild_id, player, "tempban", reason, 0, expires_at=expires)
                if resp:
                    guild_settings.mark_punishment_executed(pid)
                await self._send_punish_alert(guild_id, bot_i18n.t(guild_id, "auto_tempbanned_chat", player=player, hours=hours, reason=reason))
            elif punishment == "ban":
                await asyncio_to_thread(nitrado.ban_player, guild_id, player)
                guild_settings.add_punishment(guild_id, player, "ban", reason, 0)
                await self._send_punish_alert(guild_id, bot_i18n.t(guild_id, "auto_banned_chat", player=player, reason=reason))
        except Exception:
            pass

    async def _send_punish_alert(self, guild_id: int, text: str):
        cfg = guild_settings.get_chat_bridge_config(guild_id)
        ch = None
        if cfg.get("log_channel_id"):
            ch = self.bot.get_channel(cfg.get("log_channel_id"))
        if ch is None and cfg.get("relay_channel_id"):
            ch = self.bot.get_channel(cfg.get("relay_channel_id"))
        if ch is not None:
            try:
                await ch.send(text[:1900])
            except Exception:
                pass

    # ── relay: Discord -> game ───────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if not isinstance(message.channel, discord.TextChannel):
            return
        cfg = guild_settings.get_chat_bridge_config(message.guild.id)
        if not cfg or not cfg.get("enabled") or not cfg.get("relay_in"):
            return
        relay_id = cfg.get("relay_channel_id")
        if not relay_id or message.channel.id != relay_id:
            return
        content = message.content.strip()
        if not content or content.startswith("/") or content.startswith("!"):
            return
        if await self._send_to_game(message.guild.id, message.author.display_name, content):
            self._remember_sent("game", f"[Discord] {message.author.display_name}".lower(), content)
            guild_settings.add_chat_log(
                message.guild.id, "outgoing", message.author.display_name,
                content, raw_line=content, direction="out",
            )
            try:
                await message.add_reaction("✅")
            except Exception:
                pass

    # ── config commands ──────────────────────────────────────
    @app_commands.command(name="chat-bridge-enable", description="Enable or disable the in-game chat bridge (Admin)")
    @app_commands.describe(enabled="Enable or disable")
    async def chat_bridge_enable(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_chat_bridge_config(interaction.guild_id, enabled=enabled)
        state = bot_i18n.t(interaction.guild_id, "enabled_word") if enabled else bot_i18n.t(interaction.guild_id, "disabled_word")
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "chat_bridge_toggled", state=state), ephemeral=True)

    @app_commands.command(name="chat-bridge-channel", description="Set the one-way in-game chat log channel (Admin)")
    @app_commands.describe(channel="Channel for in-game chat log")
    async def chat_bridge_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_chat_bridge_config(interaction.guild_id, log_channel_id=channel.id)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "chat_log_channel_set", channel=channel.mention), ephemeral=True)

    @app_commands.command(name="chat-bridge-relay", description="Set the two-way Discord<->game relay channel (Admin)")
    @app_commands.describe(channel="Channel to relay game chat both ways")
    async def chat_bridge_relay(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_chat_bridge_config(interaction.guild_id, relay_channel_id=channel.id)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "relay_channel_set", channel=channel.mention), ephemeral=True)

    @app_commands.command(name="chat-bridge-toggle", description="Control chat bridge direction (Admin)")
    @app_commands.describe(
        game_to_discord="Forward in-game chat to the relay channel",
        discord_to_game="Send Discord messages in the relay channel into the game",
    )
    async def chat_bridge_toggle(self, interaction: discord.Interaction, game_to_discord: bool = None, discord_to_game: bool = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        cfg = guild_settings.get_chat_bridge_config(interaction.guild_id)
        kwargs = {}
        if game_to_discord is not None:
            kwargs["relay_out"] = game_to_discord
        if discord_to_game is not None:
            kwargs["relay_in"] = discord_to_game
        if kwargs:
            guild_settings.update_chat_bridge_config(interaction.guild_id, **kwargs)
        cfg = guild_settings.get_chat_bridge_config(interaction.guild_id)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "chat_bridge_state", relay_out=cfg.get('relay_out'), relay_in=cfg.get('relay_in')), ephemeral=True,
        )

    @app_commands.command(name="chat-bridge-send", description="Send a message into the game chat as Discord (Admin)")
    @app_commands.describe(message="Message to send into the game")
    async def chat_bridge_send(self, interaction: discord.Interaction, message: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        ok = await self._send_to_game(interaction.guild_id, interaction.user.display_name, message)
        if ok:
            self._remember_sent("game", f"[Discord] {interaction.user.display_name}".lower(), message)
            guild_settings.add_chat_log(interaction.guild_id, "outgoing", interaction.user.display_name, message, raw_line=message, direction="out")
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "chat_bridge_sent") if ok else bot_i18n.t(interaction.guild_id, "chat_bridge_failed"), ephemeral=True)

    @app_commands.command(name="chat-bridge-status", description="Show chat bridge status")
    async def chat_bridge_status(self, interaction: discord.Interaction):
        cfg = guild_settings.get_chat_bridge_config(interaction.guild_id)
        on = bot_i18n.t(interaction.guild_id, "on_state")
        off = bot_i18n.t(interaction.guild_id, "off_state")
        lines = [
            bot_i18n.t(interaction.guild_id, "status_enabled_field", state=on if cfg.get('enabled') else off),
            bot_i18n.t(interaction.guild_id, "status_log_channel_field", channel=f"<#{cfg.get('log_channel_id')}>") if cfg.get("log_channel_id") else bot_i18n.t(interaction.guild_id, "status_log_channel_not_set"),
            bot_i18n.t(interaction.guild_id, "status_relay_channel_field", channel=f"<#{cfg.get('relay_channel_id')}>") if cfg.get("relay_channel_id") else bot_i18n.t(interaction.guild_id, "status_relay_channel_not_set"),
            bot_i18n.t(interaction.guild_id, "status_relay_out_field", state=on if cfg.get('relay_out') else off),
            bot_i18n.t(interaction.guild_id, "status_relay_in_field", state=on if cfg.get('relay_in') else off),
        ]
        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "chat_bridge_title"), description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── auto-detection rule commands ─────────────────────────
    @app_commands.command(name="auto-chat-add", description="Add an in-game chat trigger word with an auto-punishment (Admin)")
    @app_commands.describe(
        word="Word/trigger to detect in in-game chat",
        punishment="Punishment to apply",
        tempban_hours="Hours if punishment is tempban",
    )
    @app_commands.choices(punishment=[
        app_commands.Choice(name="Warn", value="warn"),
        app_commands.Choice(name="Temp-ban", value="tempban"),
        app_commands.Choice(name="Ban", value="ban"),
        app_commands.Choice(name="Blacklist", value="blacklist"),
    ])
    async def auto_chat_add(self, interaction: discord.Interaction, word: str,
                            punishment: app_commands.Choice[str], tempban_hours: int = 24):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        try:
            guild_settings.add_chat_auto_rule(interaction.guild_id, word, punishment.value, tempban_hours, interaction.user.id)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        self._auto_rules_cache.pop(interaction.guild_id, None)
        suffix = bot_i18n.t(interaction.guild_id, "hours_suffix", hours=tempban_hours) if punishment.value == "tempban" else ""
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "trigger_added", word=word, punishment=punishment.value, suffix=suffix), ephemeral=True,
        )

    @app_commands.command(name="auto-chat-remove", description="Remove an in-game chat trigger word (Admin)")
    @app_commands.describe(word="The trigger word to remove")
    async def auto_chat_remove(self, interaction: discord.Interaction, word: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        removed = False
        for r in guild_settings.get_chat_auto_rules(interaction.guild_id):
            if r["word"] == word.strip().lower():
                guild_settings.remove_chat_auto_rule(r["id"], interaction.guild_id)
                removed = True
        self._auto_rules_cache.pop(interaction.guild_id, None)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "trigger_removed", word=word) if removed else bot_i18n.t(interaction.guild_id, "trigger_not_found", word=word), ephemeral=True,
        )

    @app_commands.command(name="auto-chat-list", description="List all in-game chat trigger words (Admin)")
    async def auto_chat_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        rules = guild_settings.get_chat_auto_rules(interaction.guild_id)
        if not rules:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "no_auto_triggers"), ephemeral=True)
        lines = []
        for r in rules:
            extra = bot_i18n.t(interaction.guild_id, "hours_suffix", hours=r['tempban_hours']) if r["punishment"] == "tempban" else ""
            state = '✅' if r['enabled'] else '⛔'
            lines.append(f"#{r['id']} {state} **{r['word']}** → `{r['punishment']}{extra}`")
        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "triggers_title"), description="\n".join(lines[:20]), color=discord.Color.dark_red())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="auto-chat-toggle", description="Enable or disable a trigger word (Admin)")
    @app_commands.describe(word_id="Rule ID (see /auto-chat-list)", enabled="Enabled or disabled")
    async def auto_chat_toggle(self, interaction: discord.Interaction, word_id: int, enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.set_chat_auto_rule_enabled(word_id, interaction.guild_id, enabled)
        self._auto_rules_cache.pop(interaction.guild_id, None)
        state = bot_i18n.t(interaction.guild_id, "enabled_word") if enabled else bot_i18n.t(interaction.guild_id, "disabled_word")
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "trigger_toggled", word_id=word_id, state=state), ephemeral=True)

    @app_commands.command(name="auto-chat-clear", description="Remove all in-game chat trigger words (Admin)")
    async def auto_chat_clear(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.clear_chat_auto_rules(interaction.guild_id)
        self._auto_rules_cache.pop(interaction.guild_id, None)
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "triggers_cleared"), ephemeral=True)

    @app_commands.command(name="auto-chat-cooldown", description="Set minutes between repeated auto-punishments per player+word (Admin)")
    @app_commands.describe(minutes="Cooldown in minutes")
    async def auto_chat_cooldown(self, interaction: discord.Interaction, minutes: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_setting(interaction.guild_id, "chat_auto_cooldown_minutes", max(0, minutes))
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "cooldown_set", minutes=max(0, minutes)), ephemeral=True)


async def asyncio_to_thread(fn, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


async def setup(bot):
    await bot.add_cog(ChatBridge(bot))
