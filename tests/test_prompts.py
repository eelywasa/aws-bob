"""Unit tests for prompts module."""

import pytest
from src.prompts import AUDIENCE_CHILD, AUDIENCE_DEFAULT, build_system_prompt


def test_build_system_prompt_default():
    prompt = build_system_prompt(AUDIENCE_DEFAULT)
    assert "Bob" in prompt
    assert "voice" in prompt.lower()
    assert "concise" in prompt.lower()


def test_build_system_prompt_child():
    prompt = build_system_prompt(AUDIENCE_CHILD)
    assert "Bob" in prompt
    assert "Child mode" in prompt or "child" in prompt.lower()


def test_prompt_voice_optimised():
    prompt = build_system_prompt()
    assert "markdown" in prompt.lower() or "spoken" in prompt.lower()
