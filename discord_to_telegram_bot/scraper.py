import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

def scrape_coordinates_from_url(url: str) -> str:
    """
    Scrapes coordinates from the pokedex100 coords link.
    Requires POKEDEX100_COOKIE in the `.env` if the site enforces Discord Login.
    """
    load_dotenv()
    session_cookie = os.getenv('POKEDEX100_COOKIE', '')
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    cookies = {}
    if session_cookie:
        cookies['sessionid'] = session_cookie

    try:
        response = requests.get(url, headers=headers, cookies=cookies, timeout=10)
        response.raise_for_status()
        
        # Check if we were redirected to a login page
        if "/accounts/discord/login/" in response.url or "/accounts/discord/login/" in response.text:
            logger.error("Authentication required! The bot hit the Discord Login page.")
            logger.error("Please log in to Pokedex100 on your browser, copy your 'sessionid' cookie, and set it as POKEDEX100_COOKIE in your .env file.")
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for the input with id="community-coord"
        coord_input = soup.find('input', id='community-coord')
        if coord_input and coord_input.has_attr('value'):
            return coord_input['value']
        
        logger.warning("Could not find the coordinates input box on the page. The link might be expired.")
        return None
    except Exception as e:
        logger.error(f"Error scraping coordinates from {url}: {e}")
        return None

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    test_url = "https://coord.pokedex100.com/6/u2JeOc7XPGhDLn"
    print(f"Scraped coords: {scrape_coordinates_from_url(test_url)}")
