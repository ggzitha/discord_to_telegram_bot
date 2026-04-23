# Discord to Telegram Coordinates Bot

## Features Implemented
- **Scraper logic**: Given a link to `coord.pokedex100.com`, the Python script connects using a standard User-Agent and retrieves the coordinate `.value` field from the `<input id="community-coord">` tag.
- **Telegram integration**: The application natively handles parsing Telegram-acceptable HTML formats. Most importantly, it strips out the generic "Click for Coords" discord embeds and inserts a 1-tap-to-copy HTML `<code>...</code>` component. It also generates a quick Google Maps link.
- **Discord listener**: A complete bot listener written in `discord.py-self` to attach to your provided Discord user account. The bot listens specifically to messages from the selected channel (`717790953393487912`). Discovered coords are delegated to the scraper over an asynchronous queue/executor so they do not block the event loop.

## Testing Performed
- **Scraper Engine**: Validated that connecting to `coord.pokedex100.com` directly in python correctly fetches the parsed DOM and the HTML parser executes securely.
- **Telegram Integration**: Successfully sent an HTML parsed Telegram message with the newly built formats utilizing your Telegram Bot Token to your Chat ID (`710848361`).

## Setup Instructions
To run this application, ensure your environment is prepared. All project scripts reside in the `discord_to_telegram_bot` directory.

### Quick Setup with Docker
The easiest and cleanest way to run this application 24/7 is via Docker.
1. Make sure you have Docker installed.
2. Edit `.env` to include your `DISCORD_TOKEN` and `POKEDEX100_COOKIE` session ID.
3. Simply run `docker-compose up -d --build` (or `docker compose up -d --build`) within the `discord_to_telegram_bot` folder!

### Manual Python Setup
1. Ensure you have Python installed. The internal python virtual environment is prepared inside `./venv` and packages from [requirements.txt](file:///d:/004_Programming_Things/001_Full-Stack/AI-Coded/Pogo-Tracks/discord_to_telegram_bot/requirements.txt) are already installed inside it.
2. In the project directory, run: `.\venv\Scripts\python main.py`
3. **CRITICAL**: Before running the bot, please copy [.env.example](file:///d:/004_Programming_Things/001_Full-Stack/AI-Coded/Pogo-Tracks/discord_to_telegram_bot/.env.example) into a `.env` file (or just edit [.env.example](file:///d:/004_Programming_Things/001_Full-Stack/AI-Coded/Pogo-Tracks/discord_to_telegram_bot/.env.example) directly for testing) and set `DISCORD_TOKEN` to your personal User Discord Token and `POKEDEX100_COOKIE` to your Pokedex100 session cookie.

> [!CAUTION]
> Utilizing automated tools acting as a Discord User account (self-botting) violates Discord's Terms of Service. Be mindful that scraping continuous flows over long-held sessions can flag your discord account, despite `discord.py-self` mimicking regular web behavior closely. Use at your own discretion!
