"""Unit tests for prompts module."""

import pytest
from src.prompts import AUDIENCE_CHILD, AUDIENCE_DEFAULT, MODE_EDUCATIONAL, build_system_prompt


def test_build_system_prompt_default():
    prompt = build_system_prompt(AUDIENCE_DEFAULT)
    assert "Bob" in prompt
    assert "voice" in prompt.lower()
    assert "concise" in prompt.lower()


def test_build_system_prompt_child():
    prompt = build_system_prompt(AUDIENCE_CHILD)
    assert "Bob" in prompt
    assert "Child mode" in prompt or "child" in prompt.lower()


def test_build_system_prompt_educational():
    prompt = build_system_prompt(MODE_EDUCATIONAL)
    assert "Bob" in prompt
    assert "Educational mode" in prompt or "educational" in prompt.lower()
    assert "deeper" in prompt.lower() or "analogies" in prompt.lower()


def test_prompt_voice_optimised():
    prompt = build_system_prompt()
    assert "markdown" in prompt.lower() or "spoken" in prompt.lower()


def test_web_search_prompt_differs_from_standard():
    standard = build_system_prompt("general", web_search=False)
    web = build_system_prompt("general", web_search=True)
    assert web != standard


def test_web_search_prompt_contains_voice_rules():
    prompt = build_system_prompt("general", web_search=True)
    assert "url" in prompt.lower() or "markdown" in prompt.lower()
    assert "source" in prompt.lower() or "reference" in prompt.lower()


def test_web_search_prompt_works_with_all_modes():
    for mode in ("general", "child", "educational"):
        prompt = build_system_prompt(mode, web_search=True)
        assert "url" in prompt.lower() or "markdown" in prompt.lower()


def test_standard_prompt_unchanged_without_web_search():
    without = build_system_prompt("general", web_search=False)
    assert "raw url" not in without.lower()
    assert "citation marker" not in without.lower()
