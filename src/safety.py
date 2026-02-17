"""Optional content guardrails for family use."""

from __future__ import annotations

from util import logger


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
    Optional post-processing for voice output.
    E.g. strip trailing punctuation that sounds odd.
    """
    if not text:
        return ""
    return text.strip()
