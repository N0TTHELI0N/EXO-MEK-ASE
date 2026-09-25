# reset_playtime.py - One-off helper to clear bogus playtime data.
#
# The tracker previously accumulated 60s per player for the ENTIRE historical
# roster every minute (because the Nitrado /players endpoint returns everyone
# with an `online` flag, and we ignored that flag). This wiped the polluted rows
# so playtime restarts cleanly with the online-only tracking fix.
#
# Run ONCE on the server (where DATABASE_URL is available):
#   python reset_playtime.py
# Optional: reset only one guild:
#   python reset_playtime.py <guild_id>

import sys
import guild_settings


def main():
    guild_id = None
    if len(sys.argv) > 1:
        try:
            guild_id = int(sys.argv[1])
        except ValueError:
            print("Usage: python reset_playtime.py [guild_id]")
            return 1
    guild_settings.reset_playtime(guild_id)
    scope = f"guild {guild_id}" if guild_id is not None else "ALL guilds"
    print(f"playtime reset done for {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
