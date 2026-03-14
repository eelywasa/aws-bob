"""Optional content guardrails for family use."""

from __future__ import annotations
import re

from .util import logger

# Matches http/https URLs including any trailing punctuation
_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)


def check_input(utterance: str) -> tuple[bool, str | None]:
    """
    Optional guardrail: reject obviously inappropriate input.
    Returns (allowed, rejection_reason).
    """
    if not utterance or not utterance.strip():
        return False, "empty_input"
    # Extensible: add age-appropriate filters, blocklists, etc.
    return True, None


def sanitize_output(text: str) -> str:
    """
    Post-processing for voice output: strip URLs and normalise whitespace.
    URLs are meaningless when spoken aloud and can be very long.
    """
    if not text:
        return ""
    text = _URL_RE.sub("", text)
    # Collapse any double spaces left behind after URL removal
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()
