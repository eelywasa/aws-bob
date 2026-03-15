"""Alexa ASK SDK entrypoint and intent handlers."""

from __future__ import annotations

from typing import Any

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.api_client import DefaultApiClient
from ask_sdk_core.skill_builder import CustomSkillBuilder, SkillBuilder
from ask_sdk_model import Intent, Response
from ask_sdk_model.dialog import ElicitSlotDirective
from ask_sdk_model.slot import Slot
from ask_sdk_model.ui import SimpleCard

import httpx
import os
import random
import time

from . import memory
from .openai_client import get_completion
from .phrases import get_chat_phrases, get_question_phrases
from .prompts import VALID_MODES, _MODE_DISPLAY, build_system_prompt
from .safety import check_input, sanitize_output
from .telemetry import consume_cold_start, emit_emf
from .util import log_intent, logger

# Graceful fallback when AI fails
FALLBACK_MSG = (
    "Sorry, I couldn't get an answer right now. "
    "Try again in a moment, or ask me something else."
)

# Fallback when AI is too slow (distinct from hard failure)
TIMEOUT_MSG = (
    "That's taking a bit long today. "
    "Try asking again in a moment."
)

MAX_TURNS = 4
DEFAULT_REPROMPT = "What else would you like to know?"
EMPTY_UTTERANCE_REPROMPT = "Tell me what you'd like to chat about."

_QUESTION_WORDS = frozenset((
    "what", "why", "how", "when", "where", "who", "which",
    "is", "are", "can", "does", "do", "will",
))


def _get_progressive_phrase(text: str) -> str | None:
    """Return a progressive phrase for the utterance, or None if too short to warrant one."""
    min_words = int(os.environ.get("PROGRESSIVE_MIN_WORDS", "8"))
    words = text.lower().split()
    if len(words) < min_words:
        return None
    if words[0] in _QUESTION_WORDS or text.rstrip().endswith("?"):
        return random.choice(get_question_phrases())
    return random.choice(get_chat_phrases())


def _send_progressive_response(handler_input: HandlerInput, speech: str) -> None:
    """Send a VoicePlayer.Speak directive so the device speaks while Lambda is still running."""
    from ask_sdk_model.services.directive import (
        Header,
        SendDirectiveRequest,
        SpeakDirective,
    )
    try:
        request_id = handler_input.request_envelope.request.request_id
        directive_client = (
            handler_input.service_client_factory.get_directive_service()
        )
        directive_client.enqueue(
            SendDirectiveRequest(
                header=Header(request_id=request_id),
                directive=SpeakDirective(speech=speech),
            )
        )
    except Exception:
        # In tests or when API credentials are absent, silently skip.
        logger.debug("Progressive response skipped (no service client)")


def _get_request_type(handler_input: HandlerInput) -> str | None:
    """Safely get request type (object_type). Never use .type - SDK uses object_type."""
    req = handler_input.request_envelope.request
    return getattr(req, "object_type", None)


def _elicit_chat_utterance() -> ElicitSlotDirective:
    """Build ElicitSlotDirective for ChatIntent.utterance so next speech is captured without carrier phrase."""
    utterance_slot = Slot(name="utterance", value="", confirmation_status="NONE")
    updated_intent = Intent(
        name="ChatIntent",
        slots={"utterance": utterance_slot},
        confirmation_status="NONE",
    )
    return ElicitSlotDirective(
        slot_to_elicit="utterance",
        updated_intent=updated_intent,
    )


def _extract_utterance_slot(handler_input: HandlerInput) -> str:
    """Extract 'utterance' slot value from intent (SearchQuery or Literal)."""
    if _get_request_type(handler_input) != "IntentRequest":
        return ""
    req = handler_input.request_envelope.request
    intent = getattr(req, "intent", None)
    if not intent:
        return ""
    slots = getattr(intent, "slots", {}) or {}
    utterance_slot = slots.get("utterance")
    if not utterance_slot:
        return ""
    return (getattr(utterance_slot, "value", None) or "").strip()


