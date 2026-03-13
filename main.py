"""
Main Entry Point
================
Orchestrates two pipelines:
    1. Email summarisation  – fetch unread emails via IMAP and summarise each one.
    2. Heise news summary   – scrape latest articles from heise.de and summarise each one.

Prompt templates and pipeline settings are defined as module-level constants below.
All LLM calls go through query_ollama() in llm_ollama.py – no summarisation logic
lives there.

Results are saved to the temp/ directory as JSON files for offline analysis.
"""


import logging
from pathlib import Path

from email_fetcher import get_emails_default
from heise_scraper import scrape_articles_by_filter, _md_remove_noise
from html_to_markdown import html_to_markdown_for_llm, html_to_markdown
from llm_ollama import query_ollama
from utils import save_json, load_json

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Output paths
# ──────────────────────────────────────────────

DIR_TEMP = Path("temp")

EMAIL_RAW_FILE    = DIR_TEMP / "emails_raw.json"
EMAIL_RESULT_FILE = DIR_TEMP / "emails_summarised.json"

HEISE_RAW_FILE    = DIR_TEMP / "heise_raw.json"
HEISE_RESULT_FILE = DIR_TEMP / "heise_summarised.json"

# ──────────────────────────────────────────────
# LLM settings
# ──────────────────────────────────────────────

COLLECT_METRICS = True   # Set False to skip token/latency tracking

# ──────────────────────────────────────────────
# Prompt templates
# ──────────────────────────────────────────────

EMAIL_PROMPT = """\
Task: Summarize.

Rules:
- Output exactly 2 sentences in German.
- Do NOT write a reply.
- Do NOT address the sender.
- Only summarize the content.

Email:
{content}"""


HEISE_PROMPT = """\
Task: Summarize the following news article in German.

Rules:
- Output exactly 3 sentences in German.
- Focus on the key facts only.
- Do NOT use filler phrases.

Article:
{content}"""


# ──────────────────────────────────────────────
# Pipeline 1 – Emails
# ──────────────────────────────────────────────
 
def summarise_emails(from_file: bool = False) -> list[dict]:
    """
    Fetches unread emails and generates a short LLM summary for each one.
 
    Converts HTML bodies to clean Markdown before passing them to the LLM.
    Results are saved to EMAIL_RESULT_FILE.
 
    Args:
        from_file: If True, loads previously fetched emails from
                   EMAIL_RAW_FILE instead of connecting to IMAP.
 
    Returns:
        List of enriched email dicts with 'content', 'prompt', and
        'llm_response' keys added.
    """
    # ── Fetch or load ──────────────────────────
    if from_file:
        logger.info(f"Loading emails from {EMAIL_RAW_FILE}")
        emails = load_json(EMAIL_RAW_FILE)
    else:
        emails = get_emails_default()
        save_json(emails, EMAIL_RAW_FILE)
 
    logger.info(f"Processing {len(emails)} email(s) ...")
 
    # ── Summarise each email ───────────────────
    results = []
    for i, email in enumerate(emails, 1):
        subject = email.get("Subject", "")
        logger.info(f"[{i}/{len(emails)}] {email.get('uid')} | {subject}")
 
        # Convert body to clean Markdown
        if email.get("text/html"):
            content = html_to_markdown_for_llm(email["text/html"], source_type="email")
        else:
            content = email.get("text/plain", "")
 
        if not content.strip():
            logger.warning(f"  Skipping - no readable content.")
            results.append({**email, "content": "", "prompt": "", "llm_response": None})
            continue
 
        prompt = EMAIL_PROMPT.format(content=content)
        llm_response = query_ollama(prompt, stream=False, collect_metrics=COLLECT_METRICS)
        logger.info(f"  → {llm_response['response']}")
 
        results.append({
            **email,
            "content":      content,
            "prompt":       EMAIL_PROMPT.format(content="... [content] ..."),
            "llm_response": llm_response,
        })
 
    save_json(results, EMAIL_RESULT_FILE)
    return results
 
 
# ──────────────────────────────────────────────
# Pipeline 2 – Heise articles
# ──────────────────────────────────────────────
 
def summarise_heise_articles(
    max_articles: int = 5,
    from_file: bool = False,
) -> list[dict]:
    """
    Scrapes the latest heise.de articles and generates a short LLM summary
    for each one.
 
    Converts the extracted article HTML to clean Markdown before passing it
    to the LLM. Results are saved to HEISE_RESULT_FILE.
 
    Args:
        max_articles: Maximum number of articles to scrape and summarise.
                      Ignored when from_file=True.
        from_file:    If True, loads previously scraped articles from
                      HEISE_RAW_FILE instead of fetching from the web.
 
    Returns:
        List of article dicts with added keys:
            - 'markdown'     (str):  Cleaned article text used as LLM input.
            - 'prompt'       (str):  Prompt template (content placeholder only).
            - 'llm_response' (dict): Full response dict from query_ollama().
    """
    # ── Scrape or load ─────────────────────────
    if from_file:
        logger.info(f"Loading articles from {HEISE_RAW_FILE}")
        articles = load_json(HEISE_RAW_FILE)
    else:
        articles = scrape_articles_by_filter(max_articles=max_articles)
        save_json(articles, HEISE_RAW_FILE)
 
    logger.info(f"Processing {len(articles)} article(s) ...")
 
    # ── Summarise each article ─────────────────
    results = []
    for i, article in enumerate(articles, 1):
        title = article.get("title", article.get("url", ""))
        logger.info(f"[{i}/{len(articles)}] {title[:70]}")
 
        md = _md_remove_noise(
            html_to_markdown(article["html"], source_type="web")
        )
 
        if not md.strip():
            logger.warning(f"  Skipping – no readable content.")
            results.append({**article, "markdown": "", "prompt": "", "llm_response": None})
            continue
 
        prompt = HEISE_PROMPT.format(content=md)
        llm_response = query_ollama(prompt, stream=True, collect_metrics=COLLECT_METRICS)
        logger.info(f"  → {llm_response['response']}")
 
        results.append({
            **article,
            "html":         "",   # drop raw HTML from output to keep file readable
            "markdown":     md,
            "prompt":       HEISE_PROMPT.format(content="... [content] ..."),
            "llm_response": llm_response,
        })
 
    save_json(results, HEISE_RESULT_FILE)
    return results
 
 
# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
 
if __name__ == "__main__":
 
    # Summarize emails
    #email_results = summarise_emails(from_file=False)
 
    # Summarize articles from heise.de
    heise_results = summarise_heise_articles(max_articles=5, from_file=True)