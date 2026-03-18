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

from lib.email.email_fetcher import get_emails_default
from lib.email.email_sender import send_email_to_self
from lib.html_to_markdown import html_to_markdown
from lib.llm_ollama import query_ollama
from lib.utils import timestamp_iso_8601_to_str
from sources.email.email_postprocessing import md_postprocess_remove_reply
from sources.heise.heise_scraper import scrape_articles_by_filter, md_postprocess_remove_section_noise
from datetime import datetime
import locale
locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
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

    # Summarize all mails and send summary by mail
    summary_string = ""
    for email in results:
        if not email.get("llm_response"):
            continue
        summary_string += f"{timestamp_iso_8601_to_str(email['Date'])} | {email['From']} | {email['Subject']}\n"
        summary_string += email["llm_response"]["response"]
        summary_string += "\n" + "-"*80 + "\n\n"
    send_email_to_self(subject="Summary Email", body=summary_string)

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

    # Summarize all articles and send summary by mail
    summary_string = ""
    for article in results:
        if not article.get("llm_response"):
            continue
        summary_string += f"{timestamp_iso_8601_to_str(article['published'])} | {article['title']} | {article['url']}\n"
        summary_string += article["llm_response"]["response"]
        summary_string += "\n" + "-"*80 + "\n\n"
    send_email_to_self(subject="Summary heise.de", body=summary_string)

    return results


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":

    # Summarize emails
    summarise_emails()

    # Summarize articles from heise.de
    summarise_heise_articles()
