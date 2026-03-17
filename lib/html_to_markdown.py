"""
HTML to Markdown Converter
===========================
Converts HTML to clean Markdown using html2text, with a BeautifulSoup
preprocessing step to remove noise.

Supports two source types:
    - "email" : aggressive preprocessing tuned for HTML email bodies
                (removes tracking pixels, quoted replies, spacer tables, etc.)
    - "web"   : lightweight preprocessing for general web pages
                (removes scripts, ads, hidden elements, etc.)

DEPENDENCIES:
    pip install html2text beautifulsoup4

html2text      – battle-tested HTML→Markdown engine.
                 https://github.com/Alir3z4/html2text
beautifulsoup4 – preprocessing only (stripping noise before conversion).
"""

import re
import html2text
from bs4 import BeautifulSoup
from typing import Literal

SourceType = Literal["email", "web"]


# ──────────────────────────────────────────────
# Preprocessing – email
# ──────────────────────────────────────────────

def _preprocess_email_html(html: str) -> str:
    """
    Cleans up email-specific HTML noise before Markdown conversion.

    Assumes _preprocess_web_html() has already run, so only handles
    artefacts unique to email HTML: tracking pixels, empty layout
    tables, and purely structural wrappers.

    Args:
        html: Raw HTML string from an email body (already web-preprocessed).

    Returns:
        Cleaned HTML string ready for Markdown conversion.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove tracking pixels and spacer images (1x1 or tiny images)
    for img in soup.find_all("img"):
        width  = img.get("width",  "")
        height = img.get("height", "")
        src    = img.get("src", "")
        if (
            str(width)  in ("0", "1")
            or str(height) in ("0", "1")
            or "spacer" in src.lower()
            or "tracker" in src.lower()
            or "pixel" in src.lower()
        ):
            img.decompose()

    # Collapse layout tables that only serve as wrappers
    # (tables with no visible text content act as spacers)
    for table in soup.find_all("table"):
        if not table.get_text(strip=True):
            table.decompose()

    # Unwrap purely structural/presentational wrappers with no attributes
    for tag in soup.find_all(["span", "div", "center"]):
        if not tag.attrs:
            tag.unwrap()

    return str(soup)


# ──────────────────────────────────────────────
# Preprocessing – web
# ──────────────────────────────────────────────

def _preprocess_web_html(html: str) -> str:
    """
    Cleans up general web page HTML noise before Markdown conversion.

    Removes scripts, stylesheets, hidden elements, navigation, footers,
    ad containers, and other non-editorial content. Less aggressive than
    the email preprocessor – preserves images and links by default.

    Args:
        html: Raw HTML string from a web page (ideally already narrowed
              to the main content container).

    Returns:
        Cleaned HTML string ready for Markdown conversion.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content structural tags
    for tag in soup.find_all(["script", "style", "noscript", "iframe",
                               "head", "meta", "svg"]):
        tag.decompose()

    # Remove hidden elements
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()
    for tag in soup.find_all(attrs={"hidden": True}):
        tag.decompose()

    # Remove common non-editorial sections by role or tag
    for tag in soup.find_all(["nav", "footer", "aside"]):
        tag.decompose()

    # Remove elements whose class/id suggests ads or peripheral content.
    # Each pattern is matched as a whole word (\b boundaries) to avoid
    # removing editorial elements whose class names merely contain a noise
    # word as a substring (e.g. "article-header__title" for "header").
    # Patterns ending in "-" are kept as prefix matches (e.g. "ad-banner").
    # Collect candidates as a list first – decomposing a parent during iteration
    # detaches its children, causing AttributeError on their .attrs access.
    _noise_parts = [
        "ad", "advertisement", "banner", "social", "share", "comment",
        "newsletter", "cookie", "popup", "modal", "sidebar", "related",
        "teaser", "promo", "tracking", "analytics",
    ]
    noise_re = re.compile("|".join(
        p if p.endswith("-") else r"\b" + re.escape(p) + r"\b"
        for p in _noise_parts
    ))
    candidates = list(soup.find_all(True))
    for tag in candidates:
        if tag.parent is None:
            # Already removed as child of a previously decomposed parent
            continue
        combined = " ".join([tag.get("id", ""), *tag.get("class", [])]).lower()
        if noise_re.search(combined):
            tag.decompose()

    return str(soup)


