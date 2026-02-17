"""Alexa ASK SDK entrypoint and intent handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import is_intent_name, is_request_type
from ask_sdk_model import Intent, Response
from ask_sdk_model.dialog import ElicitSlotDirective
from ask_sdk_model.slot import Slot
from ask_sdk_model.ui import SimpleCard

from .openai_client import get_completion
from .prompts import build_system_prompt
from .safety import check_input, sanitize_output
from .util import log_intent, logger

# Graceful fallback when AI fails
FALLBACK_MSG = (
    "Sorry, I couldn't get an answer right now. "
    "Try again in a moment, or ask me something else."
)

MAX_TURNS = 4
DEFAULT_REPROMPT = "What else would you like to know?"
EMPTY_UTTERANCE_REPROMPT = "Tell me what you'd like to chat about."


def _run_async(coro):
    """Run async code from sync handler (Lambda is sync by default)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _extract_utterance_slot(handler_input: HandlerInput) -> str:
    """Extract 'utterance' slot value from intent (SearchQuery or Literal)."""
    req = handler_input.request_envelope.request
    if getattr(req, "object_type", None) != "IntentRequest":
        return ""
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
                .set_card(SimpleCard("Brainy Bob", speech))
                .response
            )
        return (
            handler_input.response_builder.speak(speech)
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )

    # Build history from session (ensure list exists)
    history: list[dict[str, Any]] = session_attrs.get("history", [])
    if not isinstance(history, list):
        history = []
    audience = session_attrs.get("audience", "general")

    # Build input for OpenAI
    input_items: list[dict[str, Any]] = []
    for turn in history:
        input_items.append({"role": "user", "content": turn.get("user", "")})
        input_items.append({"role": "assistant", "content": turn.get("assistant", "")})
    input_items.append({"role": "user", "content": user_text})

    instructions = build_system_prompt(audience)

    try:
        text = _run_async(
            get_completion(
                instructions=instructions,
                user_input=input_items,
                store=False,
            )
        )
    except Exception as e:
        logger.exception(
            "OpenAI request failed",
            extra={"structured": {"error_type": type(e).__name__}},
        )
        text = FALLBACK_MSG

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

    response_builder = (
        handler_input.response_builder.speak(text)
        .set_card(SimpleCard("Brainy Bob", text))
    )
    if keep_mic_open:
        response_builder = response_builder.ask(DEFAULT_REPROMPT)
    return response_builder.response


class LaunchRequestHandler(AbstractRequestHandler):
    """Handle LaunchRequest - 'Alexa, open brainy bob'."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        session_attrs = handler_input.attributes_manager.session_attributes
        # Ensure session attributes exist
        if "history" not in session_attrs:
            session_attrs["history"] = []
        if "audience" not in session_attrs:
            session_attrs["audience"] = "general"

        greeting = "Hi, I'm Brainy Bob. What should we talk about?"
        reprompt = "Tell me what you'd like to chat about."

        # Elicit utterance slot for ChatIntent via dialog (no carrier phrase needed)
        utterance_slot = Slot(name="utterance", value="", confirmation_status="NONE")
        updated_intent = Intent(
            name="ChatIntent",
            slots={"utterance": utterance_slot},
            confirmation_status="NONE",
        )
        directive = ElicitSlotDirective(
            slot_to_elicit="utterance",
            updated_intent=updated_intent,
        )

        return (
            handler_input.response_builder.speak(greeting)
            .ask(reprompt)
            .add_directive(directive)
            .set_card(SimpleCard("Brainy Bob", greeting))
            .response
        )


class AskAIIntentHandler(AbstractRequestHandler):
    """Handle AskAIIntent - one-shot style ('Alexa, ask brainy bob ...')."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            getattr(req, "object_type", None) == "IntentRequest"
            and getattr(getattr(req, "intent", None), "name", "") == "AskAIIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        utterance = _extract_utterance_slot(handler_input)
        return handle_user_utterance(handler_input, utterance, keep_mic_open=False)


class ChatIntentHandler(AbstractRequestHandler):
    """Handle ChatIntent - dialog-elicited utterance (no carrier phrase)."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_intent_name("ChatIntent")(handler_input)

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
        speech = _run_async(
            get_completion(
                instructions=instructions,
                user_input=f"Summarise briefly: {last_answer}",
                store=False,
            )
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

    instructions = build_system_prompt(session_attrs.get("audience", "general"))
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
        speech = _run_async(
            get_completion(
                instructions=instructions,
                user_input=input_items,
                store=False,
            )
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
            getattr(req, "object_type", None) == "IntentRequest"
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
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )


class MoreDetailIntentHandler(AbstractRequestHandler):
    """Handle MoreDetailIntent - expand on last answer."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            getattr(req, "object_type", None) == "IntentRequest"
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
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )


class RepeatIntentHandler(AbstractRequestHandler):
    """Handle RepeatIntent - repeat last answer without calling OpenAI."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        return (
            getattr(req, "object_type", None) == "IntentRequest"
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
            .set_card(SimpleCard("Brainy Bob", speech))
            .response
        )


class SessionEndedRequestHandler(AbstractRequestHandler):
    """Handle SessionEndedRequest - session ended, timeout, or user exit."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        return handler_input.response_builder.response


class UnhandledRequestHandler(AbstractRequestHandler):
    """Catch-all for any request not matched by other handlers."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return True

    def handle(self, handler_input: HandlerInput) -> Response:
        req = handler_input.request_envelope.request
        req_type = getattr(req, "object_type", type(req).__name__)
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


class BuiltInIntentHandler(AbstractRequestHandler):
    """Handle AMAZON built-in intents (Help, Stop, Cancel, Fallback)."""

    def __init__(self, intent_name: str, speech: str):
        self.intent_name = intent_name
        self.speech = speech

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        if getattr(req, "object_type", None) != "IntentRequest":
            return False
        return getattr(getattr(req, "intent", None), "name", "") == self.intent_name

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        return (
            handler_input.response_builder.speak(self.speech)
            .set_card(SimpleCard("Brainy Bob", self.speech))
            .response
        )


def _register_handlers(sb: SkillBuilder) -> SkillBuilder:
    sb.add_request_handler(LaunchRequestHandler())
    sb.add_request_handler(SessionEndedRequestHandler())
    sb.add_request_handler(ChatIntentHandler())
    sb.add_request_handler(AskAIIntentHandler())
    sb.add_request_handler(ShortenIntentHandler())
    sb.add_request_handler(MoreDetailIntentHandler())
    sb.add_request_handler(RepeatIntentHandler())
    sb.add_request_handler(
        BuiltInIntentHandler(
            "AMAZON.HelpIntent",
            "You can ask me anything. Try: dinosaurs, tell me a story, "
            "or why is the sky blue. What would you like to know?",
        )
    )
    sb.add_request_handler(
        BuiltInIntentHandler("AMAZON.StopIntent", "Goodbye.")
    )
    sb.add_request_handler(
        BuiltInIntentHandler("AMAZON.CancelIntent", "Cancelled.")
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


sb = SkillBuilder()
_register_handlers(sb)
lambda_handler = sb.lambda_handler()
