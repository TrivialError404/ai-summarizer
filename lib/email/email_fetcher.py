"""
IMAP Email Fetcher
==================
Provider-agnostic email fetcher using the IMAP protocol.
Supports any standard IMAP provider (Gmail, Outlook, Yahoo, iCloud, custom).

PREREQUISITES:
    Most providers require an App Password rather than the regular account password:
      - Gmail:   https://myaccount.google.com/apppasswords  (requires 2FA)
      - Outlook: https://account.microsoft.com/security
      - Yahoo:   https://login.yahoo.com/account/security
      - iCloud:  https://appleid.apple.com/account/manage

    Enable IMAP access in your provider's mail settings before use.

ENVIRONMENT VARIABLES (.env):
    IMAP_USER     = your@email.com
    IMAP_PASSWORD = your-app-password

USAGE:
    from lib.email.email_fetcher import fetch_emails

    # Provider is auto-detected from the email address domain
    emails = fetch_emails(
        username="your@gmail.com",
        password="your-app-password",
    )

    # Override manually for custom domains or self-hosted servers
    emails = fetch_emails(
        username="your@company.com",
        password="your-password",
        imap_host="mail.company.com",
    )
"""

import email
import email.header
import email.utils
import imaplib
import logging
import os
from datetime import datetime
from email.policy import default as email_default_policy
from typing import Optional

from dotenv import load_dotenv

from lib.email.providers import PROVIDERS, detect_provider

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _resolve_host_port(
    provider: Optional[str], imap_host: Optional[str], imap_port: int,
    username: Optional[str] = None,
) -> tuple[str, int]:
    """
    Resolves the IMAP host and port, with automatic provider detection as fallback.

    Resolution order:
        1. Explicit provider= argument.
        2. Explicit imap_host= argument.
        3. Auto-detected provider from the username domain.

    Args:
        provider:  Provider key from IMAP_PROVIDERS (e.g. 'gmail', 'outlook').
                   Case-insensitive. Pass None to fall through to imap_host or
                   auto-detection.
        imap_host: Explicit IMAP hostname. Used when provider is None.
        imap_port: Port number used together with imap_host.
        username:  Email address used for auto-detection when provider and
                   imap_host are both None.

    Returns:
        Tuple of (host, port).

    Raises:
        ValueError: If the provider key is unknown, or if the domain cannot be
                    detected and neither provider nor imap_host is given.
    """
    if provider:
        key = provider.lower()
        if key not in PROVIDERS:
            raise ValueError(
                f"Unknown provider '{provider}'. "
                f"Available: {list(PROVIDERS.keys())}. "
                f"For custom servers pass imap_host= directly."
            )
        entry = PROVIDERS[key]["imap"]
        return entry["host"], entry["port"]

    if imap_host:
        return imap_host, imap_port

    if username:
        detected = detect_provider(username)
        if detected:
            logger.info(f"Auto-detected provider '{detected}' from {username!r}.")
            entry = PROVIDERS[detected]["imap"]
            return entry["host"], entry["port"]

    raise ValueError(
        "Could not determine IMAP server. "
        "Pass provider= (e.g. 'gmail') or imap_host= explicitly."
    )


# ──────────────────────────────────────────────
# Connection
# ──────────────────────────────────────────────

def connect(host: str, port: int, username: str, password: str) -> imaplib.IMAP4_SSL:
    """
    Opens an authenticated SSL/TLS IMAP connection.

    Args:
        host:     IMAP server hostname.
        port:     IMAP server port (typically 993 for SSL).
        username: Email address used for login.
        password: Account password or App Password.

    Returns:
        Authenticated IMAP4_SSL connection object.

    Raises:
        imaplib.IMAP4.error: If authentication fails.
        ConnectionError:     If the server is unreachable.
    """
    logger.info(f"Connecting to {host}:{port} as {username} ...")
    try:
        imap = imaplib.IMAP4_SSL(host, port)
        imap.login(username, password)
        logger.info("Login successful.")
        return imap
    except ConnectionRefusedError:
        raise ConnectionError(f"Connection refused by {host}:{port}.")


# ──────────────────────────────────────────────
# Parsing helpers
# ──────────────────────────────────────────────

def _decode_header(raw: str) -> str:
    """Decodes MIME-encoded header values (e.g. =?UTF-8?B?...?=)."""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    result = []
    for fragment, charset in parts:
        if isinstance(fragment, bytes):
            result.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(str(fragment))
    return " ".join(result).strip()


def _extract_body(msg: email.message.Message, content_type: str) -> str:
    """
    Extracts all body parts matching the given MIME type.

    Args:
        msg:          Parsed email message object.
        content_type: MIME type to extract, e.g. 'text/plain' or 'text/html'.

    Returns:
        Concatenated decoded body string.
    """
    parts = []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        if part.get_content_type() == content_type:
            charset = part.get_content_charset() or "utf-8"
            payload = part.get_payload(decode=True)
            if payload:
                parts.append(payload.decode(charset, errors="replace"))
    return "\n".join(parts).strip()


