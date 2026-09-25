# embed_builder.py - Build Discord embeds from customizable database templates
# Used by both the bot cogs and the web dashboard

import json
import discord
import guild_settings


def hex_to_color(hex_str: str) -> discord.Color:
    """Convert a hex color string like '#FF0000' or 'FF0000' to discord.Color."""
    hex_str = hex_str.strip().lstrip("#")
    try:
        return discord.Color(int(hex_str, 16))
    except (ValueError, TypeError):
        return discord.Color.gold()


def build_embed(
    guild_id: int,
    embed_key: str,
    *,
    title_override: str = None,
    description_override: str = None,
    fields: list[dict] = None,
    image_url: str = None,
    thumbnail_url: str = None,
    author_name: str = None,
    footer_text: str = None,
    color_override: str = None,
) -> discord.Embed:
    """
    Build a Discord embed from a stored template, with optional overrides.

    Args:
        guild_id: The Discord guild ID
        embed_key: Template key (e.g. 'automod_alert', 'ban_notification')
        title_override: Override the template title
        description_override: Override the template description
        fields: List of {"name": str, "value": str, "inline": bool}
        image_url: Override image URL
        thumbnail_url: Override thumbnail URL
        author_name: Override author name
        footer_text: Override footer text
        color_override: Override color (hex string)

    Returns:
        discord.Embed ready to send
    """
    template = guild_settings.get_embed_template(guild_id, embed_key)

    title = title_override if title_override is not None else template.get("title", "")
    description = description_override if description_override is not None else template.get("description", "")
    color = color_override if color_override is not None else template.get("color", "#FFD700")
    img = image_url if image_url is not None else template.get("image_url", "")
    thumb = thumbnail_url if thumbnail_url is not None else template.get("thumbnail_url", "")
    foot = footer_text if footer_text is not None else template.get("footer_text", "")
    auth = author_name if author_name is not None else template.get("author_name", "")

    embed = discord.Embed(
        title=title[:256] if title else None,
        description=description[:4096] if description else None,
        color=hex_to_color(color),
    )

    if auth:
        embed.set_author(name=auth[:256])

    if img:
        embed.set_image(url=img)

    if thumb:
        embed.set_thumbnail(url=thumb)

    if foot:
        embed.set_footer(text=foot[:2048])

    if fields:
        for field in fields[:25]:  # Discord max 25 fields
            name = field.get("name", "")[:256]
            value = field.get("value", "")[:1024]
            inline = field.get("inline", False)
            if name and value:
                embed.add_field(name=name, value=value, inline=inline)

    return embed


def preview_embed(guild_id: int, embed_key: str) -> dict:
    """
    Return embed data as a dictionary for the web dashboard.
    Useful for rendering a preview without needing a Discord connection.
    """
    template = guild_settings.get_embed_template(guild_id, embed_key)
    return {
        "title": template.get("title", ""),
        "description": template.get("description", ""),
        "color": template.get("color", "#FFD700"),
        "image_url": template.get("image_url", ""),
        "thumbnail_url": template.get("thumbnail_url", ""),
        "footer_text": template.get("footer_text", ""),
        "author_name": template.get("author_name", ""),
    }
