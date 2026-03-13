"""
Heise News Scraper
==================
Collects article links from heise.de and extracts the main article body.

The central data structure is the Article dataclass, which is populated
incrementally as it moves through the pipeline:

    Stage 1 – fetch_article_links() / fetch_article_links_archive()
              fills: title, url, time

    Stage 2 – fetch_article_html()
              fills: html, metadata

    Stage 3 – html_to_markdown() (external, in html_to_markdown.py)
              fills: markdown

    Stage 4 – query_ollama() (external, in llm_ollama.py)
              fills: summary, llm_metrics

At any point, dataclasses.asdict(article) produces a JSON-serialisable dict
with all fields populated so far.

DEPENDENCIES:
    pip install requests beautifulsoup4 html2text

USAGE:
    from heise_scraper import fetch_article_links, fetch_article_html

    articles = fetch_article_links()
    for article in articles[:3]:
        fetch_article_html(article)
        print(article.title, article.html[:200])
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

from heise_auth import create_session
session = None
try:
    session = create_session()
    logger.info("Authentication to heise successful")
except Exception as e:
    logger.warning(f"FAILED Authentication to heise: {e}")

HEISE_ARCHIVE_URL = "https://www.heise.de/newsticker/archiv/"
HEISE_BASE_URL    = "https://www.heise.de"
HEISE_RSS_URL     = "https://www.heise.de/newsticker/heise-atom.xml"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

# CSS selectors for the main article body on heise.de
# Listed in priority order – first match wins.
ARTICLE_SELECTORS = [
    ".article-content",
    ".article-layout__content",
    #"article.article-content",
    #"div.article-content",
    #"div[itemprop='articleBody']",
    #"div.article__body",
    #"main article",
    #"article",
]


# ──────────────────────────────────────────────
# Step 1 – Collect article links
# ──────────────────────────────────────────────
 
def fetch_article_links(
    max_articles: Optional[int] = None,
    request_delay: float = 0.5,
) -> list[dict]:
    """
    Fetches article links from the heise.de Atom RSS feed.
 
    Using the RSS feed instead of scraping the HTML listing avoids problems
    with JavaScript-rendered placeholders (href="${url}") that appear in the
    HTML before client-side templates are resolved.
 
    Args:
        max_articles:   Maximum number of links to return. None = all in feed.
        request_delay:  Seconds to wait after the request (politeness).
 
    Returns:
        List of dicts in feed order (newest first), each with keys:
            title (str), url (str), time (str|None).
 
    Raises:
        requests.HTTPError: If the server returns a non-2xx status.
        requests.Timeout:   If the request times out.
    """
    import xml.etree.ElementTree as ET
 
    NS = {
        "atom": "http://www.w3.org/2005/Atom",
        "dc":   "http://purl.org/dc/elements/1.1/",
    }
 
    logger.info(f"Fetching article links from RSS feed: {HEISE_RSS_URL}")
    requester = session or requests
    response = requester.get(HEISE_RSS_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    time.sleep(request_delay)
 
    root = ET.fromstring(response.content)
    articles: list[dict] = []
 
    for entry in root.findall("atom:entry", NS):
        title = entry.findtext("atom:title", "", NS).strip()
 
        url = ""
        for link_el in entry.findall("atom:link", NS):
            if link_el.get("rel", "alternate") == "alternate":
                url = link_el.get("href", "").strip()
                break
        if not url or not url.startswith(HEISE_BASE_URL):
            continue
 
        published = entry.findtext("atom:published", "", NS)
        pub_time  = published[11:16] if len(published) >= 16 else None
 
        articles.append({"title": title, "url": url, "time": pub_time})
 
        if max_articles and len(articles) >= max_articles:
            break
 
    logger.info(f"Found {len(articles)} article links from RSS feed.")
    return articles
 
 
def fetch_article_links_archive(
    max_articles: Optional[int] = None,
    request_delay: float = 0.5,
) -> list[dict]:
    """
    Fetches article links by scraping the heise.de HTML archive page.
 
    Alternative to fetch_article_links() that covers more articles since the
    archive page lists several days of news. Articles rendered via JavaScript
    templates (href="${url}") are silently skipped.
 
    Args:
        max_articles:   Maximum number of links to return. None = all found.
        request_delay:  Seconds to wait after the request (politeness).
 
    Returns:
        List of dicts in page order (newest first), each with keys:
            title (str), url (str), time (str|None).
 
    Raises:
        requests.HTTPError: If the server returns a non-2xx status.
        requests.Timeout:   If the request times out.
    """
    logger.info(f"Fetching article links from archive page: {HEISE_ARCHIVE_URL}")
    requester = session or requests
    response = requester.get(HEISE_RSS_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    time.sleep(request_delay)
 
    soup = BeautifulSoup(response.text, "html.parser")
    articles: list[dict] = []
 
    seen: set[str] = set()
    for article_tag in soup.find_all("article", attrs={"data-cid": True}):
        cid = article_tag["data-cid"].strip()
        anchor = article_tag.find("a", href=True)
        if not anchor:
            continue
 
        href = anchor["href"].split("?")[0].strip()
 
        # Skip unresolved JS template placeholders
        if "${" in href:
            continue
 
        if href.startswith("/"):
            href = HEISE_BASE_URL + href
        if not href.startswith(HEISE_BASE_URL):
            continue
 
        # Normalise URL: truncate at the CID and force .html suffix
        canonical = re.sub(r"(-" + re.escape(cid) + r").*$", r"\1.html", href)
 
        if canonical in seen:
            continue
        seen.add(canonical)
 
        time_tag = article_tag.find(class_=re.compile(r"\ba-datetime__time\b"))
        pub_time = time_tag.get_text(strip=True) if time_tag else None
 
        title = anchor.get("title", "").strip() or anchor.get_text(strip=True)
        articles.append({"title": title, "url": canonical, "time": pub_time})
 
        if max_articles and len(articles) >= max_articles:
            break
 
    logger.info(f"Found {len(articles)} article links from archive page.")
    return articles
 
 
# ──────────────────────────────────────────────
# Step 2 – Extract main article HTML
# ──────────────────────────────────────────────
 
def _extract_main_content(soup: BeautifulSoup, url: str) -> Optional[BeautifulSoup]:
    """
    Locates the main article body element within a heise.de page.
 
    Tries each selector in ARTICLE_SELECTORS in order. If none match, falls
    back to <main> and logs a warning. If even <main> is absent, logs another
    warning and returns None.
 
    Args:
        soup: Parsed BeautifulSoup object of the full page.
        url:  Article URL, used in warning messages.
 
    Returns:
        BeautifulSoup Tag of the content element, or None if not found.
    """
    for selector in ARTICLE_SELECTORS:
        element = soup.select_one(selector)
        #element = soup.find("div", class_="article-content")
        if element and element.get_text(strip=True):
            logger.debug(f"Content found with selector '{selector}': {url}")
            return element
 
    # None of the known selectors matched – fall back to <main>
    logger.warning(
        f"No selector matched {ARTICLE_SELECTORS} for {url}"# – falling back to <main>"
    )

    #main = soup.find("main")
    #if main and main.get_text(strip=True):
    #    return main
 
    #logger.warning(f"No content found at all for {url} – skipping.")
    return None
 
 
def _remove_clutter(content_tag: BeautifulSoup) -> None:
    """
    Removes non-editorial elements from an extracted content tag in-place.
 
    Strips author bios, social share buttons, ad containers, comment sections,
    newsletter teasers, and other peripheral elements that are not part of
    the main article text.
 
    Important: candidates are collected into a list before any decompose() call
    to avoid mutating the DOM while iterating over it (which causes NoneType
    errors on already-removed child nodes).
 
    Args:
        content_tag: BeautifulSoup Tag of the content container (mutated in-place).
    """
    # Tag names that are never article text – collect first, then remove
    for tag in content_tag.find_all(["script", "style", "noscript", "iframe", "footer"]):
        tag.decompose()
 
    # CSS class/id fragments that indicate non-editorial content.
    # Each pattern is matched as a whole word (\b boundaries) so that
    # e.g. "header" does not accidentally remove "article-header__title",
    # and "nav" does not remove "navbar" used for legitimate article elements.
    # Patterns ending in "-" are kept as prefix matches (e.g. "ad-banner").
    _noise_parts = [
        "author", "byline", "ad-", "advertisement", "social", "share",
        "comment", "newsletter", "related", "teaser", "sidebar", "breadcrumb",
        "navigation", "nav", "footer", "header", "cookie", "paywall",
        "subscription", "leserbrief", "weiterlesen",
    ]
    noise_re = re.compile("|".join(
        p if p.endswith("-") else r"\b" + re.escape(p) + r"\b"
        for p in _noise_parts
    ))
 
    # Collect all candidates first to avoid mutating the tree during iteration.
    # Re-check tag.parent before each decompose: if a parent was already removed,
    # its children are detached and accessing their attributes raises AttributeError.
    candidates = list(content_tag.find_all(True))
    for tag in candidates:
        if tag.parent is None:
            # Already removed as child of a previously decomposed parent
            continue
        tag_id = " ".join([tag.get("id", ""), *tag.get("class", [])]).lower()
        if noise_re.search(tag_id):
            tag.decompose()
 
 
def strip_trailing_noise(markdown: str) -> str:
    """
    Removes everything from the first occurrence of a known noise heading
    onwards.
 
    Heise.de articles often end with consent widgets, price comparison boxes,
    and author footers that survive HTML cleaning because they are hidden via
    CSS rather than marked up with identifiable classes. Cutting at a known
    heading is simpler and more reliable than trying to remove them in the
    HTML stage.
 
    Call this after html_to_markdown() has produced the markdown string:
 
        article["markdown"] = strip_trailing_noise(
            html_to_markdown(article["html"], source_type="web")
        )
 
    Args:
        markdown: Markdown string to clean.
 
    Returns:
        Markdown string with trailing noise removed and trailing whitespace
        stripped.
    """
    noise_headings = [
        "## Empfohlener redaktioneller Inhalt",
        "### Lesen Sie auch",
        "### E-Mail-Adresse",
    ]
    # Find the earliest occurrence across all patterns and cut there.
    # This handles cases where multiple noise headings appear in one article.
    cut = min(
        (markdown.find(h) for h in noise_headings if markdown.find(h) != -1),
        default=-1,
    )
    if cut != -1:
        markdown = markdown[:cut].rstrip()
    return markdown
 
 
def fetch_article_html(
    article: dict,
    request_delay: float = 1.0,
    timeout: int = 15,
) -> bool:
    """
    Fetches a heise.de article page and adds stage 2 keys to the given article
    dict in-place (html, metadata).
 
    The title key is updated from the page's <h1> if present, as it is more
    precise than the feed title.
 
    Args:
        article:        Article dict to enrich (mutated in-place).
        request_delay:  Seconds to wait after the request (politeness).
        timeout:        HTTP request timeout in seconds.
 
    Returns:
        True if content was extracted successfully, False otherwise.
 
    Raises:
        requests.HTTPError: If the server returns a non-2xx status.
        requests.Timeout:   If the request times out.
    """
    url = article["url"]
    logger.info(f"Fetching article: {url}")
    requester = session or requests
    response = requester.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    time.sleep(request_delay)
 
    soup = BeautifulSoup(response.text, "html.parser")
 
    # Update title from page <h1> (more precise than feed title)
    title_tag = soup.find("h1") or soup.find("title")
    if title_tag:
        article["title"] = title_tag.get_text(strip=True)
 
    content_tag = _extract_main_content(soup, url)
    if not content_tag:
        return False
 
    _remove_clutter(content_tag)
    article["html"] = str(content_tag)
 
    # Collect basic metadata
    metadata: dict = {}
    time_tag = soup.find("time")
    if time_tag:
        metadata["published"] = time_tag.get(
            "datetime", time_tag.get_text(strip=True)
        )
    article["metadata"] = metadata
 
    return True
 
 
# ──────────────────────────────────────────────
# Batch helper
# ──────────────────────────────────────────────
 
def scrape_latest_articles(
    max_articles: int = 10,
    request_delay: float = 1.0,
) -> list[dict]:
    """
    Convenience function: fetches links and populates each article's HTML
    content in one call.
 
    Args:
        max_articles:   Maximum number of articles to scrape.
        request_delay:  Delay in seconds between requests.
 
    Returns:
        List of article dicts with stage 1 and stage 2 keys populated.
        Articles where content extraction failed are skipped.
    """
    articles = fetch_article_links(
        max_articles=max_articles,
        request_delay=request_delay,
    )
 
    result: list[dict] = []
    for article in articles:
        try:
            success = fetch_article_html(article, request_delay=request_delay)
            if success:
                result.append(article)
        except Exception as exc:
            logger.warning(f"Skipping {article['url']}: {exc}")
 
    logger.info(f"Successfully scraped {len(result)}/{len(articles)} articles.")
    return result
 
 
# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
 
if __name__ == "__main__":
    import json
    from html_to_markdown import html_to_markdown
    from datetime import datetime
    import locale
    # German weekday names
    locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler("debug.log"),
            logging.StreamHandler()
        ],
    )
 
    # fetch all article links only
    if False:
        logger.info("Fetch all links from heise.de")
        articles = fetch_article_links()
        with open("temp/article_links.json", "w", encoding="utf-8") as f:
            json.dump(articles, f, ensure_ascii=False, indent=2)
        with open("temp/article_links.txt", "w", encoding="utf-8") as f:
            for a in articles:
                f.write(f"{a['time']} | {a['title']} | {a['url']}\n")
 
    # fetch n latest articles and convert to markdown
    if True:
        logger.info("Fetch the latest n articles and process the html to markdown")
        articles = scrape_latest_articles(max_articles=20, request_delay=1.0)
 
        for article in articles:
            article["markdown"] = strip_trailing_noise(
                html_to_markdown(article["html"], source_type="web")
            )
 
        with open("temp/articles.json", "w", encoding="utf-8") as f:
            data = [{k: v for k, v in a.items() if k != "html"} for a in articles]
            json.dump(data, f, ensure_ascii=False, indent=2)
        with open("temp/articles.txt", "w", encoding="utf-8") as f:
            for a in articles:
                dt = datetime.fromisoformat(a['metadata']["published"])
                f.write(f"{dt.strftime("%A %d.%m.%Y")} | {a['title']} | {a['url']}\n")
                f.write(a["markdown"])
                f.write("\n" + "-"*80 + "\n\n")