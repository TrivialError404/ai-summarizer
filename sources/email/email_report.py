"""
Email Report Builder
====================
Builds a formatted Markdown email body from LLM-processed email results.

USAGE:
    from sources.email.email_report import build_summary_body_md

    body_md = build_summary_body_md(results)
    send_email_to_self(subject="E-Mail Zusammenfassung", body_md=body_md)
"""

import re
from datetime import datetime


def build_summary_body_md(results: list[dict]) -> str:
    """
    Builds a Markdown email body from LLM-processed email results.

    Each email becomes a section with subject, sender, date, and the LLM
    summary. Failed items are shown with an error indicator instead of a
    summary. Skipped items (no readable content) are omitted entirely.

    A summary line at the top shows total / failed counts.

    Args:
        results: List of email dicts. Each dict must have a 'status' key
                 ("ok", "skipped", or "failed"). Failed items additionally
                 need an 'error' dict with 'type' and 'message'.

    Returns:
        Markdown string ready to be passed as body_md to send_email_to_self().
    """
    n_ok = sum(1 for r in results if r.get("status") == "ok")
    n_failed = sum(1 for r in results if r.get("status") == "failed")

    summary = f"*{n_ok} von {len(results)} E-Mail(s) erfolgreich zusammengefasst"
    if n_failed:
        summary += f" · {n_failed} fehlgeschlagen"
    summary += "*"

    lines = [summary, "", "---", ""]

    for email in results:
        status = email.get("status")
        if status == "skipped":
            continue

        subject = email.get("Subject", "(kein Betreff)")
        sender = email.get("From", "")
        dt = datetime.fromisoformat(email["Date"])
        date_str = dt.strftime("%A, %d.%m.%Y %H:%M")

        meta = f"*{date_str} \u00b7 {sender}*"

        if status == "failed":
            err = email.get("error", {})
            error_msg = f"{err.get('type', 'Error')}: {err.get('message', '')}"
            lines += [
                f"### {subject}",
                meta,
                "",
                f"\u26a0 Fehler: {error_msg}",
                "",
                "---",
                "",
            ]
        else:
            response = email["llm_response"]["response"]
            response = re.sub(r"\n+", " ", response).strip()
            lines += [
                f"### {subject}",
                meta,
                "",
                response,
                "",
                "---",
                "",
            ]

    return "\n".join(lines)