def _parse_message(uid: str, raw: bytes) -> dict:
    """
    Parses a raw RFC822 email into a structured data dict.

    Args:
        uid: IMAP sequence number as string.
        raw: Raw RFC822 email bytes.

    Returns:
        Dict with the following keys:
            uid        (str)              – IMAP sequence number
            Message-ID (str)              – unique email identifier
            From       (str)              – sender address / display name
            To         (str)              – recipient(s)
            Subject    (str)              – decoded subject line
            Date       (datetime | None)  – parsed send date
            text/plain (str)              – plain-text body
            text/html  (str)              – HTML body
    """
    msg = email.message_from_bytes(raw, policy=email_default_policy)
    date_str = msg.get("Date", "")
    date = None
    if date_str:
        try:
            date = email.utils.parsedate_to_datetime(date_str)
        except Exception:
            pass

    return {
        "uid":        uid,
        "Message-ID": msg.get("Message-ID", "").strip(),
        "From":       _decode_header(msg.get("From", "")),
        "To":         _decode_header(msg.get("To", "")),
        "Subject":    _decode_header(msg.get("Subject", "")),
        "Date":       date.isoformat(),
        "text/plain": _extract_body(msg, "text/plain"),
        "text/html":  _extract_body(msg, "text/html"),
    }


# ──────────────────────────────────────────────
# IMAP utilities
# ──────────────────────────────────────────────

def list_folders(
    username: str,
    password: str,
    provider: Optional[str] = None,
    imap_host: Optional[str] = None,
    imap_port: int = 993,
) -> list[str]:
    """
    Lists all folders/labels available in the mailbox.

    Useful for finding the exact folder name to pass to fetch_emails(),
    since names vary by provider (e.g. 'Sent Items' vs '[Gmail]/Sent Mail').

    Args:
        username:  Email address.
        password:  Account or App Password.
        provider:  Provider key, e.g. 'gmail', 'outlook'. See IMAP_PROVIDERS.
        imap_host: Custom IMAP hostname (used instead of provider).
        imap_port: Custom IMAP port (default 993).

    Returns:
        Sorted list of folder name strings.
    """
    host, port = _resolve_host_port(provider, imap_host, imap_port, username)
    imap = connect(host, port, username, password)
    try:
        status, raw_list = imap.list()
        folders = []
        if status == "OK":
            for entry in raw_list:
                decoded = entry.decode("utf-8")
                parts = decoded.split('"/"')
                if parts:
                    name = parts[-1].strip().strip('"')
                    folders.append(name)
        return sorted(folders)
    finally:
        imap.logout()


def get_unread_count(
    username: str,
    password: str,
    folder: str = "INBOX",
    provider: Optional[str] = None,
    imap_host: Optional[str] = None,
    imap_port: int = 993,
) -> int:
    """
    Returns the number of unread emails in the given folder.

    Args:
        username:  Email address.
        password:  Account or App Password.
        folder:    Mailbox folder name.
        provider:  Provider key, e.g. 'gmail', 'outlook'.
        imap_host: Custom IMAP hostname.
        imap_port: Custom IMAP port.

    Returns:
        Integer count of unread messages.
    """
    host, port = _resolve_host_port(provider, imap_host, imap_port, username)
    imap = connect(host, port, username, password)
    try:
        imap.select(f'"{folder}"', readonly=True)
        status, data = imap.search(None, "UNSEEN")
        return len(data[0].split()) if status == "OK" else 0
    finally:
        imap.logout()


def mark_as_read(
    username: str,
    password: str,
    uids: list[str],
    folder: str = "INBOX",
    provider: Optional[str] = None,
    imap_host: Optional[str] = None,
    imap_port: int = 993,
) -> None:
    """
    Marks the specified emails as read (adds the \\Seen flag).

    Args:
        username:  Email address.
        password:  Account or App Password.
        uids:      List of IMAP sequence numbers to mark.
        folder:    Mailbox folder name.
        provider:  Provider key, e.g. 'gmail', 'outlook'.
        imap_host: Custom IMAP hostname.
        imap_port: Custom IMAP port.
    """
    host, port = _resolve_host_port(provider, imap_host, imap_port, username)
    imap = connect(host, port, username, password)
    try:
        imap.select(f'"{folder}"', readonly=False)
        imap.store(",".join(uids), "+FLAGS", "\\Seen")
        logger.info(f"Marked {len(uids)} email(s) as read.")
    finally:
        imap.logout()


def mark_as_unread(
    username: str,
    password: str,
    uids: list[str],
    folder: str = "INBOX",
    provider: Optional[str] = None,
    imap_host: Optional[str] = None,
    imap_port: int = 993,
) -> None:
    """
    Marks the specified emails as unread (removes the \\Seen flag).

    Args:
        username:  Email address.
        password:  Account or App Password.
        uids:      List of IMAP sequence numbers to mark.
        folder:    Mailbox folder name.
        provider:  Provider key, e.g. 'gmail', 'outlook'.
        imap_host: Custom IMAP hostname.
        imap_port: Custom IMAP port.
    """
    host, port = _resolve_host_port(provider, imap_host, imap_port, username)
    imap = connect(host, port, username, password)
    try:
        imap.select(f'"{folder}"', readonly=False)
        imap.store(",".join(uids), "-FLAGS", "\\Seen")
        logger.info(f"Marked {len(uids)} email(s) as unread.")
    finally:
        imap.logout()


