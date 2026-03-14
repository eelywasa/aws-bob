"""Progressive response phrase management — SSM-backed with module-level caching."""

from __future__ import annotations

import json
import os

import boto3
from botocore.exceptions import ClientError

from .util import logger

# Fallback defaults — used when SSM is unavailable or not configured
_DEFAULT_QUESTION_PHRASES: tuple[str, ...] = (
    "Let me think about that.",
    "Good question, let me think.",
    "Let me find out.",
    "One moment.",
)

_DEFAULT_CHAT_PHRASES: tuple[str, ...] = (
    "Let me think about that.",
    "Hmm, let me think.",
)

# Module-level cache — populated on first call per Lambda container
_CACHED_QUESTION_PHRASES: tuple[str, ...] | None = None
_CACHED_CHAT_PHRASES: tuple[str, ...] | None = None

_SSM_CLIENT = boto3.client("ssm")


def _fetch_phrases(param_name: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Fetch a JSON phrase list from SSM Parameter Store. Returns fallback on any failure."""
    if not param_name:
        return fallback
    try:
        resp = _SSM_CLIENT.get_parameter(Name=param_name)
        raw = resp["Parameter"]["Value"]
        phrases = json.loads(raw)
        if isinstance(phrases, list) and phrases and all(isinstance(p, str) for p in phrases):
            return tuple(phrases)
        logger.warning(
            "phrases: SSM value is not a non-empty list of strings",
            extra={"structured": {"param": param_name}},
        )
        return fallback
    except Exception as exc:
        logger.warning(
            "phrases: SSM fetch failed, using defaults",
            extra={"structured": {"param": param_name, "error": type(exc).__name__}},
        )
        return fallback


def get_question_phrases() -> tuple[str, ...]:
    """Return question phrases. Fetches from SSM on first call per Lambda container."""
    global _CACHED_QUESTION_PHRASES
    if _CACHED_QUESTION_PHRASES is None:
        _CACHED_QUESTION_PHRASES = _fetch_phrases(
            os.environ.get("PROGRESSIVE_QUESTION_PHRASES_PARAM", ""),
            _DEFAULT_QUESTION_PHRASES,
        )
    return _CACHED_QUESTION_PHRASES


def get_chat_phrases() -> tuple[str, ...]:
    """Return chat phrases. Fetches from SSM on first call per Lambda container."""
    global _CACHED_CHAT_PHRASES
    if _CACHED_CHAT_PHRASES is None:
        _CACHED_CHAT_PHRASES = _fetch_phrases(
            os.environ.get("PROGRESSIVE_CHAT_PHRASES_PARAM", ""),
            _DEFAULT_CHAT_PHRASES,
        )
    return _CACHED_CHAT_PHRASES
