"""Unit tests for openai_client module (output extraction and payload construction)."""

import pytest
from unittest.mock import MagicMock, patch
from src.openai_client import _extract_output_text


def test_extract_output_text_simple():
    data = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Hello, how can I help?"}
                ],
            }
        ]
    }
    assert _extract_output_text(data) == "Hello, how can I help?"


def test_extract_output_text_multiple_blocks():
    data = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "First part. "},
                    {"type": "output_text", "text": "Second part."},
                ],
            }
        ]
    }
    assert _extract_output_text(data) == "First part. Second part."


def test_extract_output_text_empty_output():
    assert _extract_output_text({"output": []}) == ""


def test_extract_output_text_no_output_key():
    assert _extract_output_text({}) == ""


def test_extract_output_text_ignores_non_message():
    data = {
        "output": [
            {"type": "other", "content": "ignored"},
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Only this."}
                ],
            },
        ]
    }
    assert _extract_output_text(data) == "Only this."


def test_extract_output_text_skips_web_search_call():
    """web_search_call items in the output array must be silently skipped."""
    data = {
        "output": [
            {
                "type": "web_search_call",
                "id": "ws_abc123",
                "status": "completed",
            },
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Search result summary."}
                ],
            },
        ]
    }
    assert _extract_output_text(data) == "Search result summary."


def test_get_completion_includes_tools_when_web_search_enabled():
    """Payload must contain tools key when use_web_search=True."""
    import os
    os.environ["OPENAI_MODEL"] = "gpt-4o-mini"
    os.environ["OPENAI_SECRET_ARN"] = "arn:aws:secretsmanager:eu-west-1:000:secret:test"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Result."}],
            }
        ]
    }

    captured = {}
    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return mock_response

    with patch("src.openai_client._CLIENT") as mock_client, \
         patch("src.openai_client._get_api_key_cached", return_value="sk-test"):
        mock_client.post.side_effect = fake_post
        from src.openai_client import get_completion
        get_completion(
            instructions="test",
            user_input="hello",
            use_web_search=True,
        )

    assert "tools" in captured["payload"]
    assert captured["payload"]["tools"] == [{"type": "web_search_preview"}]


def test_get_completion_excludes_tools_when_web_search_disabled():
    """Payload must not contain tools key when use_web_search=False (default)."""
    import os
    os.environ["OPENAI_MODEL"] = "gpt-4o-mini"
    os.environ["OPENAI_SECRET_ARN"] = "arn:aws:secretsmanager:eu-west-1:000:secret:test"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Result."}],
            }
        ]
    }

    captured = {}
    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return mock_response

    with patch("src.openai_client._CLIENT") as mock_client, \
         patch("src.openai_client._get_api_key_cached", return_value="sk-test"):
        mock_client.post.side_effect = fake_post
        from src.openai_client import get_completion
        get_completion(
            instructions="test",
            user_input="hello",
            use_web_search=False,
        )

    assert "tools" not in captured["payload"]
