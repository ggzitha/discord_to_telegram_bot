import os
import re
import asyncio
import logging
import discord
import threading
import time
import requests
import signal
import json
from dotenv import load_dotenv

from scraper import scrape_coordinates_from_url
from telegram_sender import send_telegram_message

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

DISCORD_TOKEN      = os.getenv('DISCORD_TOKEN')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID', '')

# ──────────────────────────────────────────────
# Discord Channel IDs
# ──────────────────────────────────────────────
PVP_CHANNEL_ID   = 717790953393487912   # /pvp channel
HUNDO_CHANNEL_ID = 259536527221063683   # /hundo channel

# ──────────────────────────────────────────────
# App State
# ──────────────────────────────────────────────
# Listening mode: 'pvp' | 'hundo' | 'both' | 'off'
LISTEN_MODE = 'off'

# Shared location filter (applies to both modes)
CURRENT_LOCATIONS = []      # empty = ALL

# PVP-only filters
CURRENT_CPS          = []   # empty = ALL  (cp500 / cp1500 / cp2500)
CURRENT_PVP_POKEMON  = []   # empty = ALL

# Hundo-only filter
CURRENT_HUNDO_POKEMON = []  # empty = ALL

LAST_UPDATE_ID   = 0
discord_client   = None
discord_loop     = None
discord_thread   = None
discord_start_time = None
AUTO_STOP_HOURS  = float(os.getenv('AutoStop', 0))
APP_RUNNING      = True

# ──────────────────────────────────────────────
# Pokédex Cache
# ──────────────────────────────────────────────
POKEDEX_FILE  = 'pokedex.json'
VALID_POKEMON = set()

def load_or_update_pokedex(force_update=False):
    global VALID_POKEMON
    if not force_update and os.path.exists(POKEDEX_FILE):
        try:
            with open(POKEDEX_FILE, 'r') as f:
                data = json.load(f)
                VALID_POKEMON = set(data)
                logger.info(f"Loaded {len(VALID_POKEMON)} Pokemon from local {POKEDEX_FILE}.")
                return True
        except Exception as e:
            logger.warning(f"Failed to read {POKEDEX_FILE}: {e}")

    try:
        logger.info("Downloading Pokemon vocabulary from PokeAPI (pokemon-species)...")
        res = requests.get('https://pokeapi.co/api/v2/pokemon-species?limit=2000', timeout=10).json()
        pokemon_list = [p['name'].lower() for p in res['results']]
        VALID_POKEMON = set(pokemon_list)
        with open(POKEDEX_FILE, 'w') as f:
            json.dump(pokemon_list, f)
        logger.info(f"Saved {len(VALID_POKEMON)} Pokemon to {POKEDEX_FILE}.")
        return True
    except Exception as e:
        logger.warning(f"Could not fetch Pokemon vocabulary: {e}")
        return False

load_or_update_pokedex()

# ──────────────────────────────────────────────
# Signal / Graceful Shutdown
# ──────────────────────────────────────────────
def handle_shutdown(signum, frame):
    global APP_RUNNING
    logger.info("\nGraceful shutdown signal received! Cleaning up...")
    APP_RUNNING = False
    raise KeyboardInterrupt

# ──────────────────────────────────────────────
# Emoji / Text Helpers
# ──────────────────────────────────────────────
def translate_emojis(t):
    emoji_map = {':shiny:': '✨', ':100:': '💯', ':tr:': '🚀'}
    for k, v in emoji_map.items():
        t = t.replace(k, v)

    def flag_repl(m):
        code = m.group(1).upper()
        if len(code) == 2:
            return chr(ord(code[0]) + 127397) + chr(ord(code[1]) + 127397)
        return m.group(0)

    t = re.sub(r':flag_([a-zA-Z]{2}):', flag_repl, t, flags=re.IGNORECASE)
    t = re.sub(r':(\d+):', r'#\1', t)
    return t

