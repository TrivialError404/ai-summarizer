"""
Main Entry Point
================
Orchestrates two pipelines:
    1. Email summarisation  – fetch unread emails via IMAP and summarise each one.
    2. Heise news summary   – scrape latest articles from heise.de and summarise each one.

Prompt templates and pipeline settings are defined as module-level constants below.
All LLM calls go through query_ollama() in llm_ollama.py – no summarisation logic
lives there.
"""


import logging
from pathlib import Path

from setup_logging import setup_logger
from lib.email.email_fetcher import get_emails_default
from lib.email.email_sender import send_email_to_self
from lib.html_to_markdown import html_to_markdown
from lib.llm_ollama import query_ollama
from lib.utils import save_json
from sources.email.email_postprocessing import md_postprocess_remove_reply
from sources.email.email_report import build_summary_body_md as build_email_body_md
from sources.heise.heise_scraper import scrape_articles_by_filter, md_postprocess_remove_section_noise
from sources.heise.heise_report import build_summary_body_md as build_heise_body_md
from datetime import datetime
import locale
locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")

logger = logging.getLogger(__name__)

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
{content_markdown}"""


HEISE_PROMPT = """\
Task: Summarize the following news article in German.

Rules:
- Output exactly 3 sentences in German.
- Focus on the key facts only.
- Do NOT use filler phrases.

Article:
{content_markdown}"""


# ──────────────────────────────────────────────
# Pipeline 1 – Emails
# ──────────────────────────────────────────────

def summarise_emails() -> list[dict]:
    """
    Fetches unread emails and generates a short LLM summary for each one.

    Converts HTML bodies to clean Markdown before passing them to the LLM.
    Sends the collected summaries as a single email.

    Returns:
        List of enriched email dicts with 'content_markdown', 'prompt', and
        'llm_response' keys added.
    """
    # Fetch raw emails
    emails = get_emails_default(folder="INBOX", unread=True)
    logger.info(f"Processing {len(emails)} email(s) ...")

    results = []
    for i, email in enumerate(emails, 1):
        subject = email.get("Subject", "")
        logger.info(f"[{i}/{len(emails)}] {email.get('uid')} | {subject}")

        # Convert to Markdown
        if email.get("text/html"):
            content_markdown = html_to_markdown(email["text/html"], source_type="email")
        else:
            content_markdown = email.get("text/plain", "")
        content_markdown = md_postprocess_remove_reply(content_markdown)

        if not content_markdown.strip():
            logger.warning("  Skipping - no readable content.")
            results.append({**email, "content_markdown": "", "prompt": "", "llm_response": None})
            continue
        
        # Summarize each mail from LLM
        prompt = EMAIL_PROMPT.format(content_markdown=content_markdown)
        llm_response = query_ollama(prompt, stream=True, collect_metrics=True)
        logger.info(f"  → {llm_response['response']}")

        results.append({
            **email,
            "content_markdown": content_markdown,
            "prompt":           EMAIL_PROMPT.format(content_markdown="... [content_markdown] ..."),
            "llm_response":     llm_response,
        })

    # Send email
    debug = False
    result_path = Path("temp/email/result.json")
    save_json(results, str(result_path))
    send_email_to_self(
        subject="E-Mail Zusammenfassung",
        body_md=build_email_body_md(results),
        attachments=[result_path] if debug else None,
    )

    return results


# ──────────────────────────────────────────────
# Pipeline 2 – Heise articles
# ──────────────────────────────────────────────

def summarise_heise_articles() -> list[dict]:
    """
    Scrapes the latest heise.de articles and generates a short LLM summary
    for each one.

    Converts the extracted article HTML to clean Markdown before passing it
    to the LLM. Sends the collected summaries as a single email.

    Returns:
        List of article dicts with added keys:
            - 'content_markdown' (str):  Cleaned article text used as LLM input.
            - 'prompt'           (str):  Prompt template (content placeholder only).
            - 'llm_response'     (dict): Full response dict from query_ollama().
    """
    # Fetch raw articles from heise.de
    articles = scrape_articles_by_filter(max_articles=None, days_back=1, exact_day=True)
    logger.info(f"Processing {len(articles)} article(s) ...")

    results = []
    for i, article in enumerate(articles, 1):
        title = article.get("title", article.get("url", ""))
        logger.info(f"[{i}/{len(articles)}] {title[:70]}")

        # Convert to Markdown
        content_markdown = html_to_markdown(article["content_html"], source_type="web")
        content_markdown = md_postprocess_remove_section_noise(content_markdown)

        if not content_markdown.strip():
            logger.warning("  Skipping – no readable content.")
            results.append({**article, "content_markdown": "", "prompt": "", "llm_response": None})
            continue
        
        # Summarize each mail from LLM
        prompt = HEISE_PROMPT.format(content_markdown=content_markdown)
        llm_response = query_ollama(prompt, stream=True, collect_metrics=True)
        logger.info(f"  → {llm_response['response']}")

        results.append({
            **article,
            "html":             "",   # drop raw HTML to keep output readable
            "content_markdown": content_markdown,
            "prompt":           HEISE_PROMPT.format(content_markdown="... [content_markdown] ..."),
            "llm_response":     llm_response,
        })

    # Send email
    debug = False
    result_path = Path("temp/heise/result.json")
    save_json(results, str(result_path))
    send_email_to_self(
        subject="heise.de \u2013 Zusammenfassung",
        body_md=build_heise_body_md(results),
        attachments=[result_path] if debug else None,
    )

    return results


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    setup_logger()

    # Summarize emails
    summarise_emails()

    # Summarize articles from heise.de
    summarise_heise_articles()
