import discord
from discord.ext import commands, tasks
from discord import app_commands
import bot_i18n
import guild_settings
import nitrado
import asyncio
import time


async def _normalize_thread(result):
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, discord.Thread):
                return item
        return None
    return result if isinstance(result, discord.Thread) else None


def _find_thread_by_name(forum, keywords) -> int | None:
    """Return the id of the first forum thread whose name matches any keyword."""
    if forum is None:
        return None
    for t in forum.threads:
        tn = str(t.name or "").lower()
        if any(k in tn for k in keywords):
            return t.id
    return None


def _forum_named(guild, name) -> discord.ForumChannel | None:
    for ch in guild.channels:
        if isinstance(ch, discord.ForumChannel) and str(ch.name or "").lower() == name:
            return ch
    return None


class ServerLogs(commands.Cog):
    """Server-logs forum (player join/leave) + game-chat forum.

    Events are captured by cogs/chat_bridge.py from the ARK server log; this
    cog owns the forums and posts the queued entries to their threads.
    """

    def __init__(self, bot):
        self.bot = bot
        self._diag_ts = {}
        self._posted_ts = {}
        print("[ServerLogs] build=c217e83", flush=True)
        self.post_server_logs.start()

    def cog_unload(self):
        self.post_server_logs.cancel()

    # ── background poster ────────────────────────────────────

    def _server_logs_cycle_sync(self, guild) -> dict | None:
        """Sync worker thread: Postgres reads + self-heal only (no Discord I/O)."""
        cfg = guild_settings.get_server_log_config(guild.id)
        if not cfg or cfg.get("enabled") is False:
            return None
        cfg = dict(cfg or {})
        # Self-heal: some thread ids may be missing (e.g. only "/setup-logs chat"
        # ran, or thread names changed). Resolve the missing ones now from the
        # log forums, matching name keywords rather than exact names.
        missing = [k for k in ("join_thread_id", "leave_thread_id", "chat_thread_id") if not cfg.get(k)]
        if missing:
            forum = guild.get_channel(cfg.get("server_forum_id") or 0)
            if not isinstance(forum, discord.ForumChannel):
                forum = _forum_named(guild, "server-logs")
            if isinstance(forum, discord.ForumChannel):
                ids = {}
                for t in forum.threads:
                    tn = str(t.name or "").lower()
                    if "join" in tn or "دخول" in tn or "انضمام" in tn:
                        ids.setdefault("join_thread_id", t.id)
                    elif "leave" in tn or "خروج" in tn or "مغادرة" in tn:
                        ids.setdefault("leave_thread_id", t.id)
                    elif "شات" in tn or "chat" in tn or "رسائل" in tn or "messages" in tn or "global" in tn:
                        ids.setdefault("chat_thread_id", t.id)
                if ids:
                    if not cfg.get("server_forum_id"):
                        ids["server_forum_id"] = forum.id
                    try:
                        guild_settings.update_server_log_config(guild.id, **ids)
                    except Exception:
                        pass
                    cfg = guild_settings.get_server_log_config(guild.id)
        # Resolve the admin event thread from its dedicated forum.
        special = {}
        if not cfg.get("admin_thread_id"):
            admin_forum = _forum_named(guild, "admin-logs")
            tid = _find_thread_by_name(admin_forum, ("admin", "ادارة", "إدارة", "logs"))
            if tid:
                special["admin_thread_id"] = tid
        if special:
            try:
                guild_settings.update_server_log_config(guild.id, **special)
            except Exception:
                pass
            cfg = guild_settings.get_server_log_config(guild.id)
        try:
            guild_settings.drop_stale_chat_forum_logs(guild.id, 300)
        except Exception:
            pass
        return {
            "cfg": cfg,
            "joins": guild_settings.get_unposted_server_events(guild.id, event_type="join"),
            "leaves": guild_settings.get_unposted_server_events(guild.id, event_type="leave"),
            "admins": guild_settings.get_unposted_server_events(guild.id, event_type="admin"),
            "chats": guild_settings.get_unposted_chat_forum_logs(guild.id),
        }

    async def _ensure_missing_threads(self, guild, cfg) -> None:
        """Create server-log threads when their ids are missing (e.g. only
        /setup-logs chat ran before). Matches existing threads by name and
        only creates what is actually absent."""
        forum = guild.get_channel(cfg.get("server_forum_id") or 0)
        if not isinstance(forum, discord.ForumChannel):
            forum = _forum_named(guild, "server-logs")
        made_forum = False
        if not isinstance(forum, discord.ForumChannel):
            try:
                forum = await guild.create_forum_channel("server-logs", topic=bot_i18n.t(guild.id, "server_logs_topic"))
                made_forum = True
            except Exception:
                forum = None
        updates = {}
        if made_forum and forum is not None:
            updates["server_forum_id"] = forum.id
        plan_threads = {
            "join_thread_id": (bot_i18n.t(guild.id, "server_logs_thread_join"),
                               ("join", "دخول", "انضمام")),
            "leave_thread_id": (bot_i18n.t(guild.id, "server_logs_thread_leave"),
                                ("leave", "خروج", "مغادرة")),
            "chat_thread_id": (bot_i18n.t(guild.id, "chat_forum_thread_name"),
                               ("شات", "chat", "رسائل", "messages")),
        }
        for key, (name, kws) in plan_threads.items():
            if cfg.get(key):
                continue
            if not isinstance(forum, discord.ForumChannel):
                continue
            tid = _find_thread_by_name(forum, kws)
            if tid:
                updates[key] = tid
                continue
            try:
                t = await forum.create_thread(name=name, content=bot_i18n.t(guild.id, "server_logs_thread_intro"))
                updates[key] = t.id
            except Exception:
                continue
        if not cfg.get("admin_thread_id"):
            admin_forum = _forum_named(guild, "admin-logs")
            if not isinstance(admin_forum, discord.ForumChannel):
                try:
                    admin_forum = await guild.create_forum_channel("admin-logs", topic=bot_i18n.t(guild.id, "forum_topic"))
                except Exception:
                    admin_forum = None
            if isinstance(admin_forum, discord.ForumChannel):
                tid = _find_thread_by_name(admin_forum, ("admin", "ادارة", "إدارة"))
                if not tid:
                    try:
                        t = await admin_forum.create_thread(
                            name=bot_i18n.t(guild.id, "server_logs_thread_admin"),
                            content=bot_i18n.t(guild.id, "server_logs_thread_intro_admin"))
                        updates["admin_thread_id"] = t.id
                    except Exception:
                        pass
                else:
                    updates["admin_thread_id"] = tid
        if updates:
            try:
                guild_settings.update_server_log_config(guild.id, **updates)
            except Exception:
                pass

    @staticmethod
    async def _resolve_thread(guild, thread_id) -> discord.Thread | None:
        """Resolve a thread by id, falling back to an API fetch.

        ``guild.get_thread`` only sees the cached threads (and archived threads
        are often missing from the guild cache after a restart), which made the
        admin forum thread silently unresolvable. Falling back to
        ``guild.fetch_channel`` still finds archived threads.
        """
        if not thread_id:
            return None
        t = guild.get_thread(thread_id)
        if isinstance(t, discord.Thread):
            return t
        try:
            ch = await guild.fetch_channel(thread_id)
        except Exception:
            return None
        return ch if isinstance(ch, discord.Thread) else None

    @staticmethod
    async def _unarchive_thread(thread: discord.Thread) -> None:
        if isinstance(thread, discord.Thread) and thread.archived:
            try:
                await thread.edit(archived=False, auto_archive_duration=10080)
            except Exception:
                pass

    @tasks.loop(seconds=15)
    async def post_server_logs(self):
        for guild in self.bot.guilds:
            try:
                plan = await asyncio.to_thread(self._server_logs_cycle_sync, guild)
            except Exception:
                continue
            if not plan:
                continue
            cfg = plan["cfg"]
            try:
                await self._ensure_missing_threads(guild, cfg)
                cfg = guild_settings.get_server_log_config(guild.id) or cfg
            except Exception:
                pass
            pending = (len(plan["chats"]), len(plan["joins"]), len(plan["leaves"]), len(plan["admins"]))
            if any(pending):
                nowp = time.time()
                if guild.id not in self._diag_ts or nowp - self._diag_ts[guild.id] >= 60:
                    self._diag_ts[guild.id] = nowp
                    print(f"[ServerLogs] gid={guild.id} pending chats={pending[0]} joins={pending[1]} leaves={pending[2]} admins={pending[3]} "
                          f"join_t={cfg.get('join_thread_id')} leave_t={cfg.get('leave_thread_id')} chat_t={cfg.get('chat_thread_id')} admin_t={cfg.get('admin_thread_id')}", flush=True)
            join_thread = await self._resolve_thread(guild, cfg.get("join_thread_id"))
            leave_thread = await self._resolve_thread(guild, cfg.get("leave_thread_id"))
            chat_thread = await self._resolve_thread(guild, cfg.get("chat_thread_id"))
            admin_thread = await self._resolve_thread(guild, cfg.get("admin_thread_id"))
            # Self-heal: ids that no longer resolve (thread deleted/renamed) are
            # dropped so _ensure_missing_threads recreates them next tick.
            stale = {}
            for key, th in (("join_thread_id", join_thread), ("leave_thread_id", leave_thread),
                            ("chat_thread_id", chat_thread), ("admin_thread_id", admin_thread)):
                if cfg.get(key) and th is None:
                    stale[key] = None
            if stale:
                try:
                    guild_settings.update_server_log_config(guild.id, **stale)
                except Exception:
                    pass
            for th in (join_thread, leave_thread, chat_thread, admin_thread):
                await self._unarchive_thread(th)

            if isinstance(join_thread, discord.Thread):
                for ev in plan["joins"]:
                    name = ev["player_name"] or "?"
                    raw = (ev["raw_line"] or "").strip()
                    try:
                        await join_thread.send(f"🟢 **{name}** — {bot_i18n.t(guild.id, 'server_event_join')}\n```{raw[:1850]}```")
                        await asyncio.to_thread(guild_settings.mark_server_event_posted, ev["id"])
                    except Exception:
                        continue

            if isinstance(leave_thread, discord.Thread):
                for ev in plan["leaves"]:
                    name = ev["player_name"] or "?"
                    raw = (ev["raw_line"] or "").strip()
                    try:
                        await leave_thread.send(f"🔴 **{name}** — {bot_i18n.t(guild.id, 'server_event_leave')}\n```{raw[:1850]}```")
                        await asyncio.to_thread(guild_settings.mark_server_event_posted, ev["id"])
                    except Exception:
                        continue

            if isinstance(admin_thread, discord.Thread):
                admin_fails = 0
                for ev in plan["admins"]:
                    raw = (ev["raw_line"] or "").strip()
                    try:
                        await admin_thread.send(f"🛠️ {bot_i18n.t(guild.id, 'server_log_admin')}\n```{raw[:1700]}```")
                        await asyncio.to_thread(guild_settings.mark_server_event_posted, ev["id"])
                    except Exception:
                        admin_fails += 1
                        continue
                if admin_fails:
                    print(f"[ServerLogs] gid={guild.id} admin send failures={admin_fails} thread={admin_thread.id}", flush=True)

            if isinstance(chat_thread, discord.Thread):
                posts = 0
                nowc = time.time()
                stale = []
                for log in plan["chats"]:
                    # Old backlog (queued for hours/days) is dropped, not replayed:
                    # replaying it floods the chat thread with stale posts.
                    rel = log.get("relayed_at")
                    age = (nowc - rel.timestamp()) if getattr(rel, "timestamp", None) else -1
                    if age > 300:
                        stale.append(log["id"])
                        continue
                    if posts >= 20:
                        break
                    raw = (log.get("raw_line") or log["message"] or "").strip()
                    icon = "➡️" if log["direction"] == "out" else "💬"
                    try:
                        await chat_thread.send(f"{icon}```{raw[:1850]}```")
                        await asyncio.to_thread(guild_settings.mark_chat_forum_posted, log["id"])
                        posts += 1
                    except Exception:
                        continue
                if stale:
                    try:
                        await asyncio.to_thread(guild_settings.mark_chat_forum_posted_batch, guild.id, stale)
                    except Exception:
                        pass
                if posts:
                    nowp2 = time.time()
                    if guild.id not in self._posted_ts or nowp2 - self._posted_ts[guild.id] >= 30:
                        print(f"[ServerLogs] gid={guild.id} posted chats={posts}", flush=True)
                        self._posted_ts[guild.id] = nowp2

    @post_server_logs.before_loop
    async def before_post_server_logs(self):
        await self.bot.wait_until_ready()

    # ── /server-logs-enable ──────────────────────────────────
    @app_commands.command(name="nitrado-debug", description="Diagnose Nitrado log reading (Admin)")
    async def nitrado_debug(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild_id

        def _run():
            client = nitrado.get_client(gid)
            if client is None:
                return "No Nitrado client — add token + service in the dashboard before this guild can read logs."
            out = [f"service_id={client.service_id}", f"token?={bool(client.api_token)}"]
            gs = client._server_gs() or {}
            out.append(f"status={gs.get('status')} game={gs.get('game')} user={gs.get('username')}")
            user = str(gs.get("username") or "").strip()
            try:
                code, body = client._raw("GET", "/services")
                svc = {}
                if isinstance(body, dict) and isinstance(body.get("data"), dict):
                    for s in body["data"].get("services") or []:
                        if isinstance(s, dict) and str(s.get("id")) == str(client.service_id):
                            svc = s
                            break
                out.append(f"ws_token={bool(svc.get('websocket_token'))}")
                extra_flags = " ".join(f"{k}={v}" for k, v in svc.items() if any(t in k.lower() for t in ("websocket", "app_server", "container")))
                if extra_flags:
                    out.append("flags: " + extra_flags)
                out.append("svc_keys=" + str(sorted(k for k in svc.keys() if not str(k).startswith("_")))[:300])
                if isinstance(svc.get("game_specific"), dict):
                    gall = svc.get("game_specific") or {}
                    if isinstance(gall, dict):
                        for k in ("features", "webinterface", "modlists"):
                            if gall.get(k) is not None:
                                out.append(f"game_specific.{k}={gall[k]}"[:300])
            except Exception as e:
                out.append(f"flags ERR {type(e).__name__}: {e}")
            try:
                code2, body2 = client._raw("GET", f"/services/{client.service_id}/gameservers/app_server")
                if isinstance(body2, dict):
                    shown = dict(body2)
                    for k, v in shown.items():
                        if isinstance(v, str) and any(t in k.lower() for t in ("token", "key", "secret", "socket", "url")):
                            shown[k] = f"{v[:10]}...({len(v)})"
                    out.append(f"app_server HTTP={code2} " + str(shown)[:700])
                else:
                    out.append(f"app_server HTTP={code2} body={str(body2)[:200]}")
            except Exception as e:
                out.append(f"app_server ERR {type(e).__name__}: {e}")
            if user:
                try:
                    restart = client.read_file_tail(f"/games/{user}/ftproot/restart.log", 5000)
                    if restart:
                        out.append("restart.log:\n" + restart[:500])
                    else:
                        out.append("restart.log: EMPTY or UNREACHABLE")
                except Exception as e:
                    out.append(f"restart.log ERR {type(e).__name__}: {e}")
            try:
                code3, body3 = client._raw("GET", f"/services/{client.service_id}/webinterface_login")
                if isinstance(body3, dict):
                    wi = body3.get("data", body3)
                    url = wi.get("url", "") if isinstance(wi, dict) else ""
                    expires = wi.get("expires_at") if isinstance(wi, dict) else None
                    out.append(f"webinterface_login HTTP={code3} url={url[:120]} expires={expires}")
                else:
                    out.append(f"webinterface_login HTTP={code3} body={str(body3)[:200]}")
            except Exception as e:
                out.append(f"webinterface_login ERR {type(e).__name__}: {e}")
            for ep in ("log", "logs", "players"):
                try:
                    code4, body4 = client._raw("GET", f"/services/{client.service_id}/gameservers/games/arkps/{ep}")
                    if isinstance(body4, dict):
                        d = body4.get("data", body4)
                        content = d.get("content", "") if isinstance(d, dict) else ""
                        out.append(f"arkps/{ep} HTTP={code4} content_len={len(content)}")
                        if content:
                            out.append("sample:\n" + "\n".join(content.split("\n")[-3:])[:400])
                    else:
                        out.append(f"arkps/{ep} HTTP={code4} body={str(body4)[:200]}")
                except Exception as e:
                    out.append(f"arkps/{ep} ERR {type(e).__name__}: {e}")
            roots = ["/", "/games", "/ftproot", "Server", "arkps"]
            if user:
                roots += [f"/games/{user}", f"/games/{user}/ftproot", f"/{user}"]
            res = []
            for r in roots:
                code, entries = client.file_server_list(r)
                n = len(entries) if isinstance(entries, list) else "?"
                res.append(f"HTTP{code}:{n} {r}")
            out.append("roots = " + " | ".join(res))
            for base in (["/", "Server", "arkps"] + ([f"/games/{user}", f"/games/{user}/ftproot", f"/games/{user}/Server"] if user else [])):
                for pat in ("ShooterGame.log", "ShooterGame_Last.log"):
                    code, entries = client.file_server_list(base, search=pat)
                    if not isinstance(entries, list):
                        continue
                    names = "; ".join(f"{e.get('name')}|{e.get('type')}" for e in entries[:5] if isinstance(e, dict))
                    if entries:
                        out.append(f"search {pat!r}@{base}: HTTP{code} n={len(entries)} [{names}]")
            path = client._discover_log_path()
            out.append(f"discovered_log={path or 'NONE'}")
            if path:
                text = client.read_file_tail(path)
                out.append(f"tail_chars={len(text) if text else 0}")
                if text:
                    out.append("sample:\n" + "\n".join(text.splitlines()[-30:])[:1200])
            else:
                text = client.get_logs(400)
                out.append(f"get_logs_chars={len(text) if text else 0}")
                if text:
                    out.append("sample:\n" + "\n".join(text.splitlines()[-30:])[:1200])
            return "\n".join(out)[:1900]

        try:
            result = await asyncio.to_thread(_run)
        except Exception as e:
            result = f"EXC {type(e).__name__}: {e}"
        await interaction.followup.send(f"```{result}```", ephemeral=True)

    @app_commands.command(name="server-logs-enable", description="Enable or disable posting to server-logs & game-chat forums (Admin)")
    @app_commands.describe(enabled="Enable or disable")
    async def server_logs_enable(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        guild_settings.update_server_log_config(interaction.guild_id, enabled=enabled)
        state = bot_i18n.t(interaction.guild_id, "enabled_word") if enabled else bot_i18n.t(interaction.guild_id, "disabled_word")
        await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "server_logs_toggled", state=state), ephemeral=True)


async def setup(bot):
    await bot.add_cog(ServerLogs(bot))