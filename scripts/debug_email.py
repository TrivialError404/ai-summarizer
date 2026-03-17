"""
Debug script for the email pipeline.

Fetches or loads emails, converts HTML to Markdown, and dumps the results
to temp/email/ for manual inspection.

Usage (from project root):
    python scripts/debug_email.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging
import os

from dotenv import load_dotenv

from sources.email.fetcher import fetch_emails, get_emails_default, list_folders, get_unread_count
from lib.html_to_markdown import html_to_markdown, email_md_remove_reply
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

FROM_FILE = True

# ── Fetch or load ────────────────────────────
if FROM_FILE:
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

# ── Convert to Markdown ──────────────────────
for e in emails:
    if e.get("text/html"):
        content_markdown = html_to_markdown(
            e["text/html"], source_type="email", ignore_links=True, ignore_images=True,
        )
    else:
        content = e.get("text/plain", "")
        content_markdown = email_md_remove_reply(content)
    e["content_markdown"] = content_markdown

# ── Save results ─────────────────────────────
save_json(emails, "temp/email/emails_md.json")
with open("temp/email/emails.txt", "w", encoding="utf-8") as f:
    for e in emails:
        f.write(f"{e['From']} | {e['Subject']} | {e['Date']}\n")
        f.write(e["content_markdown"])
        f.write("\n" + "-" * 80 + "\n\n")
