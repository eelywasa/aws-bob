"""Alexa ASK SDK entrypoint and intent handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from ask_sdk_core.dispatch_components import AbstractRequestHandler
from ask_sdk_core.handler_input import HandlerInput
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_model import Response
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


def _run_async(coro):
    """Run async code from sync handler (Lambda is sync by default)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class AskAIIntentHandler(AbstractRequestHandler):
    """Handle AskAIIntent with slot 'utterance' (AMAZON.SearchQuery)."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            handler_input.request_envelope.request.type == "IntentRequest"
            and getattr(
                handler_input.request_envelope.request.intent,
                "name",
                "",
            )
            == "AskAIIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        session_attrs = handler_input.attributes_manager.session_attributes

        # Get utterance from slot
        slots = getattr(
            handler_input.request_envelope.request.intent,
            "slots",
            {},
        ) or {}
        utterance_slot = slots.get("utterance")
        utterance = (
            getattr(utterance_slot, "value", None) if utterance_slot else None
        ) or ""

        # Build conversation context from session
        history: list[dict[str, Any]] = session_attrs.get("conversation", [])
        audience = session_attrs.get("audience", "general")

        # Safety check
        allowed, reason = check_input(utterance)
        if not allowed:
            speech = (
                "I didn't quite catch that. "
                "Try asking me a question in your own words."
            )
            return (
                handler_input.response_builder.speak(speech)
                .set_card(SimpleCard("Bob", speech))
                .response
            )

        # Build input for OpenAI (multi-turn)
        input_items: list[dict[str, Any]] = []
        for turn in history:
            input_items.append({"role": "user", "content": turn.get("user", "")})
            input_items.append({"role": "assistant", "content": turn.get("assistant", "")})
        input_items.append({"role": "user", "content": utterance})

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
            # Persist turn in session for multi-turn
            history.append({"user": utterance, "assistant": text})
            # Keep last N turns to avoid token bloat
            max_turns = 5
            if len(history) > max_turns:
                history = history[-max_turns:]
            session_attrs["conversation"] = history

        return (
            handler_input.response_builder.speak(text)
            .set_card(SimpleCard("Bob", text))
            .response
        )


class ShortenIntentHandler(AbstractRequestHandler):
    """Handle ShortenIntent - ask for a shorter reply."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            handler_input.request_envelope.request.type == "IntentRequest"
            and getattr(
                handler_input.request_envelope.request.intent,
                "name",
                "",
            )
            == "ShortenIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        session_attrs = handler_input.attributes_manager.session_attributes
        history = session_attrs.get("conversation", [])
        last_assistant = history[-1].get("assistant", "") if history else ""
        if not last_assistant:
            speech = "I don't have anything to shorten. Ask me something first."
        else:
            instructions = (
                "You are Bob, a voice assistant. "
                "Summarise the following in 1-2 short sentences suitable for speaking aloud. "
                "No markdown, no lists."
            )
            try:
                speech = _run_async(
                    get_completion(
                        instructions=instructions,
                        user_input=f"Summarise briefly: {last_assistant}",
                        store=False,
                    )
                )
            except Exception as e:
                logger.exception("Shorten failed", extra={"structured": {"error": type(e).__name__}})
                speech = FALLBACK_MSG
            speech = sanitize_output(speech or FALLBACK_MSG)
        return (
            handler_input.response_builder.speak(speech)
            .set_card(SimpleCard("Bob", speech))
            .response
        )


class MoreDetailIntentHandler(AbstractRequestHandler):
    """Handle MoreDetailIntent - ask for more detail on last reply."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            handler_input.request_envelope.request.type == "IntentRequest"
            and getattr(
                handler_input.request_envelope.request.intent,
                "name",
                "",
            )
            == "MoreDetailIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        session_attrs = handler_input.attributes_manager.session_attributes
        history = session_attrs.get("conversation", [])
        last_user = history[-1].get("user", "") if history else ""
        last_assistant = history[-1].get("assistant", "") if history else ""
        if not last_user or not last_assistant:
            speech = "I need a bit more context. Ask me something first, then say tell me more."
        else:
            instructions = build_system_prompt(
                session_attrs.get("audience", "general")
            ) + "\n\nThe user wants more detail on your previous answer. Expand helpfully in 3-5 sentences."
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
                speech = FALLBACK_MSG
            speech = sanitize_output(speech or FALLBACK_MSG)
        return (
            handler_input.response_builder.speak(speech)
            .set_card(SimpleCard("Bob", speech))
            .response
        )


class RepeatIntentHandler(AbstractRequestHandler):
    """Handle RepeatIntent - repeat last reply."""

    def can_handle(self, handler_input: HandlerInput) -> bool:
        return (
            handler_input.request_envelope.request.type == "IntentRequest"
            and getattr(
                handler_input.request_envelope.request.intent,
                "name",
                "",
            )
            == "RepeatIntent"
        )

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        session_attrs = handler_input.attributes_manager.session_attributes
        history = session_attrs.get("conversation", [])
        last = history[-1].get("assistant", "") if history else ""
        speech = last or "I don't have anything to repeat. Ask me something first."
        return (
            handler_input.response_builder.speak(speech)
            .set_card(SimpleCard("Bob", speech))
            .response
        )


class BuiltInIntentHandler(AbstractRequestHandler):
    """Handle AMAZON built-in intents (Help, Stop, Cancel, Fallback)."""

    def __init__(self, intent_name: str, speech: str):
        self.intent_name = intent_name
        self.speech = speech

    def can_handle(self, handler_input: HandlerInput) -> bool:
        req = handler_input.request_envelope.request
        if req.type != "IntentRequest":
            return False
        return getattr(req.intent, "name", "") == self.intent_name

    def handle(self, handler_input: HandlerInput) -> Response:
        log_intent(handler_input)
        return (
            handler_input.response_builder.speak(self.speech)
            .set_card(SimpleCard("Bob", self.speech))
            .response
        )


def _register_handlers(sb: SkillBuilder) -> SkillBuilder:
    sb.add_request_handler(AskAIIntentHandler())
    sb.add_request_handler(ShortenIntentHandler())
    sb.add_request_handler(MoreDetailIntentHandler())
    sb.add_request_handler(RepeatIntentHandler())
    sb.add_request_handler(
        BuiltInIntentHandler(
            "AMAZON.HelpIntent",
            "You can ask me questions like: what is the capital of France, "
            "or tell me a short story. Try asking anything.",
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
    return sb


sb = SkillBuilder()
_register_handlers(sb)
lambda_handler = sb.lambda_handler()