def build_telegram_message(raw_text, lat_lng, header):
    clean = re.sub(r'<a?:([^:]+):\d+>', r':\1:', raw_text)
    clean = translate_emojis(clean)
    html  = re.sub(r'\*\*\*(.*?)\*\*\*', r'<b><i>\1</i></b>', clean)
    html  = re.sub(r'\*\*(.*?)\*\*',     r'<b>\1</b>',        html)
    html  = re.sub(r'\*(.*?)\*',         r'<i>\1</i>',         html)
    return (
        f"{header}\n"
        f"{html}\n\n"
        f"<b>Coordinates:</b>\n"
        f"<code>{lat_lng}</code>\n"
        f"<a href='https://maps.google.com/maps?q={lat_lng}'>Google Maps</a>"
    )

# ──────────────────────────────────────────────
# CP alias matching helper
# ──────────────────────────────────────────────
CP_ALIASES = {
    'cp500':  ['cp500',  'little league', 'little cup'],
    'cp1500': ['cp1500', 'great league'],
    'cp2500': ['cp2500', 'ultra league'],
}

def matches_cp_filters(raw_lower):
    if not CURRENT_CPS:
        return True
    for cpf in CURRENT_CPS:
        aliases = CP_ALIASES.get(cpf, [cpf])
        if any(a in raw_lower for a in aliases):
            return True
    return False

# ──────────────────────────────────────────────
# Discord Client
# ──────────────────────────────────────────────
class PogoCoordsClient(discord.Client):
    async def on_ready(self):
        logger.info(f'Logged on as {self.user}!')

    async def on_message(self, message):
        channel_id = message.channel.id

        # Determine which mode applies to this channel
        if LISTEN_MODE == 'pvp'   and channel_id != PVP_CHANNEL_ID:
            return
        if LISTEN_MODE == 'hundo' and channel_id != HUNDO_CHANNEL_ID:
            return
        if LISTEN_MODE == 'both'  and channel_id not in (PVP_CHANNEL_ID, HUNDO_CHANNEL_ID):
            return
        if LISTEN_MODE == 'off':
            return

        is_pvp   = (channel_id == PVP_CHANNEL_ID)
        is_hundo = (channel_id == HUNDO_CHANNEL_ID)

        # ── Extract coords URL ──────────────────
        coords_url = None
        for embed in message.embeds:
            if embed.description:
                m = re.search(r'(https://coord\.pokedex100\.com/[^\s\)]+)', embed.description)
                if m:
                    coords_url = m.group(1)
                    break
        if not coords_url and message.content:
            m = re.search(r'(https://coord\.pokedex100\.com/[^\s\)]+)', message.content)
            if m:
                coords_url = m.group(1)
        if not coords_url:
            return

        # ── Build raw text ──────────────────────
        content_lines = []
        if message.content:
            content_lines.append(message.content)
        for embed in message.embeds:
            if embed.description:
                desc = re.sub(r'\[.*?Click for Coords.*?\].*', '', embed.description, flags=re.DOTALL)
                content_lines.append(desc.strip())
        raw_text  = "\n".join(content_lines)
        raw_lower = raw_text.lower()

        # ── Location filter (shared) ────────────
        if CURRENT_LOCATIONS and not any(lf in raw_lower for lf in CURRENT_LOCATIONS):
            logger.info(f"[{'PVP' if is_pvp else 'HUNDO'}] Ignored – location filter {CURRENT_LOCATIONS}")
            return

        # ── PVP-specific filters ────────────────
        if is_pvp:
            if CURRENT_PVP_POKEMON and not any(p in raw_lower for p in CURRENT_PVP_POKEMON):
                logger.info(f"[PVP] Ignored – pokemon filter {CURRENT_PVP_POKEMON}")
                return
            if not matches_cp_filters(raw_lower):
                logger.info(f"[PVP] Ignored – CP filter {CURRENT_CPS}")
                return

        # ── Hundo-specific filters ──────────────
        if is_hundo:
            if CURRENT_HUNDO_POKEMON and not any(p in raw_lower for p in CURRENT_HUNDO_POKEMON):
                logger.info(f"[HUNDO] Ignored – pokemon filter {CURRENT_HUNDO_POKEMON}")
                return

        logger.info(f"Found coords URL ({'PVP' if is_pvp else 'HUNDO'}): {coords_url}")

        loop    = asyncio.get_event_loop()
        lat_lng = await loop.run_in_executor(None, scrape_coordinates_from_url, coords_url)

        if not lat_lng:
            logger.error(f"Failed to scrape coordinates from {coords_url}")
            return
        logger.info(f"Scraped coords: {lat_lng}")

        header  = "⚔️ <b>PvP</b> ================================================" if is_pvp \
             else "💯 <b>Hundo</b> ==============================================="

        final_message = build_telegram_message(raw_text, lat_lng, header)

        await loop.run_in_executor(
            None, send_telegram_message,
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, final_message
        )