def handle_user_utterance(
    handler_input: HandlerInput,
    user_text: str,
    keep_mic_open: bool = False,
) -> Response:
    """
    Shared logic for processing user utterance: validate, call OpenAI, persist session.
    Returns speak() + optionally ask() to keep mic open.
    """
    session_attrs = handler_input.attributes_manager.session_attributes

    # Validate empty utterance
    if not user_text:
        speech = (
            "I didn't quite catch that. "
            "Try asking me something in your own words."
        )
        if keep_mic_open:
            return (
                handler_input.response_builder.speak(speech)
                .ask(EMPTY_UTTERANCE_REPROMPT)
                .add_directive(_elicit_chat_utterance())
                .set_card(SimpleCard("Brainy Bob", speech))
                .response
            )
        return (
            handler_input.response_builder.speak(speech)
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )

    # Safety check
    allowed, _ = check_input(user_text)
    if not allowed:
        speech = (
            "I didn't quite catch that. "
            "Try asking me a question in your own words."
        )
        if keep_mic_open:
            return (
                handler_input.response_builder.speak(speech)
                .ask(EMPTY_UTTERANCE_REPROMPT)
                .add_directive(_elicit_chat_utterance())
                .set_card(SimpleCard("Brainy Bob", speech))
                .response
            )
        return (
            handler_input.response_builder.speak(speech)
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )

    # Telemetry — cold-start detection and total request timer
    is_cold = consume_cold_start()
    _t_total = time.perf_counter()

    # Build history from session (ensure list exists)
    history: list[dict[str, Any]] = session_attrs.get("history", [])
    if not isinstance(history, list):
        history = []

    # Load cross-session memory and persisted mode once per session
    _ddb_load_ms: float | None = None
    if "cross_session_turns" not in session_attrs:
        user_id = handler_input.request_envelope.context.system.user.user_id
        _t_ddb_load = time.perf_counter()
        try:
            turns, persisted_mode = memory.load_user_data(user_id)
        except Exception:
            turns, persisted_mode = [], "general"
        _ddb_load_ms = (time.perf_counter() - _t_ddb_load) * 1000
        session_attrs["cross_session_turns"] = turns
        session_attrs["mode"] = persisted_mode  # DDB preference wins over launch default
    cross_session_turns: list[dict] = session_attrs.get("cross_session_turns", [])
    mode = session_attrs.get("mode", "general")

    # Build input for OpenAI — prepend past turns then current session turns
    input_items: list[dict[str, Any]] = memory.build_cross_session_input(cross_session_turns)
    for turn in history:
        input_items.append({"role": "user", "content": turn.get("user", "")})
        input_items.append({"role": "assistant", "content": turn.get("assistant", "")})
    input_items.append({"role": "user", "content": user_text})

    use_web_search = os.environ.get("ENABLE_WEB_SEARCH", "false").lower() == "true"
    instructions = build_system_prompt(mode, web_search=use_web_search)
    progressive_enabled = os.environ.get("ENABLE_PROGRESSIVE_RESPONSE", "true").lower() == "true"

    if progressive_enabled:
        if use_web_search:
            _send_progressive_response(handler_input, "Let me look that up for you.")
        else:
            phrase = _get_progressive_phrase(user_text)
            if phrase:
                _send_progressive_response(handler_input, phrase)

    ai_succeeded = False
    _t_openai = time.perf_counter()
    try:
        text = get_completion(
            instructions=instructions,
            user_input=input_items,
            store=False,
            use_web_search=use_web_search,
        )
        ai_succeeded = True
    except httpx.TimeoutException:
        logger.warning(
            "OpenAI request timed out",
            extra={"structured": {"error_type": "TimeoutException"}},
        )
        text = TIMEOUT_MSG
    except Exception as e:
        logger.exception(
            "OpenAI request failed",
            extra={"structured": {"error_type": type(e).__name__}},
        )
        text = FALLBACK_MSG
    _openai_ms = (time.perf_counter() - _t_openai) * 1000

    _ddb_save_ms: float | None = None
    if not text:
        text = FALLBACK_MSG
    else:
        text = sanitize_output(text)
        # Persist turn and cap history
        history.append({"user": user_text, "assistant": text})
        if len(history) > MAX_TURNS:
            history = history[-MAX_TURNS:]
        session_attrs["history"] = history
        session_attrs["last_answer"] = text
        if ai_succeeded:
            user_id = handler_input.request_envelope.context.system.user.user_id
            _t_ddb_save = time.perf_counter()
            memory.save_turns(user_id, cross_session_turns + history, mode=session_attrs.get("mode", "general"))
            _ddb_save_ms = (time.perf_counter() - _t_ddb_save) * 1000

    req = handler_input.request_envelope.request
    intent_name = getattr(getattr(req, "intent", None), "name", None) or "Unknown"
    emit_emf(
        intent=intent_name,
        is_cold=is_cold,
        total_ms=(time.perf_counter() - _t_total) * 1000,
        openai_ms=_openai_ms,
        ddb_load_ms=_ddb_load_ms,
        ddb_save_ms=_ddb_save_ms,
    )

    response_builder = (
        handler_input.response_builder.speak(text)
        .set_card(SimpleCard("Brainy Bob", text))
    )
    if keep_mic_open:
        response_builder = (
            response_builder
            .ask(DEFAULT_REPROMPT)
            .add_directive(_elicit_chat_utterance())
        )
    return response_builder.response


