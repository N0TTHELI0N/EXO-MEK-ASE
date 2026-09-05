"""Generate commands_manifest.py from the actual slash-command decorators.

Scans cogs/*.py for:
    @app_commands.command(name="X", description="Y")
and emits an authoritative, ordered manifest of every registered command so the
dashboard Commands page never drifts from the real Discord slash commands.

Run from repo root:  <python> tools/gen_commands_manifest.py
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COGS_DIR = os.path.join(ROOT, "cogs")
OUT = os.path.join(ROOT, "commands_manifest.py")

DECORATOR_RE = re.compile(
    r"@app_commands\.command\(\s*name\s*=\s*([\"'])(?P<name>.*?)\1"
    r"(?:\s*,\s*description\s*=\s*([\"'])(?P<desc>.*?)\3)?"
)
DESC_RE = re.compile(r"description\s*=\s*([\"'])(.*?)\1")

CATEGORY_ORDER = [
    "general", "server", "custom", "moderation", "shop", "whitelist",
    "tribelog", "leaderboard", "automod", "chat", "admin", "other",
]

CATEGORY_LABELS = {
    "general": "General", "server": "Server", "custom": "Custom Commands",
    "moderation": "Moderation", "shop": "Shop", "whitelist": "Whitelist",
    "tribelog": "Tribe Log", "leaderboard": "Leaderboard", "automod": "Auto-Mod",
    "chat": "In-Game Chat", "admin": "Admin", "other": "Other",
}

# Explicit category override per command name (highest priority).
NAME_CATEGORY = {
    "help": "general",
    "set-language": "general",

    "top-players": "general",
    "server-status": "server",
    "server-restart": "server",
    "server-stop": "server",
    "add-tribe-member": "tribelog",
    "set-tribe-owner": "leaderboard",
    "add-tribe-points": "leaderboard",
    "remove-tribe-points": "leaderboard",
    "automod-add-word": "automod",
    "automod-remove-word": "automod",
    "automod-list-words": "automod",
    "automod-clear-words": "automod",
}

# Default category per cog file (used when no explicit override).
FILE_CATEGORY = {
    "admin.py": "admin",
    "help.py": "general",
    "custom_commands.py": "custom",
    "shop.py": "shop",
    "whitelist.py": "whitelist",
    "tribelog.py": "tribelog",
    "leaderboard.py": "leaderboard",
    "moderation.py": "moderation",
    "server_backup.py": "server",

    "playtime.py": "general",
    "chat_bridge.py": "chat",
    "player_ops.py": "moderation",
    "anti_abuse.py": "moderation",
    "cluster.py": "server",
    "staff.py": "admin",
}


def parse_file(path):
    commands = []
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    i = 0
    filenames = []
    while i < len(lines):
        line = lines[i]
        m = DECORATOR_RE.search(line)
        if not m:
            # handle @app_commands.command(\n    name="X",\n    description="Y")
            stripped = line.strip()
            if stripped.startswith("@app_commands.command(") and ")" not in line:
                joined = stripped
                j = i + 1
                while j < len(lines) and ")" not in lines[j]:
                    joined += " " + lines[j].strip()
                    j += 1
                if j < len(lines):
                    joined += " " + lines[j].strip()
                m = DECORATOR_RE.search(joined)
                if m:
                    name = m.group("name")
                    desc = m.group("desc") or ""
                    dm = DESC_RE.search(joined) if not desc else None
                    if dm:
                        desc = dm.group(2)
                    filenames.append(name)
                    commands.append((name, desc))
                    i = j
                    continue
            i += 1
            continue
        name = m.group("name")
        desc = m.group("desc") or ""
        if not desc:
            mm = DESC_RE.search(line)
            if mm:
                desc = mm.group(2)
        filenames.append(name)
        commands.append((name, desc))
        i += 1
    return commands, filenames


def main():
    all_cmds = {}
    order = []
    seen_files = set()
    for fname in sorted(os.listdir(COGS_DIR)):
        if not fname.endswith(".py"):
            continue
        seen_files.add(fname)
        path = os.path.join(COGS_DIR, fname)
        cmds, names = parse_file(path)
        for name, desc in cmds:
            if name in all_cmds:
                continue
            all_cmds[name] = desc
            order.append(name)

    # Build final list with category
    final = []
    for name in order:
        cat = NAME_CATEGORY.get(name)
        if not cat:
            # infer from file that declared it
            cat = "other"
        if cat not in CATEGORY_ORDER:
            cat = "other"
        final.append((name, cat, all_cmds[name]))

    # Fix categories using explicit overrides already applied; for names not
    # overridden, we already assigned via NAME_CATEGORY. Adjust any file-inferred
    # categories that are still "other" by re-scanning file context.
    # (Post-pass: map unset ones from declaration file.)
    declared = {}  # name -> category from file
    for fname in sorted(os.listdir(COGS_DIR)):
        if not fname.endswith(".py"):
            continue
        cmds, _ = parse_file(os.path.join(COGS_DIR, fname))
        base = FILE_CATEGORY.get(fname, "other")
        for name, _ in cmds:
            declared.setdefault(name, base)

    final = []
    for name in order:
        cat = NAME_CATEGORY.get(name) or declared.get(name, "other")
        if cat not in CATEGORY_ORDER:
            cat = "other"
        final.append((name, cat, all_cmds[name]))

    lines = []
    lines.append('"""')
    lines.append("AUTO-GENERATED by tools/gen_commands_manifest.py - DO NOT EDIT.")
    lines.append("")
    lines.append("Canonical list of every registered slash command, derived from")
    lines.append("the @app_commands.command decorators across cogs/. Regenerate with:")
    lines.append("    python tools/gen_commands_manifest.py")
    lines.append('"""')
    lines.append("")
    lines.append(f"CATEGORY_ORDER = {CATEGORY_ORDER!r}")
    lines.append("")
    lines.append(f"CATEGORY_LABELS = {CATEGORY_LABELS!r}")
    lines.append("")
    lines.append("# (name, category, default description)")
    lines.append("COMMANDS = [")
    for name, cat, desc in final:
        lines.append(f"    ({name!r}, {cat!r}, {desc!r}),")
    lines.append("]")
    header = "\n".join(lines) + "\n"
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"Wrote {len(final)} commands to commands_manifest.py")
    return final


if __name__ == "__main__":
    main()
