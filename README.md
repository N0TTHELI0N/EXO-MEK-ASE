# Exo-Mek ASE - ARK Survival Evolved Discord Bot

Advanced admin bot for ARK: Survival Evolved servers hosted on Nitrado.

## Features

- **Server Management** - Nitrado API commands, server status, restart/stop
- **Moderation** - Ban, tempban, warn, wipe players/tribes
- **Shop System** - Buy dinos with points, manage shop
- **Whitelist** - PSN linking, auto-restart with whitelist update
- **Tribe Log** - Monitor tribe activity via file or Nitrado API
- **Leaderboard** - Tribe points and rankings
- **Server Backup** - Create, restore backups via Nitrado Cloud Backup API
- **AutoMod** - Profanity filter, spam detection, custom words
- **Dashboard** - Web panel for all settings

## Requirements

- Python 3.11+
- PostgreSQL database
- Nitrado server with API access
- Discord Bot Token

## Environment Variables

See `.env.example` for all required variables.

## Deployment

### Render
1. Push to GitHub
2. Create new Web Service on Render
3. Connect your GitHub repo
4. Set environment variables
5. Deploy

### Local
```bash
pip install -r requirements.txt
python main.py
```

## License

Private - All rights reserved.
