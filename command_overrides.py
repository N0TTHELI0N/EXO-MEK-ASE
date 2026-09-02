import discord
import guild_settings


_installed = False


def install():
    """Install a guarded hook so owner-set message overrides (from the
    dashboard Commands page) replace the default reply content of a slash
    command. Plain-text replies are overridden; embeds/uploads are left alone.
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
            name = getattr(cmd, "name", None)
            gid = getattr(interaction, "guild_id", None)
            if (
                name and gid
                and not kwargs.get("embed") and not kwargs.get("embeds")
                and not kwargs.get("file") and not kwargs.get("files")
                and not kwargs.get("attachments") and not kwargs.get("view")
            ):
                override = guild_settings.get_command_message(gid, name)
                if override:
                    content = override
        except Exception:
            pass
        return await _orig_send(self, content, *args, **kwargs)

    discord.InteractionResponse.send_message = _send_message