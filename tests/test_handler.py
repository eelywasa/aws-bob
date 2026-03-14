"""
Tests for handler.py — intent routing, session management, and regression tests.

Tests invoke lambda_handler with Alexa-formatted event dicts to verify the full
request → handler → response pipeline without calling real AWS or OpenAI services.

Response structure:
  response["response"]["outputSpeech"]["ssml"]  — spoken text (wrapped in <speak>)
  response["response"].get("reprompt")          — presence means mic stays open
  response["response"].get("shouldEndSession")  — True means session terminates
  response["response"].get("directives")        — dialog directives (ElicitSlot)
  response["sessionAttributes"]                 — persisted session state
"""

import os
from unittest.mock import patch

import pytest

# Set required env vars before importing handler (avoids get_env() errors at call time)
os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
os.environ.setdefault("OPENAI_SECRET_ARN", "arn:aws:secretsmanager:eu-west-1:000000000000:secret:test")
os.environ.setdefault("MAX_OUTPUT_TOKENS", "280")
os.environ.setdefault("OPENAI_REQUEST_TIMEOUT", "10")

from src.handler import lambda_handler  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ssml_text(response: dict) -> str:
    """Extract the spoken text from the SSML output speech."""
    ssml = response["response"]["outputSpeech"]["ssml"]
    # Strip <speak>…</speak> wrapper
    return ssml.replace("<speak>", "").replace("</speak>", "").strip()


def _has_reprompt(response: dict) -> bool:
    return bool(response["response"].get("reprompt"))


def _should_end(response: dict) -> bool:
    """Returns True only if shouldEndSession is explicitly True."""
    return response["response"].get("shouldEndSession") is True


def _has_elicit_directive(response: dict) -> bool:
    directives = response["response"].get("directives", [])
    return any(d.get("type") == "Dialog.ElicitSlot" for d in directives)


def _make_event(request: dict, session_attrs: dict | None = None) -> dict:
    """Build a minimal but valid Alexa request envelope."""
    return {
        "version": "1.0",
        "session": {
            "new": session_attrs is None,
            "sessionId": "amzn1.echo-api.session.test",
            "application": {"applicationId": "amzn1.ask.skill.test"},
            "attributes": session_attrs or {},
            "user": {"userId": "amzn1.ask.account.test"},
        },
        "context": {
            "System": {
                "application": {"applicationId": "amzn1.ask.skill.test"},
                "user": {"userId": "amzn1.ask.account.test"},
                "device": {
                    "deviceId": "amzn1.ask.device.test",
                    "supportedInterfaces": {},
                },
            }
        },
        "request": request,
    }


def _launch_event() -> dict:
    return _make_event({
        "type": "LaunchRequest",
        "requestId": "amzn1.echo-api.request.launch",
        "locale": "en-GB",
        "timestamp": "2024-01-01T00:00:00Z",
    })


def _intent_event(
    intent_name: str,
    slots: dict | None = None,
    session_attrs: dict | None = None,
) -> dict:
    intent = {
        "name": intent_name,
        "confirmationStatus": "NONE",
        "slots": {
            name: {"name": name, "value": value, "confirmationStatus": "NONE"}
            for name, value in (slots or {}).items()
        },
    }
    return _make_event(
        {
            "type": "IntentRequest",
            "requestId": "amzn1.echo-api.request.intent",
            "locale": "en-GB",
            "timestamp": "2024-01-01T00:00:00Z",
            "dialogState": "IN_PROGRESS",
            "intent": intent,
        },
        session_attrs=session_attrs,
    )


def _session_ended_event() -> dict:
    return _make_event({
        "type": "SessionEndedRequest",
        "requestId": "amzn1.echo-api.request.ended",
        "locale": "en-GB",
        "timestamp": "2024-01-01T00:00:00Z",
        "reason": "USER_INITIATED",
    })


# ---------------------------------------------------------------------------
# LaunchRequest
# ---------------------------------------------------------------------------

