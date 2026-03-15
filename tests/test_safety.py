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


# Markdown stripping (web search responses)

def test_sanitize_strips_markdown_header():
    result = sanitize_output("Good answer.\n## EPL Schedule\nMore text.")
    assert "##" not in result
    assert "EPL Schedule" not in result
    assert "Good answer." in result

def test_sanitize_strips_bullet_markers_keeps_content():
    result = sanitize_output("Results:\n- Arsenal 2-0 Everton\n- City 1-1 West Ham")
    assert "- " not in result
    assert "Arsenal 2-0 Everton" in result
    assert "City 1-1 West Ham" in result

def test_sanitize_strips_numbered_list_markers():
    result = sanitize_output("Steps:\n1. First thing\n2. Second thing")
    assert "1. " not in result
    assert "First thing" in result
    assert "Second thing" in result

def test_sanitize_strips_bold_markers():
    result = sanitize_output("The **quick** brown fox")
    assert "**" not in result
    assert "quick" in result

def test_sanitize_strips_inline_citation_fragment():
    # Simulates ([premierleague.com](https://premierleague.com)) after URL stripping
    result = sanitize_output("Arsenal won. ([premierleague.com](https://premierleague.com))")
    assert "([" not in result
    assert "Arsenal won." in result

def test_sanitize_converts_markdown_link_to_display_text():
    result = sanitize_output("See [Premier League](https://premierleague.com) for details.")
    assert "[" not in result
    assert "Premier League" in result
    assert "premierleague.com" not in result

def test_sanitize_collapses_newlines_to_spaces():
    result = sanitize_output("Line one.\nLine two.\nLine three.")
    assert "\n" not in result
    assert "Line one." in result
    assert "Line two." in result

def test_sanitize_real_web_search_response():
    """Simulate the shape of a real OpenAI web search response."""
    raw = (
        "Arsenal secured a 2-0 victory over Everton. "
        "([premierleague.com](https://premierleague.com))\n\n"
        "## EPL Schedule\n"
        "- Arsenal 2 - Everton 0 on Saturday\n"
        "- City 1 - West Ham 1 on Saturday\n"
    )
    result = sanitize_output(raw)
    assert "##" not in result
    assert "([" not in result
    assert "premierleague.com" not in result
    assert "Arsenal secured" in result
