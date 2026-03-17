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
from email_sender import send_email_to_self
from heise_scraper import scrape_articles_by_filter, md_remove_noise
from html_to_markdown import html_to_markdown, email_md_remove_reply
from llm_ollama import query_ollama
from utils import save_json, load_json, timestamp_iso_8601_to_str
from datetime import datetime
import locale
locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Output paths
# ──────────────────────────────────────────────

DIR_TEMP = Path("temp")

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
        logger.info(f"Loading emails from file")
        emails = load_json("temp/email/emails_raw.json")
    else:
        emails = get_emails_default(folder="INBOX")
        save_json(emails, "temp/email/emails_raw.json")
 
    logger.info(f"Processing {len(emails)} email(s) ...")
 
    # ── Process each email ─────────────────────
    results = []
    for i, email in enumerate(emails, 1):
        subject = email.get("Subject", "")
        logger.info(f"[{i}/{len(emails)}] {email.get('uid')} | {subject}")
 
        # Convert body to clean Markdown
        if email.get("text/html"):
            content_markdown = html_to_markdown(email["text/html"], source_type="email", )
        else:
            content = email.get("text/plain", "")
            content_markdown = email_md_remove_reply(content)
 
        if not content_markdown.strip():
            logger.warning(f"  Skipping - no readable content.")
            results.append({**email, "content_markdown": "", "prompt": "", "llm_response": None})
            continue
        
        # LLM
        prompt = EMAIL_PROMPT.format(content_markdown=content_markdown)
        llm_response = query_ollama(prompt, stream=True, collect_metrics=True)
        logger.info(f"  → {llm_response['response']}")
 
        results.append({
            **email,
            "content_markdown":      content_markdown,
            "prompt":       EMAIL_PROMPT.format(content_markdown="... [content_markdown] ..."),
            "llm_response": llm_response,
        })
    
    # Save
    save_json(results, "temp/email/emails_llm.json")
    with open("temp/email/emails_llm.txt", "w", encoding="utf-8") as f:
        for email in results:
            f.write(f"{email['From']} | {email['Subject']} | {email['Date']}\n")
            f.write(email["llm_response"]["response"])
            f.write("\n" + "-"*80 + "\n\n")

    # Email
    summary_string = ""
    for email in results:
        summary_string += f"{timestamp_iso_8601_to_str(email['Date'])} | {email['From']} | {email['Subject']}\n"
        summary_string += email["llm_response"]["response"]
        summary_string += "\n" + "-"*80 + "\n\n"
    send_email_to_self(subject="Summary Email", body=summary_string)
 
 
# ──────────────────────────────────────────────
# Pipeline 2 – Heise articles
# ──────────────────────────────────────────────
 
def summarise_heise_articles(
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
        logger.info(f"Loading articles from file")
        articles = load_json("temp/heise/articles_raw.json")
    else:
        articles = scrape_articles_by_filter(max_articles=1, days_back=0, exact_day=False)
        save_json(articles, "temp/heise/articles_raw.json")
 
    logger.info(f"Processing {len(articles)} article(s) ...")
 
    # ── Process each article ───────────────────
    results = []
    for i, article in enumerate(articles, 1):
        title = article.get("title", article.get("url", ""))
        logger.info(f"[{i}/{len(articles)}] {title[:70]}")

        # HTML to markdown
        content_markdown = html_to_markdown(article["content_html"], source_type="web")
        content_markdown = md_remove_noise(content_markdown)
 
        if not content_markdown.strip():
            logger.warning(f"  Skipping – no readable content.")
            results.append({**article, "markdown": "", "prompt": "", "llm_response": None})
            continue
 
        prompt = HEISE_PROMPT.format(content_markdown=content_markdown)
        llm_response = query_ollama(prompt, stream=True, collect_metrics=True)
        logger.info(f"  → {llm_response['response']}")
 
        results.append({
            **article,
            "html":                 "",   # drop raw HTML from output to keep file readable
            "content_markdown":     content_markdown,
            "prompt":               HEISE_PROMPT.format(content_markdown="... [content_markdown] ..."),
            "llm_response":         llm_response,
        })
    
    # Save
    save_json(results, "temp/heise/articles_llm.json")
    with open("temp/heise/articles_llm.txt", "w", encoding="utf-8") as f:
        for article in results:
            f.write(f"{timestamp_iso_8601_to_str(article["published"])} | {article['title']} | {article['url']}\n")
            f.write(article["llm_response"]["response"])
            f.write("\n" + "-"*80 + "\n\n")
    
    # Email
    summary_string = ""
    for article in results:
        summary_string += f"{timestamp_iso_8601_to_str(article["published"])} | {article['title']} | {article['url']}\n"
        summary_string += article["llm_response"]["response"]
        summary_string += "\n" + "-"*80 + "\n\n"
    send_email_to_self(subject="Summary heise.de", body=summary_string)

 
# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
 
if __name__ == "__main__":
 
    # Summarize emails
    email_results = summarise_emails(from_file=True)
    
    # Summarize articles from heise.de
    heise_results = summarise_heise_articles(from_file=True)