"""Unit tests for openai_client module (output extraction only)."""

import pytest
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
