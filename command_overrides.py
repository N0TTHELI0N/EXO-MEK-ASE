import json

import discord
import guild_settings
from embed_builder import hex_to_color


_installed = False


def _apply_embed_overrides(embed, cfg):
    """Apply owner-defined display overrides onto a discord.Embed in place."""
    if cfg.get("title"):
        embed.title = cfg["title"][:256]
    if cfg.get("description"):
        embed.description = cfg["description"][:4096]
    if cfg.get("color"):
        try:
            embed.color = hex_to_color(cfg["color"])
        except Exception:
            pass
    if cfg.get("footer_text"):
        footer_kwargs = {}
        if embed.footer and embed.footer.icon_url:
            footer_kwargs["icon_url"] = embed.footer.icon_url
        embed.set_footer(text=cfg["footer_text"][:2048], **footer_kwargs)
    if cfg.get("thumbnail_url"):
        embed.set_thumbnail(url=cfg["thumbnail_url"])
    if cfg.get("image_url"):
        embed.set_image(url=cfg["image_url"])


def _apply_button_overrides(view, cfg):
    """Remap button labels by matching the button's known original label.

    The stored button config is a list of entries:
      {"label": "new label"} and optionally {"from": "old label"}.
    If "from" is given we only touch a matching button; otherwise we apply
    labels in order to the view's buttons (skipping Select/URL components).
    """
    buttons_cfg = cfg.get("buttons")
    if not buttons_cfg or not view:
        return

    ordered = [c for c in view.children]
    buttons = [c for c in ordered if isinstance(c, discord.ui.Button) and c.label]

    by_from = {}
    tail = []
    for entry in buttons_cfg:
        src = (entry or {}).get("from")
        if src:
            by_from[src] = entry.get("label")
        else:
            tail.append(entry.get("label"))

    for btn in buttons:
        if btn.label in by_from:
            btn.label = by_from[btn.label]
        elif tail:
            btn.label = tail.pop(0)


def install():
    """Install a guarded hook so owner-set display overrides (dashboard
    Customize Text / Commands pages) replace a slash command's default
    reply text, embed content and button labels.

    Layered from most..least specific:
      1. per-guild plain-text override (Commands page) -> replaces content
      2. global command display override (Customize Text) -> replaces
         content when no per-guild override, patch passed embeds in place,
         and remap button labels on the sent view.
    Any error falls back to the original behaviour."""
    global _installed
    if _installed:
        return
    _installed = True

    _orig_send = discord.InteractionResponse.send_message

    async def _send_message(self, content=None, *args, **kwargs):
        try:
            interaction = getattr(self, "_parent", None)
            cmd = getattr(interaction, "command", None)
            guild_id = getattr(interaction, "guild_id", None)
            name = getattr(cmd, "name", None)
            if name:
                has_plain = (
                    content is not None
                    and not kwargs.get("embed")
                    and not kwargs.get("embeds")
                    and not kwargs.get("file")
                    and not kwargs.get("files")
                    and not kwargs.get("attachments")
                    and not kwargs.get("view")
                )
                per_guild_msg = guild_settings.get_command_message(guild_id, name) if guild_id else None
                if per_guild_msg and has_plain:
                    content = per_guild_msg
                cfg = guild_settings.get_command_display(name)
                if cfg:
                    if not per_guild_msg and has_plain and cfg.get("plain_reply"):
                        content = cfg["plain_reply"]
                    for embed in (kwargs.get("embeds") or []):
                        _apply_embed_overrides(embed, cfg)
                    if kwargs.get("embed") is not None:
                        _apply_embed_overrides(kwargs["embed"], cfg)
                    if kwargs.get("view") is not None:
                        _apply_button_overrides(kwargs["view"], cfg)
        except Exception:
            pass
        return await _orig_send(self, content, *args, **kwargs)

    discord.InteractionResponse.send_message = _send_message