# -*- coding: utf-8 -*-
"""gettribelog — read-only tribe log viewer.

This cog ONLY READS the two document tables (known_tribes + tribe_log_events)
that are kept untouched after the now-removed "player log" auto-relay system.
It never relays, never starts threads, never watches log files, and never
writes to the DB.  It renders the dashboard-style tribe log message that was
requested (example format only).
"""
import asyncio
import time
from datetime import datetime, timezone

import discord
import guild_settings
import bot_i18n


# i18n-friendly fallbacks (kept local so the cog works without a dashboard row)
_T = {
    "gettribelog_header_after": {
        "ar": "آخر فحص للسيرفر",
        "default": "Last Server Check",
    },
    "gettribelog_struct": {
        "ar": "سجل تدمير الهياكل",
        "default": "Structure Destroyed Log",
    },
    "gettribelog_dino": {
        "ar": "سجل مقتل الديناصورات",
        "default": "Dino Killed Log",
    },
    "gettribelog_empty": {
        "ar": "_لا توجد أحداث مسجلة بعد._",
        "default": "_No logged events yet._",
    },
    "gettribelog_no_tribe": {
        "ar": "لا توجد قبيلة بهذا الاسم في سجلات هذا السيرفر.",
        "default": "No tribe with that name is on record for this server.",
    },
    "gettribelog_need_name": {
        "ar": "اكتب اسم القبيلة: `/gettribelog tribename:اسم القبيلة`",
        "default": "Provide a tribe name: `/gettribelog tribename:<name>`",
    },
    "gettribelog_link1": {
        "ar": "تريد رؤية كل السجلات في الديسكورد؟",
        "default": "Want to see all your logs in discord?",
    },
    "gettribelog_link2": {
        "ar": "⤷ استخدم الأمر /linktribe لربط قبيلتك",
        "default": "⤷ Use the command /linktribe to link your tribe",
    },
    "gettribelog_link3": {
        "ar": "⤷ ثم استخدم الأمر /linktribelog لضبط قناة لاستقبال السجلات",
        "default": "⤷ Then use the command /linktribelog to setup a channel to recieve logs",
    },
    "gettribelog_rel_fmt": {
        "ar": "منذ {s}",
        "default": "{s} ago",
    },
}


def _t(guild_id: int, key: str, **kw) -> str:
    try:
        return bot_i18n.t(guild_id, key, **kw)
    except Exception:
        row = _T.get(key, {})
        fmt = row.get("ar", row.get("default", key))
        for k, v in kw.items():
            fmt = fmt.replace("{%s}" % k, str(v))
        return fmt


def _rel_ts(ts) -> str:
    """Render a timestamp as a Discord relative <t:...:R> label, else '—'."""
    if not ts:
        return "—"
    try:
        if isinstance(ts, (int, float)):
            stamp = int(ts)
        else:
            stamp = int(ts.timestamp())
    except Exception:
        return "—"
    return f"<t:{stamp}:R>"


class Gettribelog(commands.Cog):
    """Read-only /gettribelog — renders a tribe's stored log message."""

    def __init__(self, bot):
        self.bot = bot

    # ── /gettribelog ────────────────────────────────────────────────────────
    @app_commands.command(name="gettribelog", description="Show a tribe's stored log (read-only view)")
    @app_commands.describe(tribename="Tribe name as stored in the dashboard log")
    async def gettribelog(self, interaction: discord.Interaction, tribename: str):
        if interaction.guild is None:
            return
        guild_id = interaction.guild.id
        name = (tribename or "").strip()
        if not name:
            return await interaction.response.send_message(
                _t(guild_id, "gettribelog_need_name"), ephemeral=True
            )

        # Read-only lookups against the kept tables (never write).
        tribe_rows = await asyncio.to_thread(guild_settings.get_known_tribes, guild_id)
        match = None
        for row in tribe_rows:
            if (row.get("name") or "").lower() == name.lower():
                match = row
                break

        events = await asyncio.to_thread(
            guild_settings.get_tribe_log_events, guild_id, name, 60
        )

        if not match and not events:
            return await interaction.response.send_message(
                _t(guild_id, "gettribelog_no_tribe"), ephemeral=True
            )

        display = (match.get("name") if match else name) or name

        # Split events into structure-destroyed vs dino-killed by content shape.
        destroyed = []
        dino_killed = []
        for ev in events or []:
            content = (ev.get("content") or "").strip()
            if not content:
                continue
            ts = ev.get("created_at")
            stamp = _rel_ts(ts)
            low = content.lower()
            if "killed by" in low or "killed" in low or "قتل" in low:
                dino_killed.append(f"{stamp} - {content}")
            else:
                destroyed.append(f"{stamp} - {content}")

        last_check = None
        if events:
            last_check = max((ev.get("created_at") for ev in events), default=None)

        lines = [f"**👥 Tribe:** {display}"]
        lines.append(f"**{_t(guild_id, 'gettribelog_header_after')}:** {_rel_ts(last_check)}")
        lines.append("")
        lines.append(f"**💥 {_t(guild_id, 'gettribelog_struct')}**")
        if destroyed:
            lines.extend(destroyed[:15])
        else:
            lines.append(_t(guild_id, "gettribelog_empty"))
        lines.append("")
        lines.append(f"**⚔️ {_t(guild_id, 'gettribelog_dino')}**")
        if dino_killed:
            lines.extend(dino_killed[:15])
        else:
            lines.append(_t(guild_id, "gettribelog_empty"))
        lines.append("")
        lines.append(_t(guild_id, "gettribelog_link1"))
        lines.append(_t(guild_id, "gettribelog_link2"))
        lines.append(_t(guild_id, "gettribelog_link3"))

        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "…"
        await interaction.response.send_message(text, ephemeral=False)


async def setup(bot):
    await bot.add_cog(Gettribelog(bot))