# ──────────────────────────────────────────────
# Main fetch function
# ──────────────────────────────────────────────

def fetch_emails(
    username: str,
    password: str,
    provider: Optional[str] = None,
    imap_host: Optional[str] = None,
    imap_port: int = 993,
    folder: str = "INBOX",
    unread: Optional[bool] = True,
    max_emails: Optional[int] = None,
) -> list[dict]:
    """
    Fetches emails from any IMAP-compatible mailbox.

    Args:
        username:  Email address used for login.
        password:  Account password or App Password.
        provider:  Provider shorthand from the built-in registry:
                   'gmail', 'outlook', 'yahoo', 'icloud', 'gmx', 'web.de', 'zoho'.
                   Pass None to specify imap_host manually.
        imap_host: Custom IMAP server hostname. Used when provider is None.
        imap_port: Custom IMAP port (default 993). Used when provider is None.
        folder:    Mailbox folder to read from (default 'INBOX').
                   Use list_folders() to find exact names for your provider.
        unread:    Filter by read status:
                     True  → unread only (default)
                     False → read only
                     None  → all emails
        max_emails: Maximum number of emails to return, newest first.

    Returns:
        List of email data dicts, each containing:
            uid        (str)              – IMAP sequence number
            Message-ID (str)              – unique email identifier
            From       (str)              – sender
            To         (str)              – recipient(s)
            Subject    (str)              – subject line
            Date       (datetime | None)  – send date
            text/plain (str)              – plain-text body
            text/html  (str)              – HTML body

    Raises:
        ValueError:          If provider is unknown or neither provider nor
                             imap_host is given. Also if folder is not found.
        imaplib.IMAP4.error: On authentication failure.
        ConnectionError:     If the IMAP server is unreachable.

    Examples:
        # Provider auto-detected from email domain
        fetch_emails("you@gmail.com",   "app-pw")
        fetch_emails("you@outlook.com", "app-pw", unread=None)

        # Explicit provider override
        fetch_emails("you@gmail.com", "app-pw", provider="gmail")

        # Custom domain / self-hosted (auto-detection not possible)
        fetch_emails("you@company.com", "pw", imap_host="mail.company.com")
    """
    criterion = {True: "UNSEEN", False: "SEEN", None: "ALL"}[unread]
    host, port = _resolve_host_port(provider, imap_host, imap_port, username)

    results = []
    imap = None
    try:
        imap = connect(host, port, username, password)

        # Select folder
        status, _ = imap.select(f'"{folder}"', readonly=True)
        if status != "OK":
            available = list_folders(username, password, provider, imap_host, imap_port)
            raise ValueError(
                f"Folder '{folder}' not found. Available folders: {available}"
            )

        # Search emails in folder
        status, message_numbers = imap.search(None, criterion)
        if status != "OK":
            logger.warning("Email search failed.")
            return []

        all_ids = message_numbers[0].split()[::-1] # reverse (last email first)
        if max_emails:
            all_ids = all_ids[0:max_emails]
        logger.info(f"Found {len(all_ids)} email(s) matching '{criterion}'.")

        # Loop over each email and extract data
        for msg_id in all_ids:
            try:
                status, msg_data = imap.fetch(msg_id, "(RFC822)")
                if status != "OK" or not msg_data or not msg_data[0]:
                    logger.warning(f"Could not fetch email {msg_id}.")
                    continue
                entry = _parse_message(msg_id.decode("utf-8"), msg_data[0][1])
                results.append(entry)
                logger.info(f"  ✓ [{entry['uid']}] {entry['Subject'][:70]!r}")
            except Exception as exc:
                logger.error(f"Error processing email {msg_id}: {exc}")

    except imaplib.IMAP4.error:
        logger.error("IMAP authentication error – check username and password.")
        raise
    finally:
        if imap:
            try:
                imap.logout()
            except Exception:
                pass

    logger.info(f"Done. Fetched {len(results)} email(s).")
    return results


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────


def get_emails_default(folder: str = "INBOX", unread: bool = True, max_emails: Optional[int] = None):
    """
    Minimal email IMAP call with default params to fetch unread emails from given folder

    Args:
        folder: Mailbox folder to read from (default 'INBOX').

    Returns:
        List of email data dicts
    """
    # Load email username and passwort from .env
    load_dotenv()
    USER     = os.environ.get("IMAP_USER")
    PASSWORD = os.environ.get("IMAP_PASSWORD")

    emails = fetch_emails(
        username=USER,
        password=PASSWORD,
        folder=folder,
        unread=unread,
        max_emails=max_emails,
    )

    return emails