class TestLaunchRequest:
    def test_greets_user(self):
        response = lambda_handler(_launch_event(), {})
        speech = _ssml_text(response)
        assert "bob" in speech.lower()

    def test_keeps_session_open(self):
        response = lambda_handler(_launch_event(), {})
        assert not _should_end(response)
        assert _has_reprompt(response)

    def test_adds_elicit_directive(self):
        response = lambda_handler(_launch_event(), {})
        assert _has_elicit_directive(response)

    def test_initialises_session_attributes(self):
        response = lambda_handler(_launch_event(), {})
        attrs = response["sessionAttributes"]
        assert attrs.get("history") == []
        assert attrs.get("mode") == "general"


# ---------------------------------------------------------------------------
# ChatIntent
# ---------------------------------------------------------------------------

class TestChatIntent:
    def test_calls_openai_with_utterance(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.handler.get_completion", return_value="Gravity is a force.") as mock_ai:
            lambda_handler(event, {})
        mock_ai.assert_called_once()
        call_kwargs = mock_ai.call_args.kwargs
        assert any(
            "gravity" in str(item).lower()
            for item in (call_kwargs.get("user_input") or [])
        )

    def test_speaks_openai_response(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.handler.get_completion", return_value="Gravity is a force."):
            response = lambda_handler(event, {})
        assert "Gravity is a force." in _ssml_text(response)

    def test_keeps_mic_open(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.handler.get_completion", return_value="Gravity pulls things down."):
            response = lambda_handler(event, {})
        assert not _should_end(response)
        assert _has_reprompt(response)
        assert _has_elicit_directive(response)

    def test_stores_turn_in_history(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.handler.get_completion", return_value="Gravity pulls things down."):
            response = lambda_handler(event, {})
        history = response["sessionAttributes"].get("history", [])
        assert len(history) == 1
        assert history[0]["user"] == "what is gravity"
        assert history[0]["assistant"] == "Gravity pulls things down."

    def test_stores_last_answer(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.handler.get_completion", return_value="Gravity pulls things down."):
            response = lambda_handler(event, {})
        assert response["sessionAttributes"].get("last_answer") == "Gravity pulls things down."

    def test_empty_slot_reprompts_without_openai(self):
        event = _intent_event("ChatIntent", slots={"utterance": ""})
        with patch("src.handler.get_completion") as mock_ai:
            response = lambda_handler(event, {})
        mock_ai.assert_not_called()
        assert _has_reprompt(response)
        assert not _should_end(response)

    def test_history_carries_over_between_turns(self):
        prior_history = [{"user": "what is water", "assistant": "Water is H2O."}]
        event = _intent_event(
            "ChatIntent",
            slots={"utterance": "tell me more"},
            session_attrs={"history": prior_history, "mode": "general"},
        )
        captured = {}
        def capture_call(**kwargs):
            captured["user_input"] = kwargs.get("user_input")
            return "Water has two hydrogens and one oxygen."

        with patch("src.handler.get_completion", side_effect=capture_call):
            lambda_handler(event, {})

        # Prior assistant turn should be included in the prompt context
        assert any("H2O" in str(item) for item in captured["user_input"])

    def test_history_capped_at_max_turns(self):
        # Fill history beyond MAX_TURNS (4)
        prior_history = [
            {"user": f"question {i}", "assistant": f"answer {i}"}
            for i in range(6)
        ]
        event = _intent_event(
            "ChatIntent",
            slots={"utterance": "new question"},
            session_attrs={"history": prior_history, "mode": "general"},
        )
        with patch("src.handler.get_completion", return_value="New answer."):
            response = lambda_handler(event, {})
        history = response["sessionAttributes"].get("history", [])
        assert len(history) <= 4

    def test_openai_failure_returns_fallback(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.handler.get_completion", side_effect=RuntimeError("API down")):
            response = lambda_handler(event, {})
        speech = _ssml_text(response)
        assert "sorry" in speech.lower() or "couldn't" in speech.lower()


# ---------------------------------------------------------------------------
# AskAIIntent (one-shot)
# ---------------------------------------------------------------------------

class TestAskAIIntent:
    def test_calls_openai(self):
        event = _intent_event("AskAIIntent", slots={"utterance": "what is the speed of light"})
        with patch("src.handler.get_completion", return_value="Light travels at 300,000 km/s.") as mock_ai:
            lambda_handler(event, {})
        mock_ai.assert_called_once()

    def test_speaks_openai_response(self):
        event = _intent_event("AskAIIntent", slots={"utterance": "what is the speed of light"})
        with patch("src.handler.get_completion", return_value="Light travels at 300,000 km/s."):
            response = lambda_handler(event, {})
        assert "300,000" in _ssml_text(response)

    def test_closes_mic(self):
        """AskAIIntent is one-shot — mic must close after response."""
        event = _intent_event("AskAIIntent", slots={"utterance": "what is the speed of light"})
        with patch("src.handler.get_completion", return_value="Light travels fast."):
            response = lambda_handler(event, {})
        assert not _has_reprompt(response)
        assert not _has_elicit_directive(response)


# ---------------------------------------------------------------------------
# Stop and Cancel — regression tests for shouldEndSession fix
# ---------------------------------------------------------------------------

class TestStopAndCancel:
    def test_stop_intent_ends_session(self):
        """
        REGRESSION: Stop must explicitly set shouldEndSession=True.
        Without this, dialog mode keeps the session alive after saying 'Alexa stop'.
        """
        event = _intent_event("AMAZON.StopIntent")
        response = lambda_handler(event, {})
        assert _should_end(response), (
            "shouldEndSession must be True for StopIntent — "
            "dialog mode ignores responses that don't explicitly end the session"
        )

    def test_stop_intent_says_goodbye(self):
        event = _intent_event("AMAZON.StopIntent")
        response = lambda_handler(event, {})
        assert "goodbye" in _ssml_text(response).lower()

    def test_stop_intent_no_reprompt(self):
        event = _intent_event("AMAZON.StopIntent")
        response = lambda_handler(event, {})
        assert not _has_reprompt(response)

    def test_cancel_intent_ends_session(self):
        """
        REGRESSION: Cancel must explicitly set shouldEndSession=True.
        Same root cause as stop — dialog mode keeps session alive without explicit flag.
        """
        event = _intent_event("AMAZON.CancelIntent")
        response = lambda_handler(event, {})
        assert _should_end(response), (
            "shouldEndSession must be True for CancelIntent"
        )

    def test_cancel_intent_no_reprompt(self):
        event = _intent_event("AMAZON.CancelIntent")
        response = lambda_handler(event, {})
        assert not _has_reprompt(response)

    def test_help_intent_does_not_end_session(self):
        """Help should keep the session open so the user can ask a question."""
        event = _intent_event("AMAZON.HelpIntent")
        response = lambda_handler(event, {})
        assert not _should_end(response)

    def test_fallback_intent_does_not_end_session(self):
        event = _intent_event("AMAZON.FallbackIntent")
        response = lambda_handler(event, {})
        assert not _should_end(response)


# ---------------------------------------------------------------------------
# ShortenIntent
# ---------------------------------------------------------------------------

class TestShortenIntent:
    def test_shortens_last_answer(self):
        session = {
            "history": [{"user": "what is gravity", "assistant": "Gravity is a fundamental force of nature that attracts objects with mass toward one another."}],
            "last_answer": "Gravity is a fundamental force of nature that attracts objects with mass toward one another.",
            "mode": "general",
        }
        event = _intent_event("ShortenIntent", session_attrs=session)
        with patch("src.handler.get_completion", return_value="Gravity pulls things together.") as mock_ai:
            response = lambda_handler(event, {})
        mock_ai.assert_called_once()
        assert "Gravity pulls things together." in _ssml_text(response)

    def test_no_history_returns_prompt(self):
        event = _intent_event("ShortenIntent", session_attrs={"history": [], "mode": "general"})
        with patch("src.handler.get_completion") as mock_ai:
            response = lambda_handler(event, {})
        mock_ai.assert_not_called()
        assert "ask me something" in _ssml_text(response).lower()

    def test_updates_last_answer_in_session(self):
        session = {
            "history": [{"user": "q", "assistant": "Long answer here."}],
            "last_answer": "Long answer here.",
            "mode": "general",
        }
        event = _intent_event("ShortenIntent", session_attrs=session)
        with patch("src.handler.get_completion", return_value="Short answer."):
            response = lambda_handler(event, {})
        assert response["sessionAttributes"].get("last_answer") == "Short answer."

    def test_keeps_mic_open(self):
        session = {
            "history": [{"user": "q", "assistant": "Long answer."}],
            "last_answer": "Long answer.",
            "mode": "general",
        }
        event = _intent_event("ShortenIntent", session_attrs=session)
        with patch("src.handler.get_completion", return_value="Short."):
            response = lambda_handler(event, {})
        assert not _should_end(response)
        assert _has_reprompt(response)


# ---------------------------------------------------------------------------
# MoreDetailIntent
# ---------------------------------------------------------------------------

class TestMoreDetailIntent:
    def test_expands_last_answer(self):
        session = {
            "history": [{"user": "what is gravity", "assistant": "Gravity pulls things."}],
            "last_answer": "Gravity pulls things.",
            "mode": "general",
        }
        event = _intent_event("MoreDetailIntent", session_attrs=session)
        with patch("src.handler.get_completion", return_value="More detail about gravity.") as mock_ai:
            response = lambda_handler(event, {})
        mock_ai.assert_called_once()
        assert "More detail about gravity." in _ssml_text(response)

    def test_no_history_returns_prompt(self):
        event = _intent_event("MoreDetailIntent", session_attrs={"history": [], "mode": "general"})
        with patch("src.handler.get_completion") as mock_ai:
            response = lambda_handler(event, {})
        mock_ai.assert_not_called()
        assert "ask me something" in _ssml_text(response).lower()

    def test_includes_prior_qa_in_prompt(self):
        session = {
            "history": [{"user": "what is water", "assistant": "Water is H2O."}],
            "mode": "general",
        }
        event = _intent_event("MoreDetailIntent", session_attrs=session)
        captured = {}
        def capture(**kwargs):
            captured["user_input"] = kwargs.get("user_input")
            return "More about water."
        with patch("src.handler.get_completion", side_effect=capture):
            lambda_handler(event, {})
        assert any("H2O" in str(item) for item in captured["user_input"])

    def test_keeps_mic_open(self):
        session = {
            "history": [{"user": "q", "assistant": "A."}],
            "mode": "general",
        }
        event = _intent_event("MoreDetailIntent", session_attrs=session)
        with patch("src.handler.get_completion", return_value="More detail."):
            response = lambda_handler(event, {})
        assert not _should_end(response)
        assert _has_reprompt(response)


# ---------------------------------------------------------------------------
# RepeatIntent
# ---------------------------------------------------------------------------

class TestRepeatIntent:
    def test_repeats_last_answer_without_calling_openai(self):
        session = {
            "history": [{"user": "what is gravity", "assistant": "Gravity pulls things."}],
            "last_answer": "Gravity pulls things.",
            "mode": "general",
        }
        event = _intent_event("RepeatIntent", session_attrs=session)
        with patch("src.handler.get_completion") as mock_ai:
            response = lambda_handler(event, {})
        mock_ai.assert_not_called()
        assert "Gravity pulls things." in _ssml_text(response)

    def test_falls_back_to_history_if_no_last_answer(self):
        session = {
            "history": [{"user": "q", "assistant": "Answer from history."}],
            "mode": "general",
        }
        event = _intent_event("RepeatIntent", session_attrs=session)
        with patch("src.handler.get_completion") as mock_ai:
            response = lambda_handler(event, {})
        mock_ai.assert_not_called()
        assert "Answer from history." in _ssml_text(response)

    def test_no_history_returns_prompt(self):
        event = _intent_event("RepeatIntent", session_attrs={"history": [], "mode": "general"})
        response = lambda_handler(event, {})
        assert "ask me something" in _ssml_text(response).lower()

    def test_keeps_mic_open(self):
        session = {"history": [{"user": "q", "assistant": "A."}], "last_answer": "A.", "mode": "general"}
        event = _intent_event("RepeatIntent", session_attrs=session)
        response = lambda_handler(event, {})
        assert not _should_end(response)
        assert _has_reprompt(response)


# ---------------------------------------------------------------------------
# SessionEndedRequest
# ---------------------------------------------------------------------------

class TestSessionEndedRequest:
    def test_returns_empty_response(self):
        response = lambda_handler(_session_ended_event(), {})
        # SessionEnded must not include outputSpeech (Alexa ignores it anyway)
        assert response["response"].get("outputSpeech") is None

    def test_does_not_call_openai(self):
        with patch("src.handler.get_completion") as mock_ai:
            lambda_handler(_session_ended_event(), {})
        mock_ai.assert_not_called()


# ---------------------------------------------------------------------------
# Web search feature flag
# ---------------------------------------------------------------------------

class TestWebSearch:
    def test_web_search_passed_to_get_completion_when_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_WEB_SEARCH", "true")
        event = _intent_event("ChatIntent", slots={"utterance": "who won the match last night"})
        captured = {}
        def capture(**kwargs):
            captured["use_web_search"] = kwargs.get("use_web_search")
            return "The home team won."
        with patch("src.handler.get_completion", side_effect=capture), \
             patch("src.handler._send_progressive_response"):
            lambda_handler(event, {})
        assert captured.get("use_web_search") is True

    def test_web_search_not_passed_when_disabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_WEB_SEARCH", "false")
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        captured = {}
        def capture(**kwargs):
            captured["use_web_search"] = kwargs.get("use_web_search")
            return "Gravity pulls things down."
        with patch("src.handler.get_completion", side_effect=capture):
            lambda_handler(event, {})
        assert not captured.get("use_web_search")

    def test_progressive_response_sent_when_search_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_WEB_SEARCH", "true")
        event = _intent_event("ChatIntent", slots={"utterance": "latest news"})
        with patch("src.handler.get_completion", return_value="Here is the news."), \
             patch("src.handler._send_progressive_response") as mock_prog:
            lambda_handler(event, {})
        mock_prog.assert_called_once()
        _, speech_arg = mock_prog.call_args[0]
        assert "look that up" in speech_arg.lower()

    def test_progressive_response_not_sent_when_search_disabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_WEB_SEARCH", "false")
        event = _intent_event("ChatIntent", slots={"utterance": "what is water"})
        with patch("src.handler.get_completion", return_value="Water is H2O."), \
             patch("src.handler._send_progressive_response") as mock_prog:
            lambda_handler(event, {})
        mock_prog.assert_not_called()

    def test_search_failure_returns_fallback(self, monkeypatch):
        monkeypatch.setenv("ENABLE_WEB_SEARCH", "true")
        event = _intent_event("ChatIntent", slots={"utterance": "latest scores"})
        with patch("src.handler.get_completion", side_effect=RuntimeError("timeout")), \
             patch("src.handler._send_progressive_response"):
            response = lambda_handler(event, {})
        speech = _ssml_text(response)
        assert "sorry" in speech.lower() or "couldn't" in speech.lower()


# ---------------------------------------------------------------------------
# Unhandled / unknown intents
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cross-session memory integration
# ---------------------------------------------------------------------------

class TestCrossSessionMemory:
    def test_load_user_data_called_with_user_id(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.memory.load_user_data", return_value=([], "general")) as mock_load, \
             patch("src.handler.get_completion", return_value="Gravity pulls things."), \
             patch("src.memory.save_turns"):
            lambda_handler(event, {})
        mock_load.assert_called_once_with("amzn1.ask.account.test")

    def test_cross_session_turns_prepended_to_openai_input(self):
        past_turns = [{"user": "what is water", "assistant": "Water is H2O."}]
        event = _intent_event("ChatIntent", slots={"utterance": "tell me more"})
        captured = {}
        def capture(**kwargs):
            captured["user_input"] = kwargs.get("user_input")
            return "More details."
        with patch("src.memory.load_user_data", return_value=(past_turns, "general")), \
             patch("src.handler.get_completion", side_effect=capture), \
             patch("src.memory.save_turns"):
            lambda_handler(event, {})
        assert any("H2O" in str(item) for item in captured["user_input"])
        # Past turn must appear before current utterance
        indices = [i for i, item in enumerate(captured["user_input"]) if "H2O" in str(item)]
        current_indices = [i for i, item in enumerate(captured["user_input"]) if "tell me more" in str(item)]
        assert indices[0] < current_indices[0]

    def test_load_called_only_once_per_session(self):
        # Pre-populate cross_session_turns in session — load should not be called again
        event = _intent_event(
            "ChatIntent",
            slots={"utterance": "what is gravity"},
            session_attrs={"cross_session_turns": [], "history": [], "mode": "general"},
        )
        with patch("src.memory.load_user_data") as mock_load, \
             patch("src.handler.get_completion", return_value="Gravity pulls things."), \
             patch("src.memory.save_turns"):
            lambda_handler(event, {})
        mock_load.assert_not_called()

    def test_save_turns_called_with_merged_history(self):
        past_turns = [{"user": "what is water", "assistant": "Water is H2O."}]
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.memory.load_user_data", return_value=(past_turns, "general")), \
             patch("src.handler.get_completion", return_value="Gravity pulls things."), \
             patch("src.memory.save_turns") as mock_save:
            lambda_handler(event, {})
        mock_save.assert_called_once()
        saved_turns = mock_save.call_args[0][1]
        # Should contain both the past turn and the new turn
        assert any(t.get("user") == "what is water" for t in saved_turns)
        assert any(t.get("user") == "what is gravity" for t in saved_turns)

    def test_save_not_called_on_openai_failure(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.memory.load_user_data", return_value=([], "general")), \
             patch("src.handler.get_completion", side_effect=RuntimeError("API down")), \
             patch("src.memory.save_turns") as mock_save:
            lambda_handler(event, {})
        mock_save.assert_not_called()

    def test_memory_load_failure_does_not_crash(self):
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.memory.load_user_data", side_effect=RuntimeError("DDB down")), \
             patch("src.handler.get_completion", return_value="Gravity pulls things."), \
             patch("src.memory.save_turns"):
            response = lambda_handler(event, {})
        speech = _ssml_text(response)
        assert len(speech) > 0

    def test_memory_disabled_produces_normal_response(self, monkeypatch):
        monkeypatch.setenv("ENABLE_MEMORY", "false")
        event = _intent_event("ChatIntent", slots={"utterance": "what is gravity"})
        with patch("src.memory.load_user_data", return_value=([], "general")) as mock_load, \
             patch("src.handler.get_completion", return_value="Gravity pulls things.") as mock_ai, \
             patch("src.memory.save_turns"):
            response = lambda_handler(event, {})
        mock_ai.assert_called_once()
        assert "Gravity pulls things." in _ssml_text(response)


# ---------------------------------------------------------------------------
# SetModeIntent
# ---------------------------------------------------------------------------

class TestSetModeIntent:
    def test_switches_mode_and_updates_session(self):
        event = _intent_event("SetModeIntent", slots={"mode": "child"},
                              session_attrs={"history": [], "mode": "general"})
        with patch("src.memory.save_mode") as mock_save:
            response = lambda_handler(event, {})
        speech = _ssml_text(response)
        assert "kids" in speech.lower() or "child" in speech.lower()
        assert response["sessionAttributes"].get("mode") == "child"
        mock_save.assert_called_once_with("amzn1.ask.account.test", "child")

    def test_already_in_requested_mode(self):
        event = _intent_event("SetModeIntent", slots={"mode": "general"},
                              session_attrs={"history": [], "mode": "general"})
        with patch("src.memory.save_mode") as mock_save:
            response = lambda_handler(event, {})
        speech = _ssml_text(response)
        assert "already" in speech.lower()
        mock_save.assert_not_called()

    def test_unknown_mode_value_prompts_choice(self):
        event = _intent_event("SetModeIntent", slots={"mode": "turbo"},
                              session_attrs={"history": [], "mode": "general"})
        with patch("src.memory.save_mode") as mock_save:
            response = lambda_handler(event, {})
        speech = _ssml_text(response)
        assert "general" in speech.lower() or "kids" in speech.lower()
        mock_save.assert_not_called()

    def test_keeps_mic_open(self):
        event = _intent_event("SetModeIntent", slots={"mode": "educational"},
                              session_attrs={"history": [], "mode": "general"})
        with patch("src.memory.save_mode"):
            response = lambda_handler(event, {})
        assert not _should_end(response)
        assert _has_reprompt(response)
        assert _has_elicit_directive(response)

    def test_educational_mode_switch(self):
        event = _intent_event("SetModeIntent", slots={"mode": "educational"},
                              session_attrs={"history": [], "mode": "general"})
        with patch("src.memory.save_mode"):
            response = lambda_handler(event, {})
        assert response["sessionAttributes"].get("mode") == "educational"
        assert "educational" in _ssml_text(response).lower()

    def test_mode_persists_to_next_utterance(self):
        """After SetModeIntent sets child mode, next ChatIntent uses child prompt."""
        # First: set mode to child (session now has mode=child, cross_session_turns present)
        set_event = _intent_event("SetModeIntent", slots={"mode": "child"},
                                  session_attrs={"history": [], "mode": "general",
                                                 "cross_session_turns": []})
        with patch("src.memory.save_mode"):
            set_response = lambda_handler(set_event, {})

        # Second: chat utterance using session attrs from previous response
        session_after_set = set_response["sessionAttributes"]
        chat_event = _intent_event("ChatIntent", slots={"utterance": "what is water"},
                                   session_attrs=session_after_set)
        captured = {}
        def capture(**kwargs):
            captured["instructions"] = kwargs.get("instructions", "")
            return "Water is H2O."
        with patch("src.handler.get_completion", side_effect=capture), \
             patch("src.memory.save_turns"):
            lambda_handler(chat_event, {})
        assert "child" in captured["instructions"].lower()


# ---------------------------------------------------------------------------
# Persistent mode loaded from DynamoDB
# ---------------------------------------------------------------------------

class TestPersistentMode:
    def test_persisted_mode_loaded_at_first_utterance(self):
        """load_user_data returning educational mode results in educational prompt."""
        event = _intent_event("ChatIntent", slots={"utterance": "what is DNA"})
        captured = {}
        def capture(**kwargs):
            captured["instructions"] = kwargs.get("instructions", "")
            return "DNA is the blueprint of life."
        with patch("src.memory.load_user_data", return_value=([], "educational")), \
             patch("src.handler.get_completion", side_effect=capture), \
             patch("src.memory.save_turns"):
            lambda_handler(event, {})
        assert "educational" in captured["instructions"].lower()

    def test_persisted_mode_stored_in_session(self):
        """Session attributes reflect the mode loaded from DynamoDB."""
        event = _intent_event("ChatIntent", slots={"utterance": "what is DNA"})
        with patch("src.memory.load_user_data", return_value=([], "child")), \
             patch("src.handler.get_completion", return_value="DNA is genetic code."), \
             patch("src.memory.save_turns"):
            response = lambda_handler(event, {})
        assert response["sessionAttributes"].get("mode") == "child"

    def test_mode_included_in_save_turns_call(self):
        """save_turns is called with the current session mode."""
        event = _intent_event("ChatIntent", slots={"utterance": "what is water"},
                              session_attrs={"cross_session_turns": [], "history": [],
                                            "mode": "educational"})
        with patch("src.handler.get_completion", return_value="Water is H2O."), \
             patch("src.memory.save_turns") as mock_save:
            lambda_handler(event, {})
        mock_save.assert_called_once()
        assert mock_save.call_args[1].get("mode") == "educational"


class TestUnhandledRequest:
    def test_unknown_intent_returns_fallback_speech(self):
        event = _intent_event("UnknownCustomIntent")
        response = lambda_handler(event, {})
        speech = _ssml_text(response)
        assert len(speech) > 0

    def test_unknown_intent_keeps_session_open(self):
        event = _intent_event("UnknownCustomIntent")
        response = lambda_handler(event, {})
        assert not _should_end(response)