class LaunchRequestHandler(AbstractRequestHandler):
    """Handle LaunchRequest - 'Alexa, open brainy bob'."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return _get_request_type(handler_input) == "LaunchRequest"

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        session_attrs = handler_input.attributes_manager.session_attributes
        # Ensure session attributes exist
        if "history" not in session_attrs:
            session_attrs["history"] = []
        if "mode" not in session_attrs:
            session_attrs["mode"] = "general"

        greeting = "Hi, I'm Brainy Bob. What should we talk about?"
        reprompt = "Tell me what you'd like to chat about."

        return (
            handler_input.response_builder.speak(greeting)
            .ask(reprompt)
            .add_directive(_elicit_chat_utterance())
            .set_card(SimpleCard("Brainy Bob", greeting))
            .response
        )


class AskAIIntentHandler(AbstractRequestHandler):
    """Handle AskAIIntent - one-shot style ('Alexa, ask brainy bob ...')."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            _get_request_type(handler_input) == "IntentRequest"
            and getattr(getattr(req, "intent", None), "name", "") == "AskAIIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        utterance = _extract_utterance_slot(handler_input)
        return handle_user_utterance(handler_input, utterance, keep_mic_open=False)


class ChatIntentHandler(AbstractRequestHandler):
    """Handle ChatIntent - dialog-elicited utterance (no carrier phrase)."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            _get_request_type(handler_input) == "IntentRequest"
            and getattr(getattr(req, "intent", None), "name", "") == "ChatIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        utterance = _extract_utterance_slot(handler_input)
        # Empty slot: prompt and keep mic open (re-elicit or fallback)
        return handle_user_utterance(handler_input, utterance, keep_mic_open=True)


def _handle_shorten(handler_input: HandlerInput) -> str:
    """Shorten last_answer via OpenAI or fallback. Returns speech text."""
    session_attrs = handler_input.attributes_manager.session_attributes
    last_answer = session_attrs.get("last_answer", "")
    history = session_attrs.get("history", [])

    if not last_answer and history:
        last_answer = history[-1].get("assistant", "") if history else ""
    if not last_answer:
        return "Ask me something first, then I can shorten it for you."

    instructions = (
        "You are Brainy Bob, a voice assistant. "
        "Summarise the following in 1-2 short sentences suitable for speaking aloud. "
        "No markdown, no lists."
    )
    try:
        speech = get_completion(
            instructions=instructions,
            user_input=f"Summarise briefly: {last_answer}",
            store=False,
        )
    except Exception as e:
        logger.exception("Shorten failed", extra={"structured": {"error": type(e).__name__}})
        return FALLBACK_MSG
    return sanitize_output(speech or FALLBACK_MSG)


def _handle_more_detail(handler_input: HandlerInput) -> str:
    """Expand last_answer or last question via OpenAI. Returns speech text."""
    session_attrs = handler_input.attributes_manager.session_attributes
    history = session_attrs.get("history", [])
    last_user = history[-1].get("user", "") if history else ""
    last_assistant = history[-1].get("assistant", "") if history else ""

    if not last_user or not last_assistant:
        return "Ask me something first, then say tell me more."

    instructions = build_system_prompt(session_attrs.get("mode", "general"))
    instructions += (
        "\n\nThe user wants more detail on your previous answer. "
        "Expand helpfully in 3-5 sentences. Voice-friendly, no markdown."
    )
    input_items = [
        {"role": "user", "content": last_user},
        {"role": "assistant", "content": last_assistant},
        {"role": "user", "content": "Could you tell me more about that?"},
    ]
    try:
        speech = get_completion(
            instructions=instructions,
            user_input=input_items,
            store=False,
        )
    except Exception as e:
        logger.exception("MoreDetail failed", extra={"structured": {"error": type(e).__name__}})
        return FALLBACK_MSG
    return sanitize_output(speech or FALLBACK_MSG)


class ShortenIntentHandler(AbstractRequestHandler):
    """Handle ShortenIntent - shorter version of last answer."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            _get_request_type(handler_input) == "IntentRequest"
            and getattr(getattr(req, "intent", None), "name", "") == "ShortenIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        speech = _handle_shorten(handler_input)
        # Update last_answer in session for subsequent Repeat/MoreDetail
        session_attrs = handler_input.attributes_manager.session_attributes
        session_attrs["last_answer"] = speech
        history = session_attrs.get("history", [])
        if history:
            history[-1] = {"user": history[-1].get("user", ""), "assistant": speech}
            session_attrs["history"] = history
        return (
            handler_input.response_builder.speak(speech)
            .ask(DEFAULT_REPROMPT)
            .add_directive(_elicit_chat_utterance())
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )


