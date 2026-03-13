"""
Heise Login
===========
Provides a requests.Session authenticated with a heise.de account,
using Playwright to handle the JavaScript-based login flow.
 
heise.de's login form uses AJAX (data-ajax-enabled) and cannot be
submitted via a plain HTTP POST. Playwright drives a real browser,
executes the JavaScript login, and extracts the resulting cookies
into a requests.Session.
 
Credentials are read from environment variables – never hard-code them:
 
    export HEISE_USERNAME="your@email.de"
    export HEISE_PASSWORD="yourpassword"
 
Or place them in a .env file and load with python-dotenv.
 
DEPENDENCIES:
    pip install playwright requests python-dotenv
    playwright install chromium
"""
 
import logging
import os
 
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
 
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv()


HEISE_LOGIN_URL = "https://www.heise.de/sso/login/"
 
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}
 
 
def create_session(
    username: str | None = None,
    password: str | None = None,
    headless: bool = True,
) -> requests.Session:
    """
    Creates and returns an authenticated requests.Session for heise.de.
 
    Uses Playwright to drive a headless Chromium browser through the
    JavaScript-based login form. After successful login the browser cookies
    are transferred into a requests.Session for use in subsequent scraping.
 
    If username and password are not passed as arguments, they are read from
    the environment variables HEISE_USERNAME and HEISE_PASSWORD.
 
    Args:
        username: heise.de account email. Defaults to HEISE_USERNAME env var.
        password: heise.de account password. Defaults to HEISE_PASSWORD env var.
        headless: Run browser without a visible window. Set False for debugging.
 
    Returns:
        Authenticated requests.Session with heise.de cookies set.
 
    Raises:
        ValueError:            If credentials are missing.
        RuntimeError:          If login fails or times out.
        playwright.errors.*:   If the browser cannot be launched.
    """
    username = username or os.environ.get("HEISE_USERNAME")
    password = password or os.environ.get("HEISE_PASSWORD")
 
    if not username or not password:
        raise ValueError(
            "Heise credentials not found. Set HEISE_USERNAME and "
            "HEISE_PASSWORD environment variables."
        )
 
    logger.info(f"Logging in to heise.de as {username} (headless={headless}) ...")
 
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            user_agent=DEFAULT_HEADERS["User-Agent"],
            locale="de-DE",
        )
        page = context.new_page()
 
        # Navigate to login page
        page.goto(HEISE_LOGIN_URL, wait_until="networkidle", timeout=30_000)
 
        # Fill and submit the login form
        page.fill("input[name='username']", username)
        page.fill("input[name='password']", password)
 
        try:
            # Click submit and wait for navigation away from the login page
            with page.expect_navigation(wait_until="networkidle", timeout=15_000):
                page.click("button[name='rm_login']")
        except PlaywrightTimeoutError:
            pass  # some redirects don't trigger a full navigation event
 
        final_url = page.url
        if "/sso/login" in final_url:
            browser.close()
            raise RuntimeError(
                "Login failed – still on login page after submit. "
                "Check your HEISE_USERNAME and HEISE_PASSWORD."
            )
 
        # Extract cookies from the browser context into a requests.Session
        browser_cookies = context.cookies()
        browser.close()
 
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    for cookie in browser_cookies:
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain", ""),
            path=cookie.get("path", "/"),
        )
 
    logger.info(f"Login successful. Cookies: {[c['name'] for c in browser_cookies]}")
    return session



if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("debug.log"),
            logging.StreamHandler()
        ],
    )
    
    create_session()