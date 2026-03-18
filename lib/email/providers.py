"""
Email Provider Registry
=======================
Single source of truth for IMAP and SMTP server configuration.
Used by both email_fetcher and email_sender.

Add new providers here – both modules pick them up automatically.
"""

from typing import Optional


# ──────────────────────────────────────────────
# Provider registry
# ──────────────────────────────────────────────

PROVIDERS: dict[str, dict] = {
    "gmail": {
        "imap": {"host": "imap.gmail.com",       "port": 993},
        "smtp": {"host": "smtp.gmail.com",        "port": 587},
    },
    "outlook": {
        "imap": {"host": "outlook.office365.com", "port": 993},
        "smtp": {"host": "smtp.office365.com",    "port": 587},
    },
    "yahoo": {
        "imap": {"host": "imap.mail.yahoo.com",   "port": 993},
        "smtp": {"host": "smtp.mail.yahoo.com",   "port": 587},
    },
    "icloud": {
        "imap": {"host": "imap.mail.me.com",      "port": 993},
        "smtp": {"host": "smtp.mail.me.com",      "port": 587},
    },
    "gmx": {
        "imap": {"host": "imap.gmx.com",          "port": 993},
        "smtp": {"host": "mail.gmx.com",          "port": 587},
    },
    "web.de": {
        "imap": {"host": "imap.web.de",           "port": 993},
        "smtp": {"host": "smtp.web.de",           "port": 587},
    },
    "zoho": {
        "imap": {"host": "imap.zoho.com",         "port": 993},
        "smtp": {"host": "smtp.zoho.com",         "port": 587},
    },
}


# Maps email address domains to provider keys.
DOMAIN_TO_PROVIDER: dict[str, str] = {
    # Gmail
    "gmail.com":       "gmail",
    "googlemail.com":  "gmail",
    # Outlook / Microsoft
    "outlook.com":     "outlook",
    "hotmail.com":     "outlook",
    "hotmail.de":      "outlook",
    "hotmail.co.uk":   "outlook",
    "live.com":        "outlook",
    "live.de":         "outlook",
    "msn.com":         "outlook",
    # Yahoo
    "yahoo.com":       "yahoo",
    "yahoo.de":        "yahoo",
    "yahoo.co.uk":     "yahoo",
    "ymail.com":       "yahoo",
    # iCloud / Apple
    "icloud.com":      "icloud",
    "me.com":          "icloud",
    "mac.com":         "icloud",
    # GMX
    "gmx.com":         "gmx",
    "gmx.de":          "gmx",
    "gmx.net":         "gmx",
    "gmx.at":          "gmx",
    "gmx.ch":          "gmx",
    # web.de
    "web.de":          "web.de",
    # Zoho
    "zoho.com":        "zoho",
    "zohomail.com":    "zoho",
}


def detect_provider(username: str) -> Optional[str]:
    """
    Detects the email provider from an email address domain.

    Args:
        username: Email address (e.g. 'you@gmail.com').

    Returns:
        Provider key string (e.g. 'gmail') if recognised, None otherwise.
    """
    if "@" not in username:
        return None
    domain = username.split("@")[-1].lower()
    return DOMAIN_TO_PROVIDER.get(domain)
