"""
Debug script for the email pipeline.

Toggle individual functions by commenting/uncommenting in the __main__ block.

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
from lib.html_to_markdown import html_to_markdown
from sources.email.email_postprocessing import md_postprocess_remove_reply
from lib.utils import save_json, load_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("debug.log"),
        logging.StreamHandler(),
    ],
)

load_dotenv()
USER = os.environ.get("IMAP_USER")
PASSWORD = os.environ.get("IMAP_PASSWORD")


def show_folders():
    """List available IMAP folders for your provider."""
    print(list_folders(USER, PASSWORD))


def show_unread_count():
    """Print the number of unread emails in INBOX."""
    print(get_unread_count(USER, PASSWORD))


def fetch_emails_to_markdown(from_file=True):
    """Fetch/load emails, convert to Markdown, save to temp/email/*"""
    if from_file:
        emails = load_json("temp/email/emails_raw.json")
    else:
        emails = fetch_emails(
            username=USER,
            password=PASSWORD,
            folder="INBOX",
            unread=True,
            max_emails=50,
        )
        save_json(emails, "temp/email/emails_raw.json")

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


if __name__ == "__main__":
    # show_folders()
    # show_unread_count()
    fetch_emails_to_markdown(from_file=True)
