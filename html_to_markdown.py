"""
Email HTML to Markdown Converter
=================================
Converts HTML email bodies to clean Markdown using html2text,
with a BeautifulSoup preprocessing step to remove email-specific clutter.

DEPENDENCIES:
    pip install html2text beautifulsoup4

html2text  – battle-tested HTML→Markdown engine, excellent for email HTML.
             https://github.com/Alir3z4/html2text
beautifulsoup4 – used for preprocessing only (stripping noise before conversion).
"""

import re
import html2text
from bs4 import BeautifulSoup


# ──────────────────────────────────────────────
# Preprocessing
# ──────────────────────────────────────────────

def _preprocess_email_html(html: str) -> str:
    """
    Cleans up email-specific HTML noise before Markdown conversion.

    Removes or simplifies elements that produce garbage output when
    converted naively: tracking pixels, spacer images, nested layout
    tables, style/script blocks, and invisible elements.

    Args:
        html: Raw HTML string from an email body.

    Returns:
        Cleaned HTML string ready for Markdown conversion.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content tags entirely
    for tag in soup.find_all(["style", "script", "head", "meta", "noscript"]):
        tag.decompose()

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

    # Collapse layout divs/tables that only serve as wrappers
    # (tables with no visible text content act as spacers)
    for table in soup.find_all("table"):
        if not table.get_text(strip=True):
            table.decompose()

    # Remove elements explicitly hidden via inline style or HTML attributes
    for tag in soup.find_all(style=re.compile(r"display\s*:\s*none", re.I)):
        tag.decompose()
    for tag in soup.find_all(attrs={"aria-hidden": "true"}):
        tag.decompose()

    # Unwrap purely structural/presentational wrappers
    for tag in soup.find_all(["span", "div", "center"]):
        if not tag.attrs:
            tag.unwrap()

    return str(soup)


# ──────────────────────────────────────────────
# Postprocessing
# ──────────────────────────────────────────────

def _postprocess_markdown(md: str) -> str:
    """
    Cleans up common artifacts left in Markdown after HTML conversion.

    Collapses excessive blank lines, strips trailing whitespace,
    and removes leftover HTML entity remnants.

    Args:
        md: Raw Markdown string from html2text.

    Returns:
        Cleaned Markdown string.
    """
    # Collapse 3+ consecutive blank lines to a single blank line
    md = re.sub(r"\n{3,}", "\n\n", md)

    # Strip trailing whitespace on each line
    md = "\n".join(line.rstrip() for line in md.splitlines())

    # Remove lines that contain nothing but dashes used as dividers
    # that html2text generates from <hr> inside table cells
    md = re.sub(r"^-{3,}\s*$", "", md, flags=re.MULTILINE)

    # Remove lines that contain only noise characters: | . , ; - and whitespace
    # Catches table layout artifacts like "|  |  |" or "| . |"
    md = re.sub(r"^[\s|.,;-]+$", "", md, flags=re.MULTILINE)

    # Strip leading pipes and whitespace from lines that have real content after them
    # e.g. "|  |  | Passwort-Manager"  ->  "Passwort-Manager"
    md = re.sub(r"^[\s|]+(?=\S)", "", md, flags=re.MULTILINE)

    # Remove leftover HTML entities not caught by html2text
    md = re.sub(r"&[a-zA-Z]+;", " ", md)
    md = re.sub(r"&#\d+;",       " ", md)

    # Remove quoted reply blocks starting with "Von:" or "From:" followed by an email address
    md = re.sub(r"\n+(?:\*\*)?(?:Von|From):(?:\*\*)?.*?[\w.+-]+@[\w.-]+.*$[\s\S]*", "", md, flags=re.MULTILINE)

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
    h.ignore_links       = ignore_links
    h.ignore_images      = ignore_images
    h.ignore_emphasis    = False
    h.body_width         = body_width
    h.unicode_snob       = True   # prefer Unicode over ASCII approximations
    h.skip_internal_links= True   # drop anchor-only href="#..." links
    h.protect_links      = False
    h.wrap_links         = False
    h.mark_code          = True   # wrap <code>/<pre> in backticks
    return h


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def html_to_markdown(
    html: str,
    ignore_links:  bool = False,
    ignore_images: bool = True,
    body_width:    int  = 0,
    preprocess:    bool = True,
) -> str:
    """
    Converts an HTML email body to clean Markdown.

    Pipeline:
        1. Preprocessing  – remove tracking pixels, hidden elements, etc.
        2. html2text      – convert HTML structure to Markdown syntax.
        3. Postprocessing – collapse blank lines, strip artifacts.

    Args:
        html:          Raw HTML string (email body).
        ignore_links:  Drop hyperlink URLs, keep only anchor text.
        ignore_images: Omit <img> tags from output. Default True.
        body_width:    Line-wrap width (0 = disabled).
        preprocess:    Run BeautifulSoup cleanup before conversion.

    Returns:
        Clean Markdown string. Returns empty string for empty/None input.
    """
    if not html or not html.strip():
        return ""

    if preprocess:
        html = _preprocess_email_html(html)

    converter = _build_converter(
        ignore_links=ignore_links,
        ignore_images=ignore_images,
        body_width=body_width,
    )
    raw_md = converter.handle(html)
    return _postprocess_markdown(raw_md)


def html_to_markdown_for_llm(html: str) -> str:
    """
    Converts email HTML to Markdown optimised for LLM summarisation.

    Uses aggressive settings: links and images are stripped, only
    readable prose and structure are retained.

    This is a convenience wrapper around html_to_markdown() with
    settings tuned for feeding clean text into a language model.

    Args:
        html: Raw HTML string (email body).

    Returns:
        Plain, clean Markdown string without links or images.
    """
    return html_to_markdown(
        html,
        ignore_links=True,
        ignore_images=True,
        body_width=0,
        preprocess=True,
    )