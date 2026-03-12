"""
Heise News Scraper
==================
Collects article links from heise.de and extracts the main article body.

Steps:
    1. Fetch article links from the heise.de news archive.
    2. Fetch each article page and extract the main content HTML.

DEPENDENCIES:
    pip install requests beautifulsoup4 html2text

USAGE:
    from heise_scraper import fetch_article_links, fetch_article_html

    links = fetch_article_links()
    for url in links[:3]:
        html = fetch_article_html(url)
        print(html[:500])
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

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
    "article.article-content",
    "div.article-content",
    "div[itemprop='articleBody']",
    "div.article__body",
    "main article",
    "article",
]


# ──────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────

@dataclass
class ArticleLink:
    """Represents a single article link from the heise.de archive."""
    title: str
    url: str
    time: Optional[str] = None        # e.g. "07:30", parsed from the listing page
    date: Optional[str] = None
    is_teaser: bool = False           # True for heise+ featured articles (a-theme--ho)


@dataclass
class ArticleContent:
    """Represents the extracted content of a heise.de article."""
    url: str
    title: str
    html: str
    metadata: dict = field(default_factory=dict)


# ──────────────────────────────────────────────
# Step 1 – Collect article links
# ──────────────────────────────────────────────

def fetch_article_links(
    archive_url: str = HEISE_ARCHIVE_URL,
    max_articles: Optional[int] = None,
    request_delay: float = 0.5,
) -> list[ArticleLink]:
    """
    Fetches article links from the heise.de Atom RSS feed.

    Using the RSS feed instead of scraping the HTML listing avoids problems
    with JavaScript-rendered placeholders (href="${url}") that appear in the
    HTML before client-side templates are resolved.

    The feed contains the most recent articles with canonical URLs,
    titles, and publication timestamps.

    Args:
        archive_url:    Ignored – kept for API compatibility. The RSS feed URL
                        is always used (HEISE_RSS_URL constant).
        max_articles:   Maximum number of links to return. None = all in feed.
        request_delay:  Seconds to wait after the request (politeness).

    Returns:
        List of ArticleLink objects in feed order (newest first).

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
    response = requests.get(HEISE_RSS_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    time.sleep(request_delay)

    root = ET.fromstring(response.content)
    links: list[ArticleLink] = []

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

        links.append(ArticleLink(title=title, url=url, time=pub_time, is_teaser=False))

        if max_articles and len(links) >= max_articles:
            break

    logger.info(f"Found {len(links)} article links from RSS feed.")
    return links


def fetch_article_links_archive(
    archive_url: str = HEISE_ARCHIVE_URL,
    max_articles: Optional[int] = None,
    request_delay: float = 0.5,
) -> list[ArticleLink]:
    """
    Fetches article links by scraping the heise.de HTML archive page.

    This is an alternative to fetch_article_links() that covers more articles
    since the archive page lists several days of news. The downside is that
    some articles are rendered via JavaScript templates (href="${url}") and
    will be missing from the results – these are typically the featured
    teaser articles at the top of the page.

    Uses <article data-cid="..."> elements as the anchor for each article,
    which avoids URL-suffix ambiguity (.html / .html.teaser / .teaser).

    Args:
        archive_url:    URL of the archive page to scrape. Defaults to
                        HEISE_ARCHIVE_URL.
        max_articles:   Maximum number of links to return. None = all found.
        request_delay:  Seconds to wait after the request (politeness).

    Returns:
        List of ArticleLink objects in page order (newest first).
        Articles with unresolved JS placeholders are silently skipped.

    Raises:
        requests.HTTPError: If the server returns a non-2xx status.
        requests.Timeout:   If the request times out.
    """
    logger.info(f"Fetching article links from archive page: {archive_url}")
    response = requests.get(archive_url, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    time.sleep(request_delay)

    soup = BeautifulSoup(response.text, "html.parser")
    links: list[ArticleLink] = []

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

        article_classes = " ".join(article_tag.get("class", []))
        is_teaser = "a-theme--ho" in article_classes

        time_tag = article_tag.find(class_=re.compile(r"\ba-datetime__time\b"))
        pub_time = time_tag.get_text(strip=True) if time_tag else None

        title = anchor.get("title", "").strip() or anchor.get_text(strip=True)
        links.append(ArticleLink(title=title, url=canonical, time=pub_time, is_teaser=is_teaser))

        if max_articles and len(links) >= max_articles:
            break

    logger.info(f"Found {len(links)} article links from archive page.")
    return links

# ──────────────────────────────────────────────
# Step 2 – Extract main article HTML
# ──────────────────────────────────────────────

def _extract_main_content(soup: BeautifulSoup) -> Optional[BeautifulSoup]:
    """
    Locates the main article body element within a heise.de page.

    Tries a prioritised list of CSS selectors to find the content container.
    Falls back to <main> if no selector matches.

    Args:
        soup: Parsed BeautifulSoup object of the full page.

    Returns:
        BeautifulSoup Tag of the content element, or None if not found.
    """
    for selector in ARTICLE_SELECTORS:
        element = soup.select_one(selector)
        if element and element.get_text(strip=True):
            logger.debug(f"Content found with selector: '{selector}'")
            return element

    # Last resort: <main> tag
    main = soup.find("main")
    if main and main.get_text(strip=True):
        logger.debug("Content found via <main> fallback.")
        return main

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
    for tag in content_tag.find_all(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    # Common CSS class/id fragments that indicate non-editorial content
    noise_patterns = [
        "author", "byline", "ad-", "advertisement", "social", "share",
        "comment", "newsletter", "related", "teaser", "sidebar", "breadcrumb",
        "navigation", "nav", "footer", "header", "cookie", "paywall",
        "subscription", "leserbrief", "weiterlesen",
    ]

    # Collect all candidates first to avoid mutating the tree during iteration.
    # Re-check tag.parent before each decompose: if a parent was already removed,
    # its children are detached and accessing their attributes raises AttributeError.
    candidates = list(content_tag.find_all(True))
    for tag in candidates:
        if tag.parent is None:
            # Already removed as child of a previously decomposed parent
            continue
        tag_id = " ".join([tag.get("id", ""), *tag.get("class", [])]).lower()
        if any(pattern in tag_id for pattern in noise_patterns):
            tag.decompose()


def fetch_article_html(
    url: str,
    request_delay: float = 1.0,
    timeout: int = 15,
) -> Optional[ArticleContent]:
    """
    Fetches a single heise.de article and extracts its main content as HTML.

    Performs the HTTP request, parses the page, and isolates the article
    body while removing ads, author bios, and other clutter.

    Args:
        url:            Full URL of the heise.de article.
        request_delay:  Seconds to wait after the request (politeness).
        timeout:        HTTP request timeout in seconds.

    Returns:
        ArticleContent with the main body HTML, or None if extraction fails.

    Raises:
        requests.HTTPError: If the server returns a non-2xx status.
        requests.Timeout:   If the request times out.
    """
    logger.info(f"Fetching article: {url}")
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    time.sleep(request_delay)

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract page title
    page_title = ""
    title_tag = soup.find("h1") or soup.find("title")
    if title_tag:
        page_title = title_tag.get_text(strip=True)

    content_tag = _extract_main_content(soup)
    if not content_tag:
        logger.warning(f"Could not extract main content from: {url}")
        return None

    _remove_clutter(content_tag)

    # Collect basic metadata
    metadata: dict = {}
    time_tag = soup.find("time")
    if time_tag:
        metadata["published"] = time_tag.get("datetime", time_tag.get_text(strip=True))

    return ArticleContent(
        url=url,
        title=page_title,
        html=str(content_tag),
        metadata=metadata,
    )


# ──────────────────────────────────────────────
# Batch helper
# ──────────────────────────────────────────────

def scrape_latest_articles(
    max_articles: int = 10,
    request_delay: float = 1.0,
    archive_url: str = HEISE_ARCHIVE_URL,
) -> list[ArticleContent]:
    """
    Convenience function: fetches links and scrapes each article in one call.

    Args:
        max_articles:   Maximum number of articles to scrape.
        request_delay:  Delay in seconds between requests.
        archive_url:    Archive page to collect links from.

    Returns:
        List of ArticleContent objects (failed extractions are skipped).
    """
    links = fetch_article_links(
        archive_url=archive_url,
        max_articles=max_articles,
        request_delay=request_delay,
    )

    articles: list[ArticleContent] = []
    for link in links:
        try:
            article = fetch_article_html(link.url, request_delay=request_delay)
            if article:
                articles.append(article)
        except Exception as exc:
            logger.warning(f"Skipping {link.url}: {exc}")

    logger.info(f"Successfully scraped {len(articles)}/{len(links)} articles.")
    return articles


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import json
    from html_to_markdown import html_to_markdown

    # fetch all articles
    if True:
        article_links = fetch_article_links()
        #article_links = fetch_article_links_archive()
        with open("temp/article_links.txt", "w", encoding="utf-8") as f:
            for link in article_links:
                print(link)
                f.write(f"{link.time} | {link.is_teaser} | {link.title} | {link.url}\n")
        

    # fetch n latest articles
    if False:
        articles = scrape_latest_articles(max_articles=3, request_delay=1.0)

        for i, article in enumerate(articles, 1):
            md = html_to_markdown(article.html, source_type="web")
            print(f"\n{'='*60}")
            print(f"[{i}] {article.title}")
            print(f"URL: {article.url}")
            if article.metadata:
                print(f"Meta: {json.dumps(article.metadata)}")
            print("-" * 60)
            print(md[:800])
            print("...")