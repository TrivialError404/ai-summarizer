"""
Email Sender
============
Sends emails via SMTP. Uses the shared provider registry from
lib.email.providers. The same IMAP_USER / IMAP_PASSWORD environment
variables are reused so no additional configuration is needed for known
providers.

ENVIRONMENT VARIABLES (.env):
    IMAP_USER     = your@email.com
    IMAP_PASSWORD = your-app-password

    For custom / self-hosted servers, additionally set:
    SMTP_HOST     = mail.company.com
    SMTP_PORT     = 587                 (optional, auto-detected otherwise)

USAGE:
    from lib.email.email_sender import send_email, send_easy, send_email_to_self

    # High-level: send to yourself, credentials from .env
    send_email_to_self(subject="Test", body="Hello.")

    # Mid-level: credentials from .env, flexible recipient, Markdown support
    send_easy(subject="Report", to="team@example.com", body_md="# Summary\n\nDone.")

    # Low-level: full control
    send_email(
        username="you@gmail.com",
        password="app-password",
        subject="Test",
        body="Hello.",
        to="recipient@example.com",
        sender="you@gmail.com",
    )

DEPENDENCIES:
    pip install python-dotenv markdown
"""

import logging
import mimetypes
import os
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from typing import Optional

import markdown
from dotenv import load_dotenv

from lib.email.providers import PROVIDERS, detect_provider

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Host resolution
# ──────────────────────────────────────────────

def _resolve_host_port(
    username: str,
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
) -> tuple[str, int]:
    """
    Resolves SMTP host and port.

    Resolution order:
        1. Explicit smtp_host / smtp_port arguments.
        2. Auto-detected provider from the username domain.

    Args:
        username:  Email address used for auto-detection.
        smtp_host: Explicit SMTP hostname (overrides auto-detection).
        smtp_port: Explicit SMTP port (overrides auto-detection).

    Returns:
        Tuple of (host, port).

    Raises:
        ValueError: If the domain is not recognised and smtp_host is not given.
    """
    if smtp_host:
        return smtp_host, smtp_port or 587

    provider = detect_provider(username)
    if provider:
        logger.info(f"Auto-detected SMTP provider '{provider}' from {username!r}.")
        entry = PROVIDERS[provider]["smtp"]
        return entry["host"], smtp_port or entry["port"]

    raise ValueError(
        f"Could not detect SMTP provider for {username!r}. "
        "Set SMTP_HOST (and optionally SMTP_PORT) in your .env file."
    )


# ──────────────────────────────────────────────
# Markdown → HTML conversion
# ──────────────────────────────────────────────

def markdown_to_html_email(content_md: str) -> str:
    """
    Converts a Markdown string to an HTML email body.

    Args:
        content_md: Markdown-formatted text.

    Returns:
        HTML string ready to be used as an email body.
    """
    html_body = markdown.markdown(content_md, extensions=["tables", "fenced_code"])
    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8"></head>\n'
        f"<body>{html_body}</body></html>"
    )


# ──────────────────────────────────────────────
# Core send function
# ──────────────────────────────────────────────

def send_email(
    username: str,
    password: str,
    subject: str,
    body: str,
    to: str,
    sender: str,
    body_type: str = "plain",
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    attachments: Optional[list[str | Path]] = None,
) -> None:
    """
    Sends an email via SMTP.

    Low-level send function – all parameters explicit.
    For convenience wrappers see send_easy() and send_email_to_self().

    Args:
        username:    SMTP login username (usually the sender address).
        password:    Account password or App Password.
        subject:     Email subject line.
        body:        Email body – plain text or HTML string.
        to:          Recipient email address.
        sender:      Sender (From) email address.
        body_type:   MIME subtype: "plain" or "html". Default "plain".
        smtp_host:   Override SMTP hostname (auto-detected from sender domain otherwise).
        smtp_port:   Override SMTP port (auto-detected otherwise).
        attachments: Optional list of file paths to attach.

    Raises:
        ValueError:            If provider cannot be detected and smtp_host is missing.
        FileNotFoundError:     If an attachment path does not exist.
        smtplib.SMTPException: If the server rejects the message.
    """

    host, port = _resolve_host_port(username, smtp_host, smtp_port)

    msg = MIMEMultipart()
    msg["From"]    = sender
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, body_type, "utf-8"))

    for filepath in attachments or []:
        filepath = Path(filepath)
        if not filepath.is_file():
            raise FileNotFoundError(f"Attachment not found: {filepath}")

        mime_type, _ = mimetypes.guess_type(str(filepath))
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)

        with open(filepath, "rb") as f:
            part = MIMEBase(maintype, subtype)
            part.set_payload(f.read())

        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", "attachment", filename=filepath.name,
        )
        msg.attach(part)

    logger.info(f"Sending email '{subject}' to {to} via {host}:{port} ...")

    if port == 465:
        with smtplib.SMTP_SSL(host, port) as smtp:
            smtp.login(username, password)
            smtp.sendmail(sender, to, msg.as_string())
    else:
        with smtplib.SMTP(host, port) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(username, password)
            smtp.sendmail(sender, to, msg.as_string())

    logger.info(f"Email sent successfully. Title: {subject}")


