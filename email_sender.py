"""
Email Sender
============
Sends emails via SMTP. Mirrors the provider registry and credential
pattern from email_fetcher.py – the same IMAP_USER / IMAP_PASSWORD
environment variables are reused so no additional configuration is needed
for known providers.

ENVIRONMENT VARIABLES (.env):
    IMAP_USER     = your@email.com      (reused from email_fetcher)
    IMAP_PASSWORD = your-app-password   (reused from email_fetcher)

    For custom / self-hosted servers, additionally set:
    SMTP_HOST     = mail.company.com
    SMTP_PORT     = 587                 (optional, auto-detected otherwise)

USAGE:
    # Simplest – provider and credentials auto-detected
    send_email_default(
        subject="Zusammenfassung",
        body="Hier steht der Text.",
    )

    # Explicit
    send_email(
        username="you@gmail.com",
        password="app-password",
        subject="Zusammenfassung",
        body="Hier steht der Text.",
        to="empfaenger@example.com",   # defaults to username (send to self)
    )

DEPENDENCIES:
    pip install python-dotenv
"""

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Provider registry
# ──────────────────────────────────────────────

SMTP_PROVIDERS: dict[str, dict] = {
    "gmail": {
        "host": "smtp.gmail.com",
        "port": 587,
    },
    "outlook": {
        "host": "smtp.office365.com",
        "port": 587,
    },
    "yahoo": {
        "host": "smtp.mail.yahoo.com",
        "port": 587,
    },
    "icloud": {
        "host": "smtp.mail.me.com",
        "port": 587,
    },
    "gmx": {
        "host": "mail.gmx.com",
        "port": 587,
    },
    "web.de": {
        "host": "smtp.web.de",
        "port": 587,
    },
    "zoho": {
        "host": "smtp.zoho.com",
        "port": 587,
    },
}

# Mirrors DOMAIN_TO_PROVIDER from email_fetcher.py
DOMAIN_TO_PROVIDER: dict[str, str] = {
    "gmail.com":      "gmail",
    "googlemail.com": "gmail",
    "outlook.com":    "outlook",
    "hotmail.com":    "outlook",
    "hotmail.de":     "outlook",
    "hotmail.co.uk":  "outlook",
    "live.com":       "outlook",
    "live.de":        "outlook",
    "msn.com":        "outlook",
    "yahoo.com":      "yahoo",
    "yahoo.de":       "yahoo",
    "yahoo.co.uk":    "yahoo",
    "ymail.com":      "yahoo",
    "icloud.com":     "icloud",
    "me.com":         "icloud",
    "mac.com":        "icloud",
    "gmx.com":        "gmx",
    "gmx.de":         "gmx",
    "gmx.net":        "gmx",
    "gmx.at":         "gmx",
    "gmx.ch":         "gmx",
    "web.de":         "web.de",
    "zoho.com":       "zoho",
    "zohomail.com":   "zoho",
}


def _detect_provider(username: str) -> Optional[str]:
    """Returns the provider key for a given email address, or None."""
    if "@" not in username:
        return None
    domain = username.split("@")[-1].lower()
    return DOMAIN_TO_PROVIDER.get(domain)


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

    provider = _detect_provider(username)
    if provider:
        logger.info(f"Auto-detected SMTP provider '{provider}' from {username!r}.")
        entry = SMTP_PROVIDERS[provider]
        return entry["host"], smtp_port or entry["port"]

    raise ValueError(
        f"Could not detect SMTP provider for {username!r}. "
        "Set SMTP_HOST (and optionally SMTP_PORT) in your .env file."
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
) -> None:
    """
    Sends an email via SMTP.

    Generic send function – explicit sender and recipient required.
    For sending to yourself using credentials from .env, use send_email_to_self().

    Args:
        username:  SMTP login username (usually the sender address).
        password:  Account password or App Password.
        subject:   Email subject line.
        body:      Email body – plain text or HTML string.
        to:        Recipient email address.
        sender:    Sender (From) email address.
        body_type: MIME subtype: "plain" or "html". Default "plain".
        smtp_host: Override SMTP hostname (auto-detected from sender domain otherwise).
        smtp_port: Override SMTP port (auto-detected otherwise).

    Raises:
        ValueError:            If provider cannot be detected and smtp_host is missing.
        smtplib.SMTPException: If the server rejects the message.
    """

    host, port = _resolve_host_port(username, smtp_host, smtp_port)

    msg = MIMEMultipart()
    msg["From"]    = sender
    msg["To"]      = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, body_type, "utf-8"))

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


def send_email_to_self(
    subject: str,
    body: str,
    body_type: str = "plain",
) -> None:
    """
    Sends an email to yourself using credentials from environment variables.

    Reads IMAP_USER and IMAP_PASSWORD from the .env file – the same
    variables used by email_fetcher.py, so no additional configuration
    is needed for known providers. Both sender and recipient are set to
    IMAP_USER. SMTP host and port are auto-detected from the email domain;
    for custom domains set SMTP_HOST and SMTP_PORT in .env.

    Args:
        subject:   Email subject line.
        body:      Email body – plain text or HTML string.
        body_type: MIME subtype: "plain" or "html". Default "plain".

    Raises:
        ValueError:            If IMAP_USER or IMAP_PASSWORD are not set,
                               or if the provider cannot be detected.
        smtplib.SMTPException: If the server rejects the message.
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

    send_email(
        username=username,
        password=password,
        subject=subject,
        body=body,
        to=username,
        sender=username,
        smtp_host=smtp_host,
        smtp_port=int(smtp_port) if smtp_port else None,
        body_type=body_type,
    )

# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    send_email_to_self(
        subject="Test",
        body="Das ist eine Testmail vom Email Sender.",
    )