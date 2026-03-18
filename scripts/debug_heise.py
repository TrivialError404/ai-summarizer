"""
Debug script for the Heise pipeline.

Each step reads from the previous step's saved file and writes its output.
Toggle steps by commenting/uncommenting in the __main__ block.

Steps:
    1. step1_fetch_raw()    – Scrape articles from heise.de  → articles_raw.json
    2. step2_to_markdown()  – Convert to Markdown            → articles_md.json / .txt
    3. step3_run_llm()      – LLM summarisation              → articles_llm.json / .txt
    4. step4_send_email()   – Send summary via email

    Bonus: step1_fetch_links() – RSS links only              → links.json / .txt

Usage (from project root):
    python scripts/debug_heise.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import locale
import logging
from datetime import datetime

from lib.email.email_sender import send_email_to_self
from lib.html_to_markdown import html_to_markdown
from lib.llm_ollama import query_ollama
from lib.utils import save_json, load_json, timestamp_iso_8601_to_str
from sources.heise.heise_scraper import (
    fetch_article_links,
    scrape_articles_by_filter,
    md_postprocess_remove_section_noise,
)
from main import HEISE_PROMPT

locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("debug.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def step1_fetch_links():
    """Fetch all article links from RSS and save to temp/heise/links.*"""
    logger.info("Fetching all links from heise.de RSS feed")
    articles = fetch_article_links()
    save_json(articles, "temp/heise/links.json")
    with open("temp/heise/links.txt", "w", encoding="utf-8") as f:
        for a in articles:
            dt = datetime.fromisoformat(a["published"])
            f.write(f"{dt.strftime('%A %d.%m.%Y %H:%M')} | {a['title']} | {a['url']}\n")
    logger.info(f"Saved {len(articles)} links")


def step1_fetch_raw():
    """Scrape articles from heise.de and save to temp/heise/articles_raw.json."""
    articles = scrape_articles_by_filter(max_articles=5, days_back=0, exact_day=False)
    save_json(articles, "temp/heise/articles_raw.json")
    logger.info(f"Fetched and saved {len(articles)} articles")


def step2_to_markdown():
    """Load raw articles, convert to Markdown, save to temp/heise/articles_md.*"""
    articles = load_json("temp/heise/articles_raw.json")

    for article in articles:
        content_markdown = html_to_markdown(article["content_html"], source_type="web")
        content_markdown = md_postprocess_remove_section_noise(content_markdown)
        article["content_markdown"] = content_markdown

    save_json(articles, "temp/heise/articles_md.json")
    with open("temp/heise/articles_md.txt", "w", encoding="utf-8") as f:
        for a in articles:
            dt = datetime.fromisoformat(a["published"])
            f.write(f"{dt.strftime('%A %d.%m.%Y %H:%M')} | {a['title']} | {a['url']}\n")
            f.write(a["content_markdown"])
            f.write("\n" + "-" * 80 + "\n\n")
    logger.info(f"Converted {len(articles)} articles to Markdown")


def step3_run_llm():
    """Load Markdown articles, run LLM summaries, save to temp/heise/articles_llm.*"""
    articles = load_json("temp/heise/articles_md.json")

    results = []
    for i, article in enumerate(articles, 1):
        title = article.get("title", article.get("url", ""))
        logger.info(f"[{i}/{len(articles)}] {title[:70]}")

        content_markdown = article.get("content_markdown", "")
        if not content_markdown.strip():
            logger.warning("  Skipping – no readable content.")
            results.append({**article, "prompt": "", "llm_response": None})
            continue

        prompt = HEISE_PROMPT.format(content_markdown=content_markdown)
        llm_response = query_ollama(prompt, stream=True, collect_metrics=True)
        logger.info(f"  → {llm_response['response']}")

        results.append({
            **article,
            "html":         "",   # drop raw HTML to keep output readable
            "prompt":       HEISE_PROMPT.format(content_markdown="... [content_markdown] ..."),
            "llm_response": llm_response,
        })

    save_json(results, "temp/heise/articles_llm.json")
    with open("temp/heise/articles_llm.txt", "w", encoding="utf-8") as f:
        for a in results:
            dt = datetime.fromisoformat(a["published"])
            response = a["llm_response"]["response"] if a.get("llm_response") else "(no response)"
            f.write(f"{dt.strftime('%A %d.%m.%Y %H:%M')} | {a['title']} | {a['url']}\n")
            f.write(response)
            f.write("\n" + "-" * 80 + "\n\n")
    logger.info(f"LLM processing done for {len(results)} articles")


def step4_send_email():
    """Load LLM results and send summary email."""
    results = load_json("temp/heise/articles_llm.json")

    summary_string = ""
    for article in results:
        if not article.get("llm_response"):
            continue
        summary_string += f"{timestamp_iso_8601_to_str(article['published'])} | {article['title']} | {article['url']}\n"
        summary_string += article["llm_response"]["response"]
        summary_string += "\n" + "-" * 80 + "\n\n"

    send_email_to_self(subject="Summary heise.de", body=summary_string)
    logger.info("Summary email sent")


if __name__ == "__main__":
    # step1_fetch_links()
    # step1_fetch_raw()
    # step2_to_markdown()
    # step3_run_llm()
    # step4_send_email()
    pass
