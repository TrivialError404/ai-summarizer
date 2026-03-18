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

    Each email becomes a section with a linked subject line (Gmail deep-link
    via Message-ID), sender, date, and the LLM summary. Consecutive newlines
    in the LLM response are collapsed to a single space.

    Args:
        results: List of email dicts with at least 'Subject', 'From', 'Date',
                 'Message-ID', and 'llm_response' keys. Entries without an
                 'llm_response' are skipped.

    Returns:
        Markdown string ready to be passed as body_md to send_email_to_self().
    """
    lines = []

    for email in results:
        if not email.get("llm_response"):
            continue

        subject = email.get("Subject", "(kein Betreff)")
        sender = email.get("From", "")
        dt = datetime.fromisoformat(email["Date"])
        date_str = dt.strftime("%A, %d.%m.%Y %H:%M")

        response = email["llm_response"]["response"]
        response = re.sub(r"\n+", " ", response).strip()

        # Gmail deep-link: opens the original email directly in Gmail
        message_id = email.get("Message-ID", "").strip("<>")
        if message_id:
            subject_line = f"### [{subject}](https://mail.google.com/mail/#search/rfc822msgid:{message_id})"
        else:
            subject_line = f"### {subject}"

        lines += [
            subject_line,
            f"*{date_str} \u00b7 {sender}*",
            "",
            response,
            "",
            "---",
            "",
        ]

    return "\n".join(lines)