class MoreDetailIntentHandler(AbstractRequestHandler):
    """Handle MoreDetailIntent - expand on last answer."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            _get_request_type(handler_input) == "IntentRequest"
            and getattr(getattr(req, "intent", None), "name", "") == "MoreDetailIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        speech = _handle_more_detail(handler_input)
        session_attrs = handler_input.attributes_manager.session_attributes
        session_attrs["last_answer"] = speech
        history = session_attrs.get("history", [])
        if history:
            history[-1] = {"user": history[-1].get("user", ""), "assistant": speech}
            session_attrs["history"] = history
        return (
            handler_input.response_builder.speak(speech)
            .ask(DEFAULT_REPROMPT)
            .add_directive(_elicit_chat_utterance())
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )


class RepeatIntentHandler(AbstractRequestHandler):
    """Handle RepeatIntent - repeat last answer without calling OpenAI."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            _get_request_type(handler_input) == "IntentRequest"
            and getattr(getattr(req, "intent", None), "name", "") == "RepeatIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        session_attrs = handler_input.attributes_manager.session_attributes
        last_answer = session_attrs.get("last_answer", "")
        history = session_attrs.get("history", [])
        if not last_answer and history:
            last_answer = history[-1].get("assistant", "") if history else ""
        speech = last_answer or "Ask me something first, then I can repeat it."
        return (
            handler_input.response_builder.speak(speech)
            .ask(DEFAULT_REPROMPT)
            .add_directive(_elicit_chat_utterance())
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )


class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handle SessionEndedRequest - session ended, timeout, or user exit."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return _get_request_type(handler_input) == "SessionEndedRequest"

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        return handler_input.response_builder.response


