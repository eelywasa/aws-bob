"""Tests for src/memory.py — DynamoDB-backed cross-session turn persistence."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
os.environ.setdefault("OPENAI_SECRET_ARN", "arn:aws:secretsmanager:eu-west-1:000000000000:secret:test")
os.environ.setdefault("MAX_OUTPUT_TOKENS", "280")
os.environ.setdefault("OPENAI_REQUEST_TIMEOUT", "10")

import src.memory as memory_module
from src.memory import (
    MEMORY_INJECT_TURNS,
    MEMORY_MAX_TURNS,
    build_cross_session_input,
    load_turns,
    save_turns,
)


def _client_error() -> ClientError:
    return ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "test"}}, "GetItem")


# ---------------------------------------------------------------------------
# TestLoadTurns
# ---------------------------------------------------------------------------

class TestLoadTurns:
    def test_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "false")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            result = load_turns("user123")
        mock_ddb.get_item.assert_not_called()
        assert result == []

    def test_missing_table_returns_empty(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.delenv("MEMORY_TABLE", raising=False)
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            result = load_turns("user123")
        mock_ddb.get_item.assert_not_called()
        assert result == []

    def test_item_not_found_returns_empty(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            mock_ddb.get_item.return_value = {}
            result = load_turns("user123")
        assert result == []

    def test_deserialises_ddb_wire_format(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        ddb_response = {
            "Item": {
                "user_id": {"S": "user123"},
                "turns": {
                    "L": [
                        {"M": {"user": {"S": "what is water"}, "assistant": {"S": "Water is H2O."}}},
                        {"M": {"user": {"S": "tell me more"}, "assistant": {"S": "It has two hydrogens."}}},
                    ]
                },
            }
        }
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            mock_ddb.get_item.return_value = ddb_response
            result = load_turns("user123")
        assert len(result) == 2
        assert result[0] == {"user": "what is water", "assistant": "Water is H2O."}
        assert result[1] == {"user": "tell me more", "assistant": "It has two hydrogens."}

    def test_caps_at_inject_turns(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        # Create more turns than MEMORY_INJECT_TURNS
        many_turns = [
            {"M": {"user": {"S": f"q{i}"}, "assistant": {"S": f"a{i}"}}}
            for i in range(MEMORY_INJECT_TURNS + 5)
        ]
        ddb_response = {"Item": {"user_id": {"S": "user123"}, "turns": {"L": many_turns}}}
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            mock_ddb.get_item.return_value = ddb_response
            result = load_turns("user123")
        assert len(result) == MEMORY_INJECT_TURNS

    def test_client_error_returns_empty(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            mock_ddb.get_item.side_effect = _client_error()
            result = load_turns("user123")
        assert result == []


# ---------------------------------------------------------------------------
# TestSaveTurns
# ---------------------------------------------------------------------------

class TestSaveTurns:
    def test_disabled_is_noop(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "false")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            save_turns("user123", [{"user": "q", "assistant": "a"}])
        mock_ddb.put_item.assert_not_called()

    def test_missing_table_is_noop(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.delenv("MEMORY_TABLE", raising=False)
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            save_turns("user123", [{"user": "q", "assistant": "a"}])
        mock_ddb.put_item.assert_not_called()

    def test_put_item_called_with_correct_structure(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        turns = [{"user": "what is gravity", "assistant": "Gravity pulls things."}]
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            save_turns("user123", turns)
        mock_ddb.put_item.assert_called_once()
        call_kwargs = mock_ddb.put_item.call_args[1]
        item = call_kwargs["Item"]
        assert item["user_id"]["S"] == "user123"
        assert len(item["turns"]["L"]) == 1
        assert item["turns"]["L"][0]["M"]["user"]["S"] == "what is gravity"
        assert "updated_at" in item
        assert "ttl_epoch" in item

    def test_caps_at_max_turns(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        many_turns = [{"user": f"q{i}", "assistant": f"a{i}"} for i in range(MEMORY_MAX_TURNS + 5)]
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            save_turns("user123", many_turns)
        call_kwargs = mock_ddb.put_item.call_args[1]
        saved = call_kwargs["Item"]["turns"]["L"]
        assert len(saved) == MEMORY_MAX_TURNS

    def test_client_error_does_not_propagate(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "true")
        monkeypatch.setenv("MEMORY_TABLE", "test-table")
        with patch("src.memory._DDB_CLIENT") as mock_ddb:
            mock_ddb.put_item.side_effect = _client_error()
            # Must not raise
            save_turns("user123", [{"user": "q", "assistant": "a"}])


# ---------------------------------------------------------------------------
# TestBuildCrossSessionInput
# ---------------------------------------------------------------------------

class TestBuildCrossSessionInput:
    def test_empty_list_returns_empty(self):
        assert build_cross_session_input([]) == []

    def test_single_turn_produces_two_items(self):
        turns = [{"user": "what is water", "assistant": "Water is H2O."}]
        result = build_cross_session_input(turns)
        assert result == [
            {"role": "user", "content": "what is water"},
            {"role": "assistant", "content": "Water is H2O."},
        ]

    def test_multiple_turns_preserve_order(self):
        turns = [
            {"user": "q1", "assistant": "a1"},
            {"user": "q2", "assistant": "a2"},
        ]
        result = build_cross_session_input(turns)
        assert len(result) == 4
        assert result[0] == {"role": "user", "content": "q1"}
        assert result[1] == {"role": "assistant", "content": "a1"}
        assert result[2] == {"role": "user", "content": "q2"}
        assert result[3] == {"role": "assistant", "content": "a2"}
