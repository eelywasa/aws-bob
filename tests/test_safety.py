"""Unit tests for safety module."""

import pytest
from src.safety import check_input, sanitize_output


def test_check_input_allows_normal_utterance():
    allowed, reason = check_input("What is the capital of France?")
    assert allowed is True
    assert reason is None


def test_check_input_rejects_empty():
    allowed, reason = check_input("")
    assert allowed is False
    assert reason == "empty_input"


def test_check_input_rejects_whitespace():
    allowed, reason = check_input("   ")
    assert allowed is False


def test_sanitize_output_passthrough():
    assert sanitize_output("Hello world") == "Hello world"


def test_sanitize_output_strips():
    assert sanitize_output("  Hello  ") == "Hello"


def test_sanitize_output_empty():
    assert sanitize_output("") == ""
