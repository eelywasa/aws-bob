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


def test_sanitize_output_strips_url():
    assert sanitize_output("More info at https://example.com/some/long/path.") == "More info at"

def test_sanitize_output_strips_url_mid_sentence():
    result = sanitize_output("See https://example.com for details.")
    assert "https://" not in result
    assert "for details." in result

def test_sanitize_output_strips_multiple_urls():
    text = "Visit https://one.com and https://two.com/path?q=1 for more."
    result = sanitize_output(text)
    assert "https://" not in result
    assert "Visit" in result
    assert "for more." in result

def test_sanitize_output_no_double_spaces_after_url_removal():
    result = sanitize_output("Hello https://example.com world")
    assert "  " not in result