# ──────────────────────────────────────────────
# Discord Thread Management
# ──────────────────────────────────────────────
def start_discord_session():
    global discord_client, discord_loop
    discord_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(discord_loop)
    discord_client = PogoCoordsClient()
    try:
        logger.info("Connecting Discord Client...")
        discord_loop.run_until_complete(discord_client.start(DISCORD_TOKEN))
    except Exception as e:
        logger.error(f"Discord session stopped: {e}")

def start_discord_thread():
    global discord_thread, discord_start_time
    if discord_thread is None or not discord_thread.is_alive():
        discord_thread = threading.Thread(target=start_discord_session, daemon=True)
        discord_thread.start()
        discord_start_time = time.time()
        return True
    return False

def stop_discord_thread():
    global discord_client, discord_loop, discord_start_time
    if discord_client and discord_loop and not discord_client.is_closed():
        logger.info("Closing Discord Client politely...")
        asyncio.run_coroutine_threadsafe(discord_client.close(), discord_loop)
        discord_start_time = None
        return True
    return False

# ──────────────────────────────────────────────
# Telegram Command Poller
# ──────────────────────────────────────────────
def telegram_command_poller():
    global LISTEN_MODE, CURRENT_LOCATIONS, CURRENT_CPS
    global CURRENT_PVP_POKEMON, CURRENT_HUNDO_POKEMON
    global LAST_UPDATE_ID, discord_start_time, APP_RUNNING

    signal.signal(signal.SIGINT,  handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    while APP_RUNNING:
        try:
            # AutoStop check
            if AUTO_STOP_HOURS > 0 and discord_start_time:
                if time.time() - discord_start_time >= (AUTO_STOP_HOURS * 3600):
                    if stop_discord_thread():
                        LISTEN_MODE = 'off'
                        send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"<b>App status:</b> AUTO-STOPPED (Ran for {AUTO_STOP_HOURS}h)")

            url  = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={LAST_UPDATE_ID + 1}&timeout=30"
            resp = requests.get(url, timeout=40).json()

            if resp.get('ok'):
                for update in resp['result']:
                    LAST_UPDATE_ID = update['update_id']
                    if 'message' not in update or 'text' not in update['message']:
                        continue

                    text    = update['message']['text'].strip()
                    chat_id = str(update['message']['chat']['id'])
                    if chat_id != TELEGRAM_CHAT_ID:
                        continue

                    cmd = text.lower()

                    # ── Mode commands ─────────────────────────
                    if cmd.startswith('/pvp'):
                        LISTEN_MODE = 'pvp'
                        start_discord_thread()
                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            "⚔️ <b>Mode:</b> PVP only (listening to PVP channel)")

                    elif cmd.startswith('/hundo') or cmd.startswith('/hondo'):
                        LISTEN_MODE = 'hundo'
                        start_discord_thread()
                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            "💯 <b>Mode:</b> Hundo only (listening to Hundo channel)")

                    elif cmd.startswith('/both'):
                        LISTEN_MODE = 'both'
                        start_discord_thread()
                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            "⚔️💯 <b>Mode:</b> BOTH channels active")

                    elif cmd.startswith('/stop-app'):
                        if stop_discord_thread():
                            LISTEN_MODE = 'off'
                            send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                                "<b>App status:</b> DISCORD LISTENER STOPPED")
                        else:
                            send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                                "<b>App status:</b> ALREADY STOPPED")

                    # ── Pokédex update ────────────────────────
                    elif cmd.startswith('/update-dex'):
                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            "<b>App status:</b> Downloading Pokédex from PokeAPI...")
                        if load_or_update_pokedex(force_update=True):
                            send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                                f"<b>App status:</b> Updated to {len(VALID_POKEMON)} Pokemon.")
                        else:
                            send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                                "<b>App status:</b> FAILED to update Pokédex.")

                    # ── Reset commands ────────────────────────
                    elif cmd.startswith('/all'):
                        CURRENT_LOCATIONS     = []
                        CURRENT_CPS           = []
                        CURRENT_PVP_POKEMON   = []
                        CURRENT_HUNDO_POKEMON = []
                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            "<b>Filters reset:</b> ALL Locations, CPs &amp; Pokemon cleared")

                    elif cmd.startswith('/cityall'):
                        CURRENT_LOCATIONS = []
                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            "<b>Location Filter:</b> ALL")

                    elif cmd.startswith('/cpall'):
                        CURRENT_CPS = []
                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            "<b>CP Filter (PVP):</b> ALL")

                    elif cmd.startswith('/pokeall'):
                        CURRENT_PVP_POKEMON   = []
                        CURRENT_HUNDO_POKEMON = []
                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            "<b>Pokemon Filter:</b> ALL (PVP &amp; Hundo cleared)")

                    # ── Generic filter parser ─────────────────
                    elif cmd.startswith('/'):
                        raw_tokens = text[1:].replace('-', ' ')
                        tokens     = [t.strip().lower() for t in raw_tokens.split('/') if t.strip()]

                        # Hundo pokemon tokens start with "hdo "
                        new_hundo_pokes = [t[4:].strip() for t in tokens
                                           if t.startswith('hdo ') and t[4:].strip() in VALID_POKEMON]
                        # Remaining token classification
                        remaining = [t for t in tokens if not t.startswith('hdo ')]
                        new_cps           = [t for t in remaining if t.startswith('cp')]
                        new_pvp_pokes     = [t for t in remaining if t in VALID_POKEMON]
                        new_locs          = [t for t in remaining
                                             if not t.startswith('cp') and t not in VALID_POKEMON]

                        if new_locs:          CURRENT_LOCATIONS     = new_locs
                        if new_cps:           CURRENT_CPS           = new_cps
                        if new_pvp_pokes:     CURRENT_PVP_POKEMON   = new_pvp_pokes
                        if new_hundo_pokes:   CURRENT_HUNDO_POKEMON = new_hundo_pokes

                        loc_d   = ", ".join(f.title() for f in CURRENT_LOCATIONS)     or "ALL"
                        cp_d    = ", ".join(f.upper() for f in CURRENT_CPS)           or "ALL"
                        pvp_d   = ", ".join(f.title() for f in CURRENT_PVP_POKEMON)   or "ALL"
                        hundo_d = ", ".join(f.title() for f in CURRENT_HUNDO_POKEMON) or "ALL"

                        send_telegram_message(TELEGRAM_BOT_TOKEN, chat_id,
                            f"<b>Location Filter:</b> {loc_d}\n"
                            f"<b>CP Filter (PVP):</b> {cp_d}\n"
                            f"<b>PVP Pokemon:</b> {pvp_d}\n"
                            f"<b>Hundo Pokemon:</b> {hundo_d}"
                        )

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Poller error: {e}")
            time.sleep(2)
        time.sleep(1)

    logger.info("Main polling loop halted. Commencing safe shutdown.")
    stop_discord_thread()
    time.sleep(1.5)
    logger.info("Shutdown complete. Goodbye.")

# ──────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_DISCORD_USER_TOKEN_HERE":
        logger.error("Please set a valid DISCORD_TOKEN in .env file.")
        print("IMPORTANT: Check the .env file and set your Discord user token.")
    else:
        logger.info("Initializing in STANDBY mode (mode=off).")
        logger.info("Send /pvp, /hundo, or /both in Telegram to start listening.")
        telegram_command_poller()