# ──────────────────────────────────────────────
# Postprocessing – shared
# ──────────────────────────────────────────────

def _postprocess_markdown(md: str) -> str:
    """
    Cleans up common artifacts left in Markdown after HTML conversion.

    Collapses excessive blank lines, strips trailing whitespace,
    removes leftover HTML entity remnants and table-layout noise.

    Args:
        md: Raw Markdown string from html2text.

    Returns:
        Cleaned Markdown string.
    """
    # Collapse 3+ consecutive blank lines to a single blank line
    md = re.sub(r"\n{3,}", "\n\n", md)

    # Strip trailing whitespace on each line
    md = "\n".join(line.rstrip() for line in md.splitlines())

    # Remove lines that contain nothing but dashes (html2text <hr> artefacts)
    md = re.sub(r"^-{3,}\s*$", "", md, flags=re.MULTILINE)

    # Remove lines that contain only noise characters: | . , ; - and whitespace
    md = re.sub(r"^[\s|.,;-]+$", "", md, flags=re.MULTILINE)

    # Strip leading pipes and whitespace from lines with real content after them
    # e.g. "|  |  | Some text"  ->  "Some text"
    md = re.sub(r"^[\s|]+(?=\S)", "", md, flags=re.MULTILINE)

    # Remove leftover HTML entities not caught by html2text
    md = re.sub(r"&[a-zA-Z]+;", " ", md)
    md = re.sub(r"&#\d+;",       " ", md)

    # Final collapse after entity removal may leave new blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)

    return md.strip()


# ──────────────────────────────────────────────
# html2text configuration
# ──────────────────────────────────────────────

def _build_converter(
    ignore_links:  bool = False,
    ignore_images: bool = True,
    body_width:    int  = 0,
) -> html2text.HTML2Text:
    """
    Creates a configured html2text converter instance.

    Args:
        ignore_links:  If True, link URLs are dropped (only anchor text kept).
        ignore_images: If True, <img> tags are omitted entirely.
        body_width:    Line-wrap width in characters. 0 = no wrapping.

    Returns:
        Configured HTML2Text instance.
    """
    h = html2text.HTML2Text()
    h.ignore_links        = ignore_links
    h.ignore_images       = ignore_images
    h.ignore_emphasis     = False
    h.body_width          = body_width
    h.unicode_snob        = True   # prefer Unicode over ASCII approximations
    h.skip_internal_links = True   # drop anchor-only href="#..." links
    h.protect_links       = False
    h.wrap_links          = False
    h.mark_code           = True   # wrap <code>/<pre> in backticks
    return h


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def html_to_markdown(
    html: str,
    source_type: SourceType = "web",
    ignore_links:  bool = False,
    ignore_images: bool = True,
    body_width:    int  = 0,
    preprocess:    bool = True,
) -> str:
    """
    Converts an HTML string to clean Markdown.

    Applies source-specific preprocessing, html2text conversion, and shared
    postprocessing. Choose source_type="email" for email bodies or
    source_type="web" for general web page content.

    Pipeline:
        1. Preprocessing  – source-specific HTML cleanup (email or web).
        2. html2text      – convert HTML structure to Markdown syntax.
        3. Postprocessing – collapse blank lines, strip artifacts.

    Args:
        html:          Raw HTML string.
        source_type:   "email" for email HTML, "web" for general web pages.
                       Controls which preprocessor is applied.
        ignore_links:  Drop hyperlink URLs, keep only anchor text.
        ignore_images: Omit <img> tags from output. Default True.
        body_width:    Line-wrap width (0 = disabled).
        preprocess:    Run source-specific HTML cleanup before conversion.
                       Set to False to skip preprocessing entirely.

    Returns:
        Clean Markdown string. Returns empty string for empty/None input.

    Raises:
        ValueError: If source_type is not "email" or "web".
    """
    if source_type not in ("email", "web"):
        raise ValueError(f"source_type must be 'email' or 'web', got: {source_type!r}")

    if not html or not html.strip():
        return ""

    if preprocess:
        if source_type == "email":
            html = _preprocess_web_html(html)
            html = _preprocess_email_html(html)
        else:
            html = _preprocess_web_html(html)

    converter = _build_converter(
        ignore_links=ignore_links,
        ignore_images=ignore_images,
        body_width=body_width,
    )
    raw_md = converter.handle(html)
    processed_md = _postprocess_markdown(raw_md)

    return processed_md
