"""Optional content guardrails for family use."""

from __future__ import annotations
import re

from .util import logger


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
    Post-processing for voice output: strip markdown formatting and URLs.
    Web search responses from OpenAI include headers, bullets, and source
    citations that are meaningless or disruptive when spoken aloud.
    """
    if not text:
        return ""

    # 1. Inline source citations: ([source](url)) or unclosed ([source]( — remove entirely
    text = re.sub(r'\(\[[^\]]*\]\([^\)]*\)\)?', '', text)

    # 2. Markdown links: [display text](url) → display text
    text = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', text)

    # 3. Bold and italic markers: **text** / *text* / _text_ → text
    text = re.sub(r'\*{1,2}([^\*\n]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_([^_\n]+)_', r'\1', text)

    # 4. Markdown headers: ## Heading — strip the whole line
    text = re.sub(r'^#{1,6}\s+.*$', '', text, flags=re.MULTILINE)

    # 5. List markers at line start: strip - / * / 1. but keep the content
    text = re.sub(r'^[\-\*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)

    # 6. Remaining bare URLs
    text = re.sub(r'https?://\S+', '', text, flags=re.IGNORECASE)

    # 7. Collapse multiple newlines to a space, then normalise whitespace
    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r' {2,}', ' ', text)

    return text.strip()
