"""Security utilities for input sanitization."""

import re
import secrets
import string


def sanitize_rcon_name(name: str) -> str:
    """Sanitize a player/display name for safe use in RCON commands.
    
    Allows only alphanumeric characters, spaces, hyphens, underscores, and periods.
    Rejects anything that could be used for command injection.
    """
    if not name:
        return ""
    
    cleaned = re.sub(r'[^\w\s\-\.]', '', name, flags=re.UNICODE)
    cleaned = cleaned.strip()
    
    if not cleaned:
        return "Unknown"
    
    if len(cleaned) > 100:
        cleaned = cleaned[:100]
    
    return cleaned


def sanitize_rcon_input(text: str, max_length: int = 200) -> str:
    """General sanitization for RCON command parameters.
    
    Removes shell metacharacters and control characters.
    """
    if not text:
        return ""
    
    cleaned = re.sub(r'[`;|&\n\r\t\x00-\x1f]', '', text)
    cleaned = cleaned.strip()
    
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    
    return cleaned


def validate_path(path: str, base_dir: str) -> bool:
    """Validate that a path is within the allowed base directory."""
    import os
    try:
        resolved = os.path.realpath(path)
        base = os.path.realpath(base_dir)
        return resolved.startswith(base)
    except (ValueError, OSError):
        return False


def generate_secret_key(length: int = 32) -> str:
    """Generate a cryptographically secure random key."""
    return secrets.token_hex(length)


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret value, showing only the last few characters."""
    if not value:
        return ""
    if len(value) <= show_chars:
        return "*" * len(value)
    return "*" * (len(value) - show_chars) + value[-show_chars:]
