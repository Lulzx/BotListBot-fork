# The Telegram @BotListBot

This is the Chatbot in charge of maintaining the [Telegram BotList](https://t.me/botlist), a channel that is a community-driven approach to collect the best Bots on Telegram.

The bot simplifies navigation by acting as a mirror of the BotList, and automates the process of submitting, reviewing and publishing bots by the [BotListChat](https://t.me/botlistchat) community.

Licensed under the MIT License.

## Quickstart (5 minutes)

You need: **Python 3.7+**, **Docker**, and a **Telegram bot token** from [@BotFather](https://t.me/BotFather).

```bash
# 1. Clone and enter the repo
git clone https://github.com/JosXa/BotListBot.git
cd BotListBot

# 2. Start PostgreSQL
docker-compose up -d

# 3. Install dependencies
pip install pipenv
pipenv install

# 4. Configure environment
cp template.env .env
#    Now edit .env — at minimum set these two:
#      BOT_TOKEN=<your token from @BotFather>
#      DEVELOPER_ID=<your Telegram user ID>

# 5. Create and seed the database
pipenv run python scripts/initialize_database.py seed

# 6. Run the bot
pipenv run python -m botlistbot.main
```

The bot will send you "Ready to rock" on Telegram when it's up.

### How to find your Telegram user ID

Message [@userinfobot](https://t.me/userinfobot) on Telegram. It will reply with your numeric ID. Put that number in `DEVELOPER_ID` in your `.env` file, and add it to the `ADMINS` list in `botlistbot/settings.py` if you want admin access.

### Stopping

```bash
# Stop the bot: Ctrl+C in the terminal
# Stop the database:
docker-compose down
```

## Configuration

All settings are in `botlistbot/settings.py` and loaded from the `.env` file via `python-decouple`.

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | Yes | Telegram bot token from @BotFather |
| `DEVELOPER_ID` | Yes | Your Telegram user ID (receives error reports and startup message) |
| `DATABASE_URL` | Yes | PostgreSQL connection string (default works with docker-compose) |
| `DEV` | No | Set to `True` for polling mode (default). `False` uses webhooks. |
| `RUN_BOTCHECKER` | No | Set to `True` to enable the background bot checker worker |
| `API_ID` | If botchecker | Telegram API ID from https://my.telegram.org |
| `API_HASH` | If botchecker | Telegram API hash |
| `USERBOT_SESSION` | If botchecker | Pyrogram session name for the checker userbot |
| `USERBOT_PHONE` | If botchecker | Phone number for the checker userbot |
| `SENTRY_URL` | No | Sentry DSN for error tracking |
| `SENTRY_ENVIRONMENT` | No | Sentry environment name |

## Database

### Fresh setup

```bash
pipenv run python scripts/initialize_database.py seed
```

This creates all tables and inserts initial categories and a revision number.

### Migrating an existing database

If upgrading from an older version, run the BigInt migration to support newer Telegram user IDs:

```bash
pipenv run python -m botlistbot.migration.bigint_ids
```

This is needed because Telegram user IDs now exceed the 32-bit integer limit (~2.1 billion). Older databases used `INTEGER` columns that cannot store these IDs. The migration widens them to `BIGINT`.

## Project Structure

```
botlistbot/
    main.py                  # Entry point
    settings.py              # All configuration
    routing.py               # Handler registration and callback/forward/reply routing
    models/                  # Peewee ORM models (Bot, User, Category, etc.)
    components/
        admin.py             # Admin panel, bot approval, suggestions
        basic.py             # /start, main menu, channel post handler
        botlist.py           # Publishing the categorized bot list to @BotList channel
        botlistchat.py       # @BotListChat group management, hints
        botproperties.py     # Editing bot metadata
        broadcasts.py        # Admin broadcast messages
        contributions.py     # /new, /offline, /spam submissions
        explore.py           # Category browsing, bot details
        favorites.py         # User favorites
        inlinequeries.py     # Inline query handler
        search.py            # Search functionality
        userbot.py           # BotChecker bridge (Pyrogram userbot for pinging bots)
    botcheckerworker/
        botchecker.py        # Background worker that pings bots to check online status
    migration/               # Database migrations
    dialog/                  # Message templates
    lib/                     # Utility libraries
    assets/                  # Images, stickers, GIFs
scripts/
    initialize_database.py   # Database creation and seeding
```

## Key Features

- **Bot Submissions**: Users submit bots via `/new @botname` or `#new @botname` in @BotListChat
- **Admin Panel**: `/admin` for moderators to approve, edit, and manage bots
- **Channel Publishing**: Admins can push the full categorized bot list to the @BotList channel
- **Bot Checker**: Background worker pings all bots periodically to detect offline/online status
- **Search**: `/search` or inline query for finding bots
- **Favorites**: Users can save and manage favorite bots
- **Forward/Reply Detection**: Forward a message from a bot or reply to one to auto-lookup its details
