import requests
import logging

logger = logging.getLogger(__name__)
TELEGRAM_API_URL = "https://api.telegram.org/bot"

def send_telegram_message(bot_token: str, chat_id: str, text: str):
    """
    Sends an HTML formatted message to Telegram.
    """
    url = f"{TELEGRAM_API_URL}{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Message sent to Telegram successfully")
        return True
    except Exception as e:
        logger.error(f"Error sending message to Telegram: {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            logger.error(f"Response details: {response.text}")
        return False
