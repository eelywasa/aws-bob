"""Shared utilities and helpers."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

# Structured logging: no raw transcripts; suitable for CloudWatch
logger = logging.getLogger(__name__)


def get_env(key: str, default: str | None = None) -> str:
    """Get required or optional env var."""
    value = os.environ.get(key)
    if value is not None:
        return value
    if default is not None:
        return default
    raise ValueError(f"Missing required environment variable: {key}")


def safe_get(obj: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get nested dict value."""
    for key in keys:
        if obj is None or not isinstance(obj, dict):
            return default
        obj = obj.get(key)
    return obj if obj is not None else default


def truncate_for_log(s: str, max_len: int = 80) -> str:
    """Truncate string for safe logging (no raw transcript leakage)."""
    if not s or len(s) <= max_len:
        return s
    return s[:max_len] + "..."


def log_intent(handler_input: Any, extra: dict[str, Any] | None = None) -> None:
    """Log intent invocation without sensitive user data."""
    request = handler_input.request_envelope.request
    intent_name = getattr(request, "intent", None)
    name = getattr(intent_name, "name", None) if intent_name else None
    payload: dict[str, Any] = {"intent": name or str(type(request).__name__)}
    if extra:
        payload.update(extra)
    logger.info("Intent invoked", extra={"structured": payload})
