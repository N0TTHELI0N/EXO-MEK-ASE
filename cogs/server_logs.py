import discord
from discord.ext import commands, tasks
from discord import app_commands
import bot_i18n
import guild_settings
import nitrado
import asyncio


async def _normalize_thread(result):
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, discord.Thread):
                return item
        return None
    return result if isinstance(result, discord.Thread) else None


class ServerLogs(commands.Cog):
    """Server-logs forum (player join/leave) + game-chat forum.

    Events are captured by cogs/chat_bridge.py from the ARK server log; this
    cog owns the two forums and posts the queued entries to their threads.
    """

    def __init__(self, bot):
        self.bot = bot
        self.post_server_logs.start()

    def cog_unload(self):
        self.post_server_logs.cancel()

    # ── background poster ────────────────────────────────────

    @tasks.loop(seconds=15)
    async def post_server_logs(self):
        for guild in self.bot.guilds:
            cfg = guild_settings.get_server_log_config(guild.id)
            if not cfg or cfg.get("enabled") is False:
                continue
            # Self-heal: a "server-logs" forum exists but its thread ids are not
            # saved yet (e.g. no /setup-logs run on this build). Resolve them now.
            if not (cfg.get("join_thread_id") or cfg.get("leave_thread_id") or cfg.get("chat_thread_id")):
                forum = guild.get_channel(cfg.get("server_forum_id") or 0)
                if not isinstance(forum, discord.ForumChannel):
                    forum = discord.utils.get(guild.channels, name="server-logs")
                if isinstance(forum, discord.ForumChannel):
                    ids = {}
                    for t in forum.threads:
                        if "دخول" in t.name:
                            ids["join_thread_id"] = t.id
                        elif "خروج" in t.name:
                            ids["leave_thread_id"] = t.id
                        elif "شات" in t.name or "chat" in t.name.lower():
                            ids["chat_thread_id"] = t.id
                    if ids:
                        ids["server_forum_id"] = forum.id
                        guild_settings.update_server_log_config(guild.id, **ids)
                        cfg = guild_settings.get_server_log_config(guild.id)
            join_thread = guild.get_thread(cfg.get("join_thread_id") or cfg.get("server_events_thread_id")) if cfg.get("join_thread_id") or cfg.get("server_events_thread_id") else None
            leave_thread = guild.get_thread(cfg.get("leave_thread_id") or cfg.get("server_events_thread_id")) if cfg.get("leave_thread_id") or cfg.get("server_events_thread_id") else None
            chat_thread = guild.get_thread(cfg.get("chat_thread_id")) if cfg.get("chat_thread_id") else None

            if isinstance(join_thread, discord.Thread):
                for ev in guild_settings.get_unposted_server_events(guild.id, event_type="join"):
                    name = ev["player_name"] or "?"
                    ts = int(ev["created_at"].timestamp()) if getattr(ev["created_at"], "timestamp", None) else None
                    ts_part = f" · <t:{ts}:f>" if ts else ""
                    try:
                        await join_thread.send(f"🟢 **{name}** — {bot_i18n.t(guild.id, 'server_event_join')}{ts_part}")
                        guild_settings.mark_server_event_posted(ev["id"])
                    except Exception:
                        break

            if isinstance(leave_thread, discord.Thread):
                for ev in guild_settings.get_unposted_server_events(guild.id, event_type="leave"):
                    name = ev["player_name"] or "?"
                    ts = int(ev["created_at"].timestamp()) if getattr(ev["created_at"], "timestamp", None) else None
                    ts_part = f" · <t:{ts}:f>" if ts else ""
                    try:
                        await leave_thread.send(f"🔴 **{name}** — {bot_i18n.t(guild.id, 'server_event_leave')}{ts_part}")
                        guild_settings.mark_server_event_posted(ev["id"])
                    except Exception:
                        break

            if isinstance(chat_thread, discord.Thread):
                posts = 0
                for log in guild_settings.get_unposted_chat_forum_logs(guild.id):
                    if posts >= 15:
                        break
                    player = log["player_name"] or "?"
                    icon = "➡️" if log["direction"] == "out" else "💬"
                    channel = (log["channel"] or "global").replace("[", "").replace("]", "")
                    try:
                        await chat_thread.send(f"{icon} `{channel}` **{player}**: {log['message'][:1900]}")
                        guild_settings.mark_chat_forum_posted(log["id"])
                        posts += 1
                    except Exception:
                        break

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
                if isinstance(svc.get("game_specific"), dict):
                    gall = svc.get("game_specific") or {}
                    if isinstance(gall, dict):
                        for k in ("features", "webinterface", "modlists"):
                            if gall.get(k) is not None:
                                out.append(f"game_specific.{k}={gall[k]}"[:300])
            except Exception as e:
                out.append(f"flags ERR {type(e).__name__}: {e}")
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
                    out.append("sample:\n" + "\n".join(text.splitlines()[-3:])[:600])
            else:
                text = client.get_logs(400)
                out.append(f"get_logs_chars={len(text) if text else 0}")
                if text:
                    out.append("sample:\n" + "\n".join(text.splitlines()[-3:])[:600])
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