# ──────────────────────────────────────────────
# Environment helpers
# ──────────────────────────────────────────────

def _load_env_credentials() -> tuple[str, str, Optional[str], Optional[int]]:
    """
    Loads SMTP credentials and optional host/port from environment variables.

    Returns:
        Tuple of (username, password, smtp_host, smtp_port).

    Raises:
        ValueError: If IMAP_USER or IMAP_PASSWORD are not set.
    """
    load_dotenv()
    username  = os.environ.get("IMAP_USER")
    password  = os.environ.get("IMAP_PASSWORD")
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")

    if not username or not password:
        raise ValueError(
            "Missing credentials. Set IMAP_USER and IMAP_PASSWORD "
            "in your .env file."
        )

    return username, password, smtp_host, int(smtp_port) if smtp_port else None


# ──────────────────────────────────────────────
# Mid-level convenience function
# ──────────────────────────────────────────────

def send_easy(
    subject: str,
    to: str,
    body: Optional[str] = None,
    body_type: str = "plain",
    body_md: Optional[str] = None,
    attachments: Optional[list[str | Path]] = None,
) -> None:
    """
    Sends an email using credentials from environment variables.

    Mid-level convenience wrapper around send_email(). Reads IMAP_USER
    and IMAP_PASSWORD from .env. Pass either body (plain text or ready
    HTML) or body_md (Markdown, auto-converted to HTML) – not both.

    Args:
        subject:     Email subject line.
        to:          Recipient email address.
        body:        Finished email body (plain text or HTML).
        body_type:   MIME subtype: "plain" or "html". Default "plain".
        body_md:     Markdown body – converted to HTML automatically.
        attachments: Optional list of file paths to attach.

    Raises:
        ValueError:            If both body and body_md are set, or neither.
        smtplib.SMTPException: If the server rejects the message.
    """
    if body and body_md:
        raise ValueError("Pass either body or body_md, not both.")
    if not body and not body_md:
        raise ValueError("Pass either body or body_md.")

    if body_md:
        body = markdown_to_html_email(body_md)
        body_type = "html"

    username, password, smtp_host, smtp_port = _load_env_credentials()

    send_email(
        username=username,
        password=password,
        subject=subject,
        body=body,
        to=to,
        sender=username,
        body_type=body_type,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        attachments=attachments,
    )


# ──────────────────────────────────────────────
# High-level: send to self
# ──────────────────────────────────────────────

def send_email_to_self(
    subject: str,
    body: Optional[str] = None,
    body_type: str = "plain",
    body_md: Optional[str] = None,
    attachments: Optional[list[str | Path]] = None,
) -> None:
    """
    Sends an email to yourself using credentials from environment variables.

    High-level wrapper – both sender and recipient are IMAP_USER.
    Delegates to send_easy() with to=IMAP_USER.

    Args:
        subject:     Email subject line.
        body:        Finished email body (plain text or HTML).
        body_type:   MIME subtype: "plain" or "html". Default "plain".
        body_md:     Markdown body – converted to HTML automatically.
        attachments: Optional list of file paths to attach.

    Raises:
        ValueError:            If IMAP_USER or IMAP_PASSWORD are not set,
                               or if body / body_md usage is invalid.
        smtplib.SMTPException: If the server rejects the message.
    """
    load_dotenv()
    username = os.environ.get("IMAP_USER")
    if not username:
        raise ValueError(
            "Missing IMAP_USER. Set it in your .env file."
        )

    send_easy(
        subject=subject,
        to=username,
        body=body,
        body_type=body_type,
        body_md=body_md,
        attachments=attachments,
    )