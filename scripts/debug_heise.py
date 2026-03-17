"""
Debug script for the Heise pipeline.

Scrapes or loads articles, converts HTML to Markdown, and dumps the results
to temp/heise/ for manual inspection.

Usage (from project root):
    python scripts/debug_heise.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import locale
import logging
from datetime import datetime

from sources.heise.scraper import (
    fetch_article_links,
    scrape_articles_by_filter,
    md_remove_noise,
)
from lib.html_to_markdown import html_to_markdown
from lib.utils import save_json, load_json

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

FROM_FILE = True

# ── Fetch or load ────────────────────────────
if FROM_FILE:
    articles = load_json("temp/heise/articles_raw.json")
else:
    articles = scrape_articles_by_filter(max_articles=5, days_back=0, exact_day=False)
    save_json(articles, "temp/heise/articles_raw.json")

# ── Convert to Markdown ──────────────────────
for article in articles:
    content_markdown = html_to_markdown(article["content_html"], source_type="web")
    content_markdown = md_remove_noise(content_markdown)
    article["content_markdown"] = content_markdown

# ── Save results ─────────────────────────────
save_json(articles, "temp/heise/articles_md.json")
with open("temp/heise/articles_md.txt", "w", encoding="utf-8") as f:
    for a in articles:
        dt = datetime.fromisoformat(a["published"])
        f.write(f"{dt.strftime('%A %d.%m.%Y %H:%M')} | {a['title']} | {a['url']}\n")
        f.write(a["content_markdown"])
        f.write("\n" + "-" * 80 + "\n\n")
