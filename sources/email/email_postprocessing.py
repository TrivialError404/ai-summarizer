"""
Email Markdown Postprocessing
=============================
Source-specific Markdown cleanup for email content.
Applied after the generic html_to_markdown() conversion.
"""

import re


def md_postprocess_remove_reply(md: str) -> str:
    """
    Removes quoted reply blocks starting with "Von:" or "From:" followed
    by an email address.

    Args:
        md: Markdown string from an email body.

    Returns:
        Markdown string with the reply block removed.
    """
    md = re.sub(
        r"\n+(?:\*\*)?(?:Von|From):(?:\*\*)?.*?[\w.+-]+@[\w.-]+.*$[\s\S]*",
        "",
        md,
        flags=re.MULTILINE,
    )
    return md
