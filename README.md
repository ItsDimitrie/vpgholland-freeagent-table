# Holland Leaderboard Bot

Discord bot that:

- shows an embed with all users who currently have a configured role
- provides a button to add/remove that role
- automatically refreshes the embed when the role changes

## Features

- persistent button
- slash command to refresh manually
- slash command to post a new leaderboard message
- Railway-friendly setup
- optional CSV export for debugging

## Important Railway Note

The bot should be configured through environment variables:

- DISCORD_TOKEN
- GUILD_ID
- ROLE_ID
- CHANNEL_ID
- MESSAGE_ID

## Setup

### 3. Local run

```bash
pip install -r requirements.txt
python leaderboard_bot.py
```