class UnhandledRequestHandler(AbstractRequestHandler):
    """Catch-all for any request not matched by other handlers."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return True

    def handle(self, handler_input: HandlerInput) -> Response:
        req = handler_input.request_envelope.request
        req_type = _get_request_type(handler_input) or type(req).__name__
        logger.warning(
            "Unhandled request",
            extra={"structured": {"request_type": req_type}},
        )
        speech = "Sorry, I didn't get that. What would you like to talk about?"
        return (
            handler_input.response_builder.speak(speech)
            .ask("You can ask me a question or say help.")
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )


class SetModeIntentHandler(AbstractRequestHandler):
    """Handle SetModeIntent — user switches conversational mode by voice."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            _get_request_type(handler_input) == "IntentRequest"
            and getattr(getattr(req, "intent", None), "name", "") == "SetModeIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        req = handler_input.request_envelope.request
        intent = getattr(req, "intent", None)
        slots = getattr(intent, "slots", {}) or {}
        mode_slot = slots.get("mode")
        raw_value = (getattr(mode_slot, "value", None) or "").strip().lower()

        session_attrs = handler_input.attributes_manager.session_attributes

        if raw_value not in VALID_MODES:
            speech = (
                "I can switch to general, kids, or educational mode. "
                "Which would you like?"
            )
            return (
                handler_input.response_builder.speak(speech)
                .ask(speech)
                .add_directive(_elicit_chat_utterance())
                .set_card(SimpleCard("Brainy Bob", speech))
                .response
            )

        current_mode = session_attrs.get("mode", "general")
        display = _MODE_DISPLAY.get(raw_value, raw_value)

        if raw_value == current_mode:
            speech = f"I'm already in {display} mode. What would you like to know?"
        else:
            session_attrs["mode"] = raw_value
            user_id = handler_input.request_envelope.context.system.user.user_id
            memory.save_mode(user_id, raw_value)
            speech = f"Switching to {display} mode. What would you like to know?"

        return (
            handler_input.response_builder.speak(speech)
            .ask(DEFAULT_REPROMPT)
            .add_directive(_elicit_chat_utterance())
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )


class BuiltInIntentHandler(AbstractRequestHandler):
    """Handle AMAZON built-in intents (Help, Stop, Cancel, Fallback)."""

    def __init__(self, intent_name: str, speech: str, end_session: bool = False):
        self.intent_name = intent_name
        self.speech = speech
        self.end_session = end_session

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        if _get_request_type(handler_input) != "IntentRequest":
            return False
        return getattr(getattr(req, "intent", None), "name", "") == self.intent_name

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        rb = (
            handler_input.response_builder.speak(self.speech)
            .set_card(SimpleCard("Brainy Bob", self.speech))
        )
        if self.end_session:
            rb = rb.set_should_end_session(True)
        return rb.response


def _register_handlers(sb: SkillBuilder) -> SkillBuilder:
    sb.add_request_handler(LaunchRequestHandler())
    sb.add_request_handler(SessionEndedRequestHandler())
    sb.add_request_handler(ChatIntentHandler())
    sb.add_request_handler(AskAIIntentHandler())
    sb.add_request_handler(ShortenIntentHandler())
    sb.add_request_handler(MoreDetailIntentHandler())
    sb.add_request_handler(RepeatIntentHandler())
    sb.add_request_handler(SetModeIntentHandler())
    sb.add_request_handler(
        BuiltInIntentHandler(
            "AMAZON.HelpIntent",
            "You can ask me anything, or say switch to kids mode or educational mode. "
            "What would you like to know?",
        )
    )
    sb.add_request_handler(
        BuiltInIntentHandler("AMAZON.StopIntent", "Goodbye.", end_session=True)
    )
    sb.add_request_handler(
        BuiltInIntentHandler("AMAZON.CancelIntent", "Cancelled.", end_session=True)
    )
    sb.add_request_handler(
        BuiltInIntentHandler(
            "AMAZON.FallbackIntent",
            "Sorry, I didn't get that. You can ask me a question or say help.",
        )
    )
    # Must be last: catch-all for any unhandled request
    sb.add_request_handler(UnhandledRequestHandler())
    return sb


sb = CustomSkillBuilder(api_client=DefaultApiClient())
_register_handlers(sb)
lambda_handler = sb.lambda_handler()
