"""Tests for src/phrases.py — SSM-backed progressive response phrase management."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
os.environ.setdefault("OPENAI_SECRET_ARN", "arn:aws:secretsmanager:eu-west-1:000000000000:secret:test")
os.environ.setdefault("MAX_OUTPUT_TOKENS", "280")
os.environ.setdefault("OPENAI_REQUEST_TIMEOUT", "10")

import src.phrases as phrases_module
from src.phrases import (
    _DEFAULT_CHAT_PHRASES,
    _DEFAULT_QUESTION_PHRASES,
    get_chat_phrases,
    get_question_phrases,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset module-level phrase caches before and after every test."""
    phrases_module._CACHED_QUESTION_PHRASES = None
    phrases_module._CACHED_CHAT_PHRASES = None
    yield
    phrases_module._CACHED_QUESTION_PHRASES = None
    phrases_module._CACHED_CHAT_PHRASES = None


def _ssm_response(value: str) -> dict:
    return {"Parameter": {"Name": "test", "Value": value, "Type": "String"}}


def _client_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ParameterNotFound", "Message": "test"}}, "GetParameter"
    )


# ---------------------------------------------------------------------------
# TestGetQuestionPhrases
# ---------------------------------------------------------------------------

class TestGetQuestionPhrases:
    def test_returns_defaults_when_param_not_configured(self, monkeypatch):
        monkeypatch.delenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", raising=False)
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            result = get_question_phrases()
        mock_ssm.get_parameter.assert_not_called()
        assert result == _DEFAULT_QUESTION_PHRASES

    def test_fetches_from_ssm_when_param_configured(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", "/test/phrases")
        phrases = ["Phrase A.", "Phrase B."]
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.return_value = _ssm_response(json.dumps(phrases))
            result = get_question_phrases()
        assert result == tuple(phrases)

    def test_returns_defaults_on_client_error(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", "/test/phrases")
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.side_effect = _client_error()
            result = get_question_phrases()
        assert result == _DEFAULT_QUESTION_PHRASES

    def test_returns_defaults_on_invalid_json(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", "/test/phrases")
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.return_value = _ssm_response("not valid json {{")
            result = get_question_phrases()
        assert result == _DEFAULT_QUESTION_PHRASES

    def test_returns_defaults_when_ssm_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", "/test/phrases")
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.return_value = _ssm_response("[]")
            result = get_question_phrases()
        assert result == _DEFAULT_QUESTION_PHRASES

    def test_returns_defaults_when_ssm_returns_non_list(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", "/test/phrases")
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.return_value = _ssm_response('"just a string"')
            result = get_question_phrases()
        assert result == _DEFAULT_QUESTION_PHRASES

    def test_caches_result_on_second_call(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", "/test/phrases")
        phrases = ["Cached phrase."]
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.return_value = _ssm_response(json.dumps(phrases))
            get_question_phrases()
            get_question_phrases()
        mock_ssm.get_parameter.assert_called_once()

    def test_result_is_a_tuple(self, monkeypatch):
        monkeypatch.delenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", raising=False)
        result = get_question_phrases()
        assert isinstance(result, tuple)


# ---------------------------------------------------------------------------
# TestGetChatPhrases
# ---------------------------------------------------------------------------

class TestGetChatPhrases:
    def test_returns_defaults_when_param_not_configured(self, monkeypatch):
        monkeypatch.delenv("PROGRESSIVE_CHAT_PHRASES_PARAM", raising=False)
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            result = get_chat_phrases()
        mock_ssm.get_parameter.assert_not_called()
        assert result == _DEFAULT_CHAT_PHRASES

    def test_fetches_from_ssm_when_param_configured(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_CHAT_PHRASES_PARAM", "/test/chat-phrases")
        phrases = ["Chat phrase A.", "Chat phrase B."]
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.return_value = _ssm_response(json.dumps(phrases))
            result = get_chat_phrases()
        assert result == tuple(phrases)

    def test_returns_defaults_on_client_error(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_CHAT_PHRASES_PARAM", "/test/chat-phrases")
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.side_effect = _client_error()
            result = get_chat_phrases()
        assert result == _DEFAULT_CHAT_PHRASES

    def test_caches_result_on_second_call(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_CHAT_PHRASES_PARAM", "/test/chat-phrases")
        phrases = ["Chat cached."]
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.return_value = _ssm_response(json.dumps(phrases))
            get_chat_phrases()
            get_chat_phrases()
        mock_ssm.get_parameter.assert_called_once()

    def test_result_is_a_tuple(self, monkeypatch):
        monkeypatch.delenv("PROGRESSIVE_CHAT_PHRASES_PARAM", raising=False)
        result = get_chat_phrases()
        assert isinstance(result, tuple)

    def test_question_and_chat_caches_are_independent(self, monkeypatch):
        monkeypatch.setenv("PROGRESSIVE_QUESTION_PHRASES_PARAM", "/test/q")
        monkeypatch.setenv("PROGRESSIVE_CHAT_PHRASES_PARAM", "/test/c")
        q_phrases = ["Q only."]
        c_phrases = ["C only."]
        with patch("src.phrases._SSM_CLIENT") as mock_ssm:
            mock_ssm.get_parameter.side_effect = [
                _ssm_response(json.dumps(q_phrases)),
                _ssm_response(json.dumps(c_phrases)),
            ]
            q = get_question_phrases()
            c = get_chat_phrases()
        assert q == ("Q only.",)
        assert c == ("C only.",)
