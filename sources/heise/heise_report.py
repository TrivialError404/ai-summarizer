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

    Each article becomes a section with a linked title, author, date, and the
    LLM summary. Failed items are shown with an error indicator instead of a
    summary. Skipped items (no readable content) are omitted entirely.

    A summary line at the top shows total / failed counts.

    Requires locale de_DE.UTF-8 to be set by the caller for German weekday
    names in the date string.

    Args:
        results: List of article dicts. Each dict must have a 'status' key
                 ("ok", "skipped", or "failed"). Failed items additionally
                 need an 'error' dict with 'type' and 'message'.

    Returns:
        Markdown string ready to be passed as body_md to send_email_to_self().
    """
    n_ok = sum(1 for r in results if r.get("status") == "ok")
    n_failed = sum(1 for r in results if r.get("status") == "failed")

    summary = f"*{n_ok} von {len(results)} Artikel erfolgreich zusammengefasst"
    if n_failed:
        summary += f" · {n_failed} fehlgeschlagen"
    summary += "*"
    summary += "Liste der letzten heise.de Artikel: [Newsticker](https://www.heise.de/newsticker/)"

    lines = [summary, "", "---", ""]

    for article in results:
        status = article.get("status")
        if status == "skipped":
            continue

        title = article["title"]
        url = article["url"]
        author = article.get("author", "")
        dt = datetime.fromisoformat(article["published"])
        date_str = dt.strftime("%A, %d.%m.%Y %H:%M")

        meta = f"*{date_str}"
        if author:
            meta += f" \u00b7 {author}"
        meta += "*"

        if status == "failed":
            err = article.get("error", {})
            error_msg = f"{err.get('type', 'Error')}: {err.get('message', '')}"
            lines += [
                f"### [{title}]({url})",
                meta,
                "",
                f"\u26a0 Fehler: {error_msg}",
                "",
                "---",
                "",
            ]
        else:
            response = article["llm_response"]["response"]
            response = re.sub(r"\n+", " ", response).strip()
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
