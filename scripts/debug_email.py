"""
Debug script for the email pipeline.

Each step reads from the previous step's saved file and writes its output.
Toggle steps by commenting/uncommenting in the __main__ block.

Steps:
    1. step1_fetch_raw()    – Fetch emails from IMAP        → emails_raw.json
    2. step2_to_markdown()  – Convert to Markdown            → emails_md.json / .txt
    3. step3_run_llm()      – LLM summarisation              → emails_llm.json / .txt
    4. step4_send_email()   – Send summary via email

Usage (from project root):
    python scripts/debug_email.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import os

from dotenv import load_dotenv

from lib.email.email_fetcher import fetch_emails, list_folders, get_unread_count
from lib.email.email_sender import send_email_to_self
from lib.html_to_markdown import html_to_markdown
from lib.llm_ollama import query_ollama
from lib.utils import save_json, load_json
from sources.email.email_postprocessing import md_postprocess_remove_reply
from sources.email.email_report import build_summary_body_md
from main import EMAIL_PROMPT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("debug.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

load_dotenv()
USER = os.environ.get("IMAP_USER")
PASSWORD = os.environ.get("IMAP_PASSWORD")


def show_folders():
    """List available IMAP folders for your provider."""
    print(list_folders(USER, PASSWORD))


def show_unread_count():
    """Print the number of unread emails in INBOX."""
    print(get_unread_count(USER, PASSWORD))


def step1_fetch_raw():
    """Fetch emails from IMAP and save to temp/email/emails_raw.json."""
    emails = fetch_emails(
        username=USER,
        password=PASSWORD,
        folder="INBOX",
        unread=True,
        max_emails=5,
    )
    save_json(emails, "temp/email/emails_raw.json")
    logger.info(f"Fetched and saved {len(emails)} emails")


def step2_to_markdown():
    """Load raw emails, convert to Markdown, save to temp/email/emails_md.*"""
    emails = load_json("temp/email/emails_raw.json")

    for e in emails:
        if e.get("text/html"):
            content_markdown = html_to_markdown(
                e["text/html"], source_type="email", ignore_links=True, ignore_images=True,
            )
        else:
            content_markdown = e.get("text/plain", "")
        content_markdown = md_postprocess_remove_reply(content_markdown)
        e["content_markdown"] = content_markdown

    save_json(emails, "temp/email/emails_md.json")
    with open("temp/email/emails_md.txt", "w", encoding="utf-8") as f:
        for e in emails:
            f.write(f"{e['From']} | {e['Subject']} | {e['Date']}\n")
            f.write(e["content_markdown"])
            f.write("\n" + "-" * 80 + "\n\n")
    logger.info(f"Converted {len(emails)} emails to Markdown")


def step3_run_llm():
    """Load Markdown emails, run LLM summaries, save to temp/email/emails_llm.*"""
    emails = load_json("temp/email/emails_md.json")

    results = []
    for i, email in enumerate(emails, 1):
        subject = email.get("Subject", "")
        logger.info(f"[{i}/{len(emails)}] {email.get('uid')} | {subject}")

        content_markdown = email.get("content_markdown", "")
        if not content_markdown.strip():
            logger.warning("  Skipping - no readable content.")
            results.append({**email, "prompt": "", "llm_response": None})
            continue

        prompt = EMAIL_PROMPT.format(content_markdown=content_markdown)
        llm_response = query_ollama(prompt, stream=True, collect_metrics=True)
        logger.info(f"  → {llm_response['response']}")

        results.append({
            **email,
            "prompt":       EMAIL_PROMPT.format(content_markdown="... [content_markdown] ..."),
            "llm_response": llm_response,
        })

    save_json(results, "temp/email/emails_llm.json")
    with open("temp/email/emails_llm.txt", "w", encoding="utf-8") as f:
        for e in results:
            response = e["llm_response"]["response"] if e.get("llm_response") else "(no response)"
            f.write(f"{e['From']} | {e['Subject']} | {e['Date']}\n")
            f.write(response)
            f.write("\n" + "-" * 80 + "\n\n")
    logger.info(f"LLM processing done for {len(results)} emails")


def step4_send_email():
    """Load LLM results and send summary email."""
    results = load_json("temp/email/emails_llm.json")
    result_path = Path("temp/email/result.json")
    save_json(results, str(result_path))
    send_email_to_self(
        subject="E-Mail Zusammenfassung",
        body_md=build_summary_body_md(results),
        attachments=[result_path],
    )
    logger.info("Summary email sent")


if __name__ == "__main__":
    #show_folders()
    #show_unread_count()
    #step1_fetch_raw()
    #step2_to_markdown()
    #step3_run_llm()
    step4_send_email()
    pass
