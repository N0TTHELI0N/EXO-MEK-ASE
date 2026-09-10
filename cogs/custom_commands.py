import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
import bot_i18n
import guild_settings
import nitrado


CATEGORY_META = {
    "dino_spawn": {"emoji": "🦖", "label": "Dino Spawning", "thread": "thread_dino"},
    "gfi": {"emoji": "🎁", "label": "GFI Commands", "thread": "thread_gfi"},
    "player": {"emoji": "🧍", "label": "Player Features", "thread": "thread_player"},
    "gcm": {"emoji": "🎮", "label": "GCM", "thread": "thread_gcm"},
    "other": {"emoji": "🗂️", "label": "Other", "thread": "thread_other"},
}


async def _normalize_thread(result):
    """Return a discord.Thread from the result of a forum create_thread call.

    discord.py returns a Thread, but some versions wrap it in a tuple —
    normalise so callers always get the Thread (or None).
    """
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, discord.Thread):
                return item
        return None
    return result if isinstance(result, discord.Thread) else None


class CustomCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.post_forum_logs.start()

    def cog_unload(self):
        self.post_forum_logs.cancel()

    # ── helpers ─────────────────────────────────────────────
    async def _build_command(self, command_string: str, user: discord.Member) -> str:
        """Fill placeholders in a custom/runner command string.

        Supported placeholders:
          {display_name} - invoking user's Discord display name
          {mention}      - a Discord user mention (pasted literally)
        """
        text = command_string.replace("{display_name}", user.display_name)
        text = text.replace("{mention}", user.mention)
        return text

    async def _execute(self, guild_id: int, command_string: str, category: str, user: discord.Member, source: str) -> str:
        """Send a command via Nitrado, log it with a category, and return a message for the user."""
        resp = await asyncio.to_thread(nitrado.send_rcon, guild_id, command_string)
        guild_settings.log_action(
            guild_id, "admin_command", user.id, str(user), None,
            sub_type="command_run", details={"command": command_string, "source": source, "category": category},
            log_category=category,
        )
        return resp

    async def _log_forum_message(self, guild_id: int, log_entry: dict) -> discord.Embed:
        meta = CATEGORY_META.get(log_entry.get("log_category"), CATEGORY_META["other"])
        who = log_entry.get("user_name") or f"User#{log_entry.get('user_id')}"
        details = log_entry.get("details") or {}
        cmd = details.get("command") or details.get("action") or log_entry.get("command") or ""
        embed = discord.Embed(
            title=bot_i18n.t(guild_id, "forum_log_title", emoji=meta['emoji'], label=meta['label']),
            description=bot_i18n.t(guild_id, "forum_log_body", who=who, cmd=cmd),
            color=discord.Color.blue(),
            timestamp=log_entry.get("created_at") or discord.utils.utcnow(),
        )
        embed.set_footer(text=f"log #{log_entry.get('id')}")
        return embed

    async def _shop_forum_message(self, guild_id: int, entry: dict) -> discord.Embed:
        sub = entry.get("sub_type")
        details = entry.get("details") or {}
        buyer = entry.get("user_name") or entry.get("player_name") or "?"
        dino = entry.get("player_name") or "?"
        level = details.get("level")
        price = details.get("price")
        pid = details.get("purchase_id", entry.get("id"))
        if sub == "purchase_delivered":
            title = bot_i18n.t(guild_id, "shop_delivery_done_title")
            desc = bot_i18n.t(guild_id, "shop_delivery_done_body", buyer=buyer, dino=dino, level=level)
            color = discord.Color.green()
        elif sub == "purchase_cancelled":
            title = bot_i18n.t(guild_id, "shop_delivery_cancelled_title")
            desc = bot_i18n.t(guild_id, "shop_delivery_cancelled_body", buyer=buyer, dino=dino, price=price)
            color = discord.Color.red()
        else:
            title = bot_i18n.t(guild_id, "shop_purchase_queued_title")
            desc = bot_i18n.t(guild_id, "shop_purchase_queued_body", buyer=buyer, dino=dino, level=level, price=price)
            color = discord.Color.blurple()
        embed = discord.Embed(
            title=title,
            description=desc,
            color=color,
            timestamp=entry.get("created_at") or discord.utils.utcnow(),
        )
        embed.set_footer(text=f"purchase #{pid}")
        return embed

    # ── background: post categorized logs to forum threads ──
    @tasks.loop(seconds=20)
    async def post_forum_logs(self):
        for guild in self.bot.guilds:
            # Admin-log forum (command categories).
            cfg = guild_settings.get_forum_log_config(guild.id)
            if cfg and cfg["forum_id"]:
                forum = guild.get_channel(cfg["forum_id"])
                if forum:
                    for entry in guild_settings.get_unposted_forum_logs(guild.id):
                        cat = entry.get("log_category") or "other"
                        meta = CATEGORY_META.get(cat, CATEGORY_META["other"])
                        thread_id = cfg.get(meta["thread"])
                        target = guild.get_thread(thread_id) if thread_id else None
                        if not target:
                            continue
                        try:
                            embed = await self._log_forum_message(guild.id, entry)
                            await target.send(embed=embed)
                            guild_settings.mark_log_posted(entry["id"])
                        except Exception:
                            continue
            # Shop forum (done / pending deliveries)
            scfg = guild_settings.get_shop_forum_config(guild.id)
            if scfg and scfg["forum_id"]:
                forum = guild.get_channel(scfg["forum_id"])
                if forum:
                    for entry in guild_settings.get_unposted_shop_logs(guild.id):
                        sub = entry.get("sub_type")
                        thread_key = "thread_pending" if sub == "purchase_pending" else "thread_done"
                        thread_id = scfg.get(thread_key)
                        target = guild.get_thread(thread_id) if thread_id else None
                        if not target:
                            continue
                        try:
                            embed = await self._shop_forum_message(guild.id, entry)
                            await target.send(embed=embed)
                            guild_settings.mark_shop_log_posted(entry["id"])
                        except Exception:
                            continue

    @post_forum_logs.before_loop
    async def before_post_forum_logs(self):
        await self.bot.wait_until_ready()

    # ── autocomplete for custom commands ────────────────────
    async def _custom_autocomplete(self, interaction: discord.Interaction, current: str):
        names = [c["name"] for c in guild_settings.get_custom_commands(interaction.guild_id)]
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    # ── /custom ─────────────────────────────────────────────
    @app_commands.command(name="custom", description="Run a custom server command")
    @app_commands.describe(name="Name of the custom command to run")
    @app_commands.autocomplete(name=_custom_autocomplete)
    async def custom(self, interaction: discord.Interaction, name: str):
        cmd = guild_settings.get_custom_command(interaction.guild_id, name)
        if not cmd:
            return await interaction.response.send_message(
                bot_i18n.t(interaction.guild_id, "custom_not_found", name=name), ephemeral=True
            )
        if not interaction.user.guild_permissions.administrator:
            if not cmd.get("enabled", True):
                return await interaction.response.send_message(
                    bot_i18n.t(interaction.guild_id, "command_disabled"), ephemeral=True
                )
            allowed_roles = guild_settings.get_command_permissions(interaction.guild_id, name)
            if allowed_roles and not ({r.id for r in interaction.user.roles} & set(allowed_roles)):
                return await interaction.response.send_message(
                    bot_i18n.t(interaction.guild_id, "custom_permission_denied"), ephemeral=True
                )
        final = await self._build_command(cmd["command_string"], interaction.user)
        await interaction.response.defer(ephemeral=False)
        resp = await self._execute(interaction.guild_id, final, cmd["category"], interaction.user, "custom")
        out = bot_i18n.t(interaction.guild_id, "custom_ran", command=final)
        if resp:
            out += f"\n```{resp[:1500]}```"
        await interaction.followup.send(out)

    # ── /custom-list ────────────────────────────────────────
    @app_commands.command(name="custom-list", description="List all custom commands (Admin only)")
    async def custom_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        cmds = guild_settings.get_custom_commands(interaction.guild_id)
        if not cmds:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "custom_empty"), ephemeral=True)
        meta = CATEGORY_META
        lines = []
        for c in cmds:
            m = meta.get(c["category"], CATEGORY_META["gcm"])
            enabled = bot_i18n.t(interaction.guild_id, "custom_disabled_suffix") if not c["enabled"] else ""
            lines.append(f"{m['emoji']} **/{c['name']}** → `{c['command_string']}`{enabled}")
        embed = discord.Embed(title=bot_i18n.t(interaction.guild_id, "custom_commands_title"), description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /custom-add ─────────────────────────────────────────
    @app_commands.command(name="custom-add", description="Create a custom server command (Admin only)")
    @app_commands.describe(name="Command name (lowercase, no spaces)", command_string="The ARK command to run", category="Log category")
    @app_commands.choices(category=[
        app_commands.Choice(name="Dino Spawning", value="dino_spawn"),
        app_commands.Choice(name="GFI Commands", value="gfi"),
        app_commands.Choice(name="Player Features", value="player"),
        app_commands.Choice(name="GCM", value="gcm"),
    ])
    async def custom_add(self, interaction: discord.Interaction, name: str, command_string: str, category: str = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        clean = name.strip().lower().replace(" ", "-")
        if not clean:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "invalid_command_name"), ephemeral=True)
        res = guild_settings.add_custom_command(interaction.guild_id, clean, command_string, category, interaction.user.id)
        await interaction.response.send_message(
            bot_i18n.t(interaction.guild_id, "custom_created", name=clean),
            ephemeral=True,
        )

    # ── /custom-remove ──────────────────────────────────────
    @app_commands.command(name="custom-remove", description="Delete a custom command (Admin only)")
    @app_commands.describe(name="Command name to delete")
    @app_commands.autocomplete(name=_custom_autocomplete)
    async def custom_remove(self, interaction: discord.Interaction, name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        removed = guild_settings.remove_custom_command(interaction.guild_id, name)
        if removed:
            await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "custom_deleted", name=name), ephemeral=True)
        else:
            await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "custom_not_found", name=name), ephemeral=True)

    # ── /ark-command (generic runner, off by default) ───────
    @app_commands.command(name="ark-command", description="Run a raw ARK console command (Admin, if enabled)")
    @app_commands.describe(command="The ARK console command to run")
    async def ark_command(self, interaction: discord.Interaction, command: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        if not guild_settings.get_bool_setting(interaction.guild_id, "runner_enabled", False):
            return await interaction.response.send_message(
                bot_i18n.t(interaction.guild_id, "runner_disabled"), ephemeral=True
            )
        final = await self._build_command(command, interaction.user)
        category = guild_settings.detect_log_category_for_guild(interaction.guild_id, final)
        await interaction.response.defer(ephemeral=False)
        resp = await self._execute(interaction.guild_id, final, category, interaction.user, "runner")
        out = bot_i18n.t(interaction.guild_id, "custom_ran", command=final)
        if resp:
            out += f"\n```{resp[:1500]}```"
        await interaction.followup.send(out)

    # ── /setup-logs ─────────────────────────────────────────
    LOG_KINDS = ("admin", "server", "chat", "shop", "tribes")

    async def _get_or_create_forum(self, guild: discord.Guild, name: str, topic: str, reason: str,
                                   channel: discord.TextChannel = None) -> discord.ForumChannel | None:
        forum = channel if isinstance(channel, discord.ForumChannel) else None
        if forum is not None:
            return forum
        try:
            return await guild.create_forum(name=name, topic=topic, reason=reason)
        except Exception:
            return None

    async def _ensure_forum_thread(self, forum: discord.ForumChannel, name: str, intro: str) -> int | None:
        existing = discord.utils.find(lambda t, n=name: n in t.name or t.name.startswith(n), forum.threads)
        if existing:
            return existing.id
        try:
            result = await forum.create_thread(name=name, content=intro)
            thread = await _normalize_thread(result)
            return thread.id if thread else None
        except Exception:
            return None

    async def _setup_admin_logs(self, guild: discord.Guild, channel=None):
        forum = await self._get_or_create_forum(guild, "admin-logs", bot_i18n.t(guild.id, "forum_topic"),
                                                "Admin log forum - created by setup-logs", channel)
        if forum is None:
            return None, "admin-logs: " + bot_i18n.t(guild.id, "forum_error", error="create failed")
        thread_ids, errors = {}, []
        for cat, meta in CATEGORY_META.items():
            existing = discord.utils.find(lambda t, m=meta: t.name.startswith(m["emoji"]) and m["label"] in t.name, forum.threads)
            if existing:
                thread_ids[meta["thread"]] = existing.id
                continue
            try:
                result = await forum.create_thread(
                    name=f"{meta['emoji']} {meta['label']}",
                    content=bot_i18n.t(guild.id, "forum_thread_intro", label=meta["label"]),
                )
                thread = await _normalize_thread(result)
                if thread is None:
                    raise RuntimeError("create_thread returned no thread")
                thread_ids[meta["thread"]] = thread.id
            except Exception as e:
                errors.append(f"{meta['label']}: {type(e).__name__}")
        if len(thread_ids) < len(CATEGORY_META):
            missing = [CATEGORY_META[c]["label"] for c in CATEGORY_META if CATEGORY_META[c]["thread"] not in thread_ids]
            errors_note = (" (" + "; ".join(errors) + ")") if errors else ""
            return None, bot_i18n.t(guild.id, "forums_partial", created=len(thread_ids), missing=', '.join(missing), errors=errors_note)
        guild_settings.set_forum_log_config(guild.id, forum.id,
                                            thread_ids.get("thread_dino"), thread_ids.get("thread_gfi"),
                                            thread_ids.get("thread_player"), thread_ids.get("thread_gcm"),
                                            thread_ids.get("thread_other"))
        return bot_i18n.t(guild.id, "forum_ready", forum=forum.mention,
                          thread_dino=thread_ids.get("thread_dino"), thread_gfi=thread_ids.get("thread_gfi"),
                          thread_player=thread_ids.get("thread_player"), thread_gcm=thread_ids.get("thread_gcm"),
                          thread_other=thread_ids.get("thread_other")), None

    async def _setup_shop_logs(self, guild: discord.Guild, channel=None):
        forum = await self._get_or_create_forum(guild, "shop-logs", bot_i18n.t(guild.id, "shop_forum_topic"),
                                                "Shop log forum - created by setup-logs", channel)
        if forum is None:
            return None, "shop-logs: " + bot_i18n.t(guild.id, "forum_error", error="create failed")
        thread_map = {"✅ Done Deliveries": "thread_done", "⏳ Pending Deliveries": "thread_pending"}
        thread_ids, errors = {}, []
        for tname, tkey in thread_map.items():
            existing = discord.utils.find(lambda t, n=tname: n in t.name or t.name.startswith(n.split()[-1]), forum.threads)
            if existing:
                thread_ids[tkey] = existing.id
                continue
            try:
                result = await forum.create_thread(name=tname, content=bot_i18n.t(guild.id, "shop_forum_thread_intro", label=tname))
                thread = await _normalize_thread(result)
                if thread is None:
                    raise RuntimeError("create_thread returned no thread")
                thread_ids[tkey] = thread.id
            except Exception as e:
                errors.append(f"{tname}: {type(e).__name__}")
        if len(thread_ids) < 2:
            missing = [t for t, k in thread_map.items() if k not in thread_ids]
            errors_note = (" (" + "; ".join(errors) + ")") if errors else ""
            return None, bot_i18n.t(guild.id, "shop_forum_partial", missing=', '.join(missing), errors=errors_note)
        guild_settings.set_shop_forum_config(guild.id, forum.id, thread_ids.get("thread_done"), thread_ids.get("thread_pending"))
        return bot_i18n.t(guild.id, "shop_forum_ready", forum=forum.mention,
                          thread_done=thread_ids.get("thread_done"), thread_pending=thread_ids.get("thread_pending")), None

    async def _ensure_server_log_threads(self, guild: discord.Guild, channel=None):
        """Make sure the server-logs forum exists with join / leave / chat threads."""
        forum = await self._get_or_create_forum(guild, "server-logs", bot_i18n.t(guild.id, "server_logs_topic"),
                                                "Server log forum - created by setup-logs", channel)
        if forum is None:
            return None, None, None, None, None
        join_tid = await self._ensure_forum_thread(forum, bot_i18n.t(guild.id, "server_logs_thread_join"),
                                                   bot_i18n.t(guild.id, "server_logs_thread_intro"))
        leave_tid = await self._ensure_forum_thread(forum, bot_i18n.t(guild.id, "server_logs_thread_leave"),
                                                    bot_i18n.t(guild.id, "server_logs_thread_intro"))
        chat_tid = await self._ensure_forum_thread(forum, bot_i18n.t(guild.id, "chat_forum_thread_name"),
                                                   bot_i18n.t(guild.id, "chat_forum_thread_intro"))
        return forum, join_tid, leave_tid, chat_tid

    async def _setup_server_logs(self, guild: discord.Guild, channel=None):
        forum, join_tid, leave_tid, chat_tid = await self._ensure_server_log_threads(guild, channel)
        if forum is None:
            return None, "server-logs: " + bot_i18n.t(guild.id, "forum_error", error="create failed")
        if not (join_tid and leave_tid and chat_tid):
            return None, "server-logs: " + bot_i18n.t(guild.id, "forum_error", error="thread failed")
        guild_settings.update_server_log_config(guild.id, enabled=True,
                                                server_forum_id=forum.id,
                                                join_thread_id=join_tid,
                                                leave_thread_id=leave_tid,
                                                chat_forum_id=forum.id,
                                                chat_thread_id=chat_tid)
        # The in-game monitoring that captures events must run to feed this forum.
        guild_settings.update_chat_bridge_config(guild.id, enabled=True)
        return bot_i18n.t(guild.id, "server_logs_forum_ready", forum=forum.mention,
                          join=join_tid, leave=leave_tid), None

    async def _setup_chat_logs(self, guild: discord.Guild, channel=None):
        forum, join_tid, leave_tid, chat_tid = await self._ensure_server_log_threads(guild, channel)
        if forum is None:
            return None, "server-logs: " + bot_i18n.t(guild.id, "forum_error", error="create failed")
        if not chat_tid:
            return None, "game-chat: " + bot_i18n.t(guild.id, "forum_error", error="thread failed")
        cfg = guild_settings.get_server_log_config(guild.id)
        guild_settings.update_server_log_config(guild.id, enabled=True,
                                                server_forum_id=forum.id,
                                                join_thread_id=join_tid or cfg.get("join_thread_id"),
                                                leave_thread_id=leave_tid or cfg.get("leave_thread_id"),
                                                chat_forum_id=forum.id,
                                                chat_thread_id=chat_tid,
                                                server_events_thread_id=cfg.get("server_events_thread_id"))
        guild_settings.update_chat_bridge_config(guild.id, enabled=True)
        return bot_i18n.t(guild.id, "chat_forum_ready", forum=forum.mention, thread=f"<#{chat_tid}>"), None

    @staticmethod
    def _known_tribes(guild_id: int) -> list[str]:
        conn = guild_settings.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT tribe_name FROM known_tribes WHERE guild_id = %s", (guild_id,))
                return [r[0] for r in cur.fetchall()]
        finally:
            conn.close()

    async def _ensure_tribe_thread(self, guild: discord.Guild, forum: discord.ForumChannel, tribe: str) -> int | None:
        cfg = guild_settings.get_tribe_forum_config(guild.id)
        if not cfg or cfg["forum_id"] != forum.id:
            guild_settings.set_tribe_forum_config(guild.id, forum.id)
        existing = discord.utils.find(lambda t, n=tribe: t.name == n or t.name.startswith(n) or n in t.name, forum.threads)
        if existing:
            guild_settings.set_tribe_thread(guild.id, tribe, existing.id)
            return existing.id
        try:
            result = await forum.create_thread(name=tribe, content=bot_i18n.t(guild.id, "tribe_forum_thread_intro", tribe=tribe))
            thread = await _normalize_thread(result)
            if thread is None:
                return None
            guild_settings.set_tribe_thread(guild.id, tribe, thread.id)
            return thread.id
        except Exception:
            return None

    async def _setup_tribe_logs(self, guild: discord.Guild, channel=None):
        forum = await self._get_or_create_forum(guild, "tribe-logs", bot_i18n.t(guild.id, "tribe_forum_topic"),
                                                "Tribe log forum - created by setup-logs", channel)
        if forum is None:
            return None, "tribe-logs: " + bot_i18n.t(guild.id, "forum_error", error="create failed")
        tribes = sorted(self._known_tribes(guild.id))
        created = []
        for tribe in tribes:
            thread_id = await self._ensure_tribe_thread(guild, forum, tribe)
            if thread_id:
                created.append((tribe, thread_id))
        if created:
            lines = "\n".join(f"  • **{t}** → <#{tid}>" for t, tid in created)
        else:
            lines = bot_i18n.t(guild.id, "tribe_forum_no_tribes")
        return bot_i18n.t(guild.id, "tribelog_forum_ready", forum=forum.mention, count=len(created), lines=lines), None

    @app_commands.command(name="setup-logs", description="Set up all log forums at once, or just one type (Admin only)")
    @app_commands.choices(which=[
        app_commands.Choice(name="All (every log)", value="all"),
        app_commands.Choice(name="Admin logs", value="admin"),
        app_commands.Choice(name="Server logs (join/leave)", value="server"),
        app_commands.Choice(name="Game chat", value="chat"),
        app_commands.Choice(name="Shop logs", value="shop"),
        app_commands.Choice(name="Tribe logs", value="tribes"),
    ])
    @app_commands.describe(
        which="Which log to set up",
        channel="Existing forum to use (optional - single selection only)",
    )
    async def setup_logs(self, interaction: discord.Interaction, which: str = "admin", channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(bot_i18n.t(interaction.guild_id, "admin_only"), ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        kinds = self.LOG_KINDS if which == "all" else (which,)
        setupers = {
            "admin": self._setup_admin_logs,
            "server": self._setup_server_logs,
            "chat": self._setup_chat_logs,
            "shop": self._setup_shop_logs,
            "tribes": self._setup_tribe_logs,
        }

        lines = []
        for kind in kinds:
            ok, err = await setupers[kind](interaction.guild, channel if len(kinds) == 1 else None)
            lines.append(ok if ok else err)
        await interaction.followup.send(
            bot_i18n.t(interaction.guild_id, "setup_logs_done", lines="\n".join(lines)),
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(CustomCommands(bot))
