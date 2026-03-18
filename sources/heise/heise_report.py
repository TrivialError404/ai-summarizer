"""
Heise Report Builder
====================
Builds a formatted Markdown email body from LLM-processed Heise article results.

USAGE:
    from sources.heise.heise_report import build_summary_body_md

    body_md = build_summary_body_md(results)
    send_email_to_self(subject="heise.de \u2013 Zusammenfassung", body_md=body_md)
"""

import re
from datetime import datetime


def build_summary_body_md(results: list[dict]) -> str:
    """
    Builds a Markdown email body from LLM-processed Heise article results.

    Each article becomes a section with a linked title (to the original
    article), author, date, and the LLM summary. Consecutive newlines in
    the LLM response are collapsed to a single space.

    Requires locale de_DE.UTF-8 to be set by the caller for German weekday
    names in the date string.

    Args:
        results: List of article dicts with at least 'title', 'url',
                 'published', and 'llm_response' keys. Entries without an
                 'llm_response' are skipped.

    Returns:
        Markdown string ready to be passed as body_md to send_email_to_self().
    """
    lines = []

    for article in results:
        if not article.get("llm_response"):
            continue

        title = article["title"]
        url = article["url"]
        author = article.get("author", "")
        dt = datetime.fromisoformat(article["published"])
        date_str = dt.strftime("%A, %d.%m.%Y %H:%M")

        response = article["llm_response"]["response"]
        response = re.sub(r"\n+", " ", response).strip()

        meta = f"*{date_str}"
        if author:
            meta += f" \u00b7 {author}"
        meta += "*"

        lines += [
            f"### [{title}]({url})",
            meta,
            "",
            response,
            "",
            "---",
            "",
        ]

    return "\n".join(lines)
