"""Cross-session memory: DynamoDB-backed turn and mode persistence for Brainy Bob."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .util import logger

MEMORY_MAX_TURNS = 20
MEMORY_INJECT_TURNS = 10
TTL_DAYS = 90

# Module-level client — mirrors _SM_CLIENT pattern in openai_client.py
_DDB_CLIENT = boto3.client("dynamodb")


def _is_enabled() -> bool:
    return os.environ.get("ENABLE_MEMORY", "true").lower() == "true"


def _table_name() -> str | None:
    return os.environ.get("MEMORY_TABLE") or None


def load_user_data(user_id: str) -> tuple[list[dict], str]:
    """
    Single GetItem → (turns, mode). Returns ([], 'general') on any failure.
    Turns are capped to last MEMORY_INJECT_TURNS. Mode defaults to 'general'
    if absent or unrecognised.
    """
    if not _is_enabled() or not _table_name():
        return [], "general"
    try:
        result = _DDB_CLIENT.get_item(
            TableName=_table_name(),
            Key={"user_id": {"S": user_id}},
        )
        item = result.get("Item")
        if not item:
            return [], "general"

        raw_turns = item.get("turns", {}).get("L", [])
        turns: list[dict] = []
        for entry in raw_turns:
            m = entry.get("M", {})
            turns.append({
                "user": m.get("user", {}).get("S", ""),
                "assistant": m.get("assistant", {}).get("S", ""),
            })

        from .prompts import VALID_MODES
        raw_mode = item.get("mode", {}).get("S", "general")
        mode = raw_mode if raw_mode in VALID_MODES else "general"

        return turns[-MEMORY_INJECT_TURNS:], mode
    except Exception as exc:
        logger.warning("memory.load_user_data failed", extra={"structured": {"error": type(exc).__name__}})
        return [], "general"


def save_turns(user_id: str, turns: list[dict], mode: str = "general") -> None:
    """Persist turns and mode together (PutItem), capped at MEMORY_MAX_TURNS. Silent on failure."""
    if not _is_enabled() or not _table_name():
        return
    try:
        capped = turns[-MEMORY_MAX_TURNS:]
        ddb_turns = [
            {"M": {"user": {"S": t.get("user", "")}, "assistant": {"S": t.get("assistant", "")}}}
            for t in capped
        ]
        now = datetime.now(tz=timezone.utc)
        ttl_epoch = int((now + timedelta(days=TTL_DAYS)).timestamp())
        _DDB_CLIENT.put_item(
            TableName=_table_name(),
            Item={
                "user_id": {"S": user_id},
                "turns": {"L": ddb_turns},
                "mode": {"S": mode},
                "updated_at": {"S": now.isoformat()},
                "ttl_epoch": {"N": str(ttl_epoch)},
            },
        )
    except Exception as exc:
        logger.warning("memory.save_turns failed", extra={"structured": {"error": type(exc).__name__}})


def save_mode(user_id: str, mode: str) -> None:
    """UpdateItem — sets only mode/updated_at/ttl_epoch, leaves turns untouched. Silent on failure."""
    if not _is_enabled() or not _table_name():
        return
    try:
        now = datetime.now(tz=timezone.utc)
        ttl_epoch = int((now + timedelta(days=TTL_DAYS)).timestamp())
        _DDB_CLIENT.update_item(
            TableName=_table_name(),
            Key={"user_id": {"S": user_id}},
            UpdateExpression="SET #m = :mode, updated_at = :ts, ttl_epoch = :ttl",
            ExpressionAttributeNames={"#m": "mode"},
            ExpressionAttributeValues={
                ":mode": {"S": mode},
                ":ts": {"S": now.isoformat()},
                ":ttl": {"N": str(ttl_epoch)},
            },
        )
    except Exception as exc:
        logger.warning("memory.save_mode failed", extra={"structured": {"error": type(exc).__name__}})


def build_cross_session_input(turns: list[dict]) -> list[dict[str, Any]]:
    """Convert stored turns to OpenAI input_items format. Pure function, no I/O."""
    if not turns:
        return []
    items: list[dict[str, Any]] = []
    for turn in turns:
        items.append({"role": "user", "content": turn.get("user", "")})
        items.append({"role": "assistant", "content": turn.get("assistant", "")})
    return items
