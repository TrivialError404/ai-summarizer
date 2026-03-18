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
from datetime import date, timedelta, datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

HEISE_ARCHIVE_URL = "https://www.heise.de/newsticker/archiv/"
HEISE_BASE_URL    = "https://www.heise.de"


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
]

# Lazy session cache – None means not yet authenticated
_session = None


def get_heise_session():
    """
    Returns an authenticated requests.Session for heise.de.

    The session is created on the first call and reused for all subsequent
    calls (lazy singleton). Safe to call multiple times – authentication
    happens exactly once.

    Returns:
        An authenticated requests.Session.

    Raises:
        Exception: If authentication fails.
    """
    global _session
    if _session is None:
        from sources.heise.heise_auth import create_session
        _session = create_session()
        logger.info("Authentication to heise successful")
    return _session


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
            title      (str)       -- article headline
            url        (str)       -- canonical article URL (tracking params stripped)
            article_id (str|None)  -- numeric heise article ID, e.g. "11210569"
            date       (str|None)  -- publication date as "YYYY-MM-DD"
            time       (str|None)  -- publication time as "HH:MM"
            updated    (str|None)  -- last-modified timestamp (ISO 8601)
            summary    (str|None)  -- short teaser text
            author     (str|None)  -- author name
            image_url  (str|None)  -- teaser image URL extracted from content HTML
 
    Raises:
        requests.HTTPError: If the server returns a non-2xx status.
        requests.Timeout:   If the request times out.
    """
    import re as _re
    import xml.etree.ElementTree as ET
    
    HEISE_RSS_URL = "https://www.heise.de/newsticker/heise-atom.xml"
    NS = {
        "atom": "http://www.w3.org/2005/Atom",
        #"dc":   "http://purl.org/dc/elements/1.1/",
    }
 
    logger.info(f"Fetching article links from RSS feed: {HEISE_RSS_URL}")
    response = requests.get(HEISE_RSS_URL, headers=DEFAULT_HEADERS, timeout=15)
    response.raise_for_status()
    time.sleep(request_delay)
 
    root = ET.fromstring(response.content)
    articles: list[dict] = []
 
    for entry in root.findall("atom:entry", NS):
        """
         <entry>
            <title type="html"><![CDATA[heise-Angebot: iX-Workshop KRITIS: Zusätzliche Prüfverfahrenskompetenz für § 8a BSIG]]></title>
            <id>http://heise.de/-11194669</id>
            <updated>2026-03-11T10:00:00+01:00</updated>
            <published>2026-03-11T10:00:00+01:00</published>
            <link href="https://www.heise.de/news/iX-Workshop-KRITIS-Zusaetzliche-Pruefverfahrenskompetenz-fuer-8a-BSIG-11194669.html?wt_mc=rss.red.ho.ho.atom.beitrag.beitrag"/>
            <author>
                <name>Ilona Krause</name>
            </author>
            <summary type="html"><![CDATA[Erlangen Sie spezielle Prüfverfahrenskompetenz für § 8a BSIG; inklusive Abschlussprüfung und Zertifizierung.]]></summary>
            <content type="html"><![CDATA[<p><a href="https://www.heise.de/news/iX-Workshop-KRITIS-Zusaetzliche-Pruefverfahrenskompetenz-fuer-8a-BSIG-11194669.html?wt_mc=rss.red.ho.ho.atom.beitrag.beitrag"><img src="https://www.heise.de/scale/geometry/450/q80//imgs/18/5/0/3/7/0/1/5/KRITIS-Pruefungskompetenz-Ticker-Header-16-9-72087be63b7bf7b2.jpeg" class="webfeedsFeaturedVisual" alt="" /></a></p><p>Erlangen Sie spezielle Prüfverfahrenskompetenz für § 8a BSIG; inklusive Abschlussprüfung und Zertifizierung.</p>]]></content>
        </entry>
        """
        # Title
        title = entry.findtext("atom:title", "", NS).strip()
        # ID
        id = entry.findtext("atom:id", "", NS)
        id_match = _re.search(r"(\d{6,})", id) # <id>http://heise.de/-11210569</id> -> "11210569"
        id_extracted = id_match.group(1) if id_match else None
        # Dates
        updated = entry.findtext("atom:updated", "", NS)
        published = entry.findtext("atom:published", "", NS)
        published_date  = published[:10]   if len(published) >= 10 else None
        published_time  = published[11:16] if len(published) >= 16 else None
        # Link
        link = entry.find("atom:link", NS).attrib["href"]
        url = link.split("?")[0].strip()
        # Author
        author = entry.findtext("atom:author/atom:name", "", NS)
        # Summary
        summary = entry.findtext("atom:summary", "", NS).strip()
        # Metadata html
        content = entry.findtext("atom:content", "", NS)
        img_match = _re.search(r'<img[^>]+src="([^"]+)"', content)
        image_url = img_match.group(1) if img_match else None
 
        articles.append({
            "title":            title,
            "id":               id,
            "id_extracted":     id_extracted,
            "updated":          updated,
            "published":        published,
            "published_date":   published_date,
            "published_time":   published_time,
            "link":             link,
            "url":              url,
            "author":           author,
            "summary":          summary,
            "content":          content,
            "image_url":        image_url,
        })
 
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
    requester = requests
    response = requester.get(HEISE_ARCHIVE_URL, headers=DEFAULT_HEADERS, timeout=15)
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
 
def _html_extract_main_content(soup: BeautifulSoup, url: str) -> Optional[BeautifulSoup]:
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
 
 
def _html_remove_clutter(content_tag: BeautifulSoup) -> None:
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


def fetch_article_html(url: str, request_delay: float = 1.0, timeout: int = 15) -> bool:
    """
    Fetches a heise.de article page and adds stage 2 keys to the given article
    dict in-place (html, metadata).
 
    The title key is updated from the page's <h1> if present, as it is more
    precise than the feed title.
 
    Args:
        url:            URL to the article
        request_delay:  Seconds to wait after the request (politeness).
        timeout:        HTTP request timeout in seconds.
 
    Returns:
        True if content was extracted successfully, False otherwise.
 
    Raises:
        requests.HTTPError: If the server returns a non-2xx status.
        requests.Timeout:   If the request times out.
    """
    logger.info(f"Fetching article: {url}")
    requester = get_heise_session()
    response = requester.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    time.sleep(request_delay)
 
    soup = BeautifulSoup(response.text, "html.parser")
    
    # Extract content (by class names)
    content_tag = _html_extract_main_content(soup, url)
    if not content_tag:
        return False
 
    _html_remove_clutter(content_tag)
    return str(content_tag)


# ──────────────────────────────────────────────
# Special Markdown reomoval
# ──────────────────────────────────────────────
def md_postprocess_remove_section_noise(markdown: str) -> str:
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
        "### Hören Sie auch",
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

 
# ──────────────────────────────────────────────
# Batch helper
# ──────────────────────────────────────────────
 
def scrape_articles_by_filter(
    max_articles: int | None = 10,
    days_back: int = 0,
    exact_day: bool = False,
) -> list[dict]:
    """
    Fetches article links and populates each article's HTML content.
 
    Articles are filtered by date before fetching HTML, so only matching
    articles cause network requests.
 
    Args:
        max_articles:   Maximum number of articles to scrape. None = no limit.
        days_back:      How many days back the cutoff date is.
                        0 = today, 1 = yesterday, 2 = two days ago, etc.
        exact_day:      If False (default), include all articles from the
                        cutoff date up to and including today.
                        If True, include only articles published on exactly
                        the cutoff date.
 
    Examples:
        scrape_latest_articles(max_articles=10)
            → 10 most recent articles, no date filter
 
        scrape_latest_articles(max_articles=None, days_back=0)
            → all articles published today
 
        scrape_latest_articles(max_articles=None, days_back=1)
            → all articles from yesterday and today
 
        scrape_latest_articles(max_articles=None, days_back=1, exact_day=True)
            → only articles published yesterday
 
    Returns:
        List of article dicts with stage 1 and stage 2 keys populated.
        Articles where content extraction failed are skipped.
    """
    # Fetch all links from the feed (no max here – date filter comes next)
    all_links = fetch_article_links()
 
    # Apply date filter when days_back or exact_day is used
    cutoff = date.today() - timedelta(days=days_back)
 
    def _matches(article: dict) -> bool:
        article_date_str = article.get("published")
        if not article_date_str:
            return False # no date -> skip
        article_date = datetime.fromisoformat(article_date_str).date()
        if exact_day:
            return article_date == cutoff
        return article_date >= cutoff
 
    filtered = [a for a in all_links if _matches(a)]
 
    if max_articles is not None:
        filtered = filtered[:max_articles]
 
    logger.info(
        f"Fetching HTML for {len(filtered)} article(s) "
        f"(cutoff={cutoff}, exact_day={exact_day}) ..."
    )
 
    result: list[dict] = []
    for article in filtered:
        try:
            html_content = fetch_article_html(article["url"])
            if html_content:
                article["content_html"] = html_content
                result.append(article)
        except Exception as exc:
            logger.warning(f"Skipping {article['url']}: {exc}")
 
    logger.info(f"Successfully scraped {len(result)}/{len(filtered)} articles.")
    return result
 
 
 
