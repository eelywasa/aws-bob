"""System prompt builder for voice-optimised responses."""

from __future__ import annotations

MODE_GENERAL = "general"
MODE_CHILD = "child"
MODE_EDUCATIONAL = "educational"

VALID_MODES = frozenset({MODE_GENERAL, MODE_CHILD, MODE_EDUCATIONAL})

_MODE_DISPLAY = {
    MODE_GENERAL: "general",
    MODE_CHILD: "kids",
    MODE_EDUCATIONAL: "educational",
}

# Deprecated aliases — kept for backward compatibility
AUDIENCE_DEFAULT = MODE_GENERAL
AUDIENCE_CHILD = MODE_CHILD


def build_system_prompt(mode: str = MODE_GENERAL, profile_id: str | None = None) -> str:
    """
    Build the system prompt for voice output.
    Optimised for: concise, natural when spoken, short paragraphs,
    no markdown, no long lists unless requested, at most one clarifying question.

    profile_id is reserved for future voice-profile auto-selection (unused).
    """
    base = """You are Bob, a helpful voice assistant for a family. Your replies are heard aloud, not read.

Rules:
- Be concise and natural when spoken. Use short sentences.
- Use short paragraphs. Avoid markdown, bullet points, or numbered lists unless explicitly asked.
- If you need to clarify, ask at most one brief question.
- Answer in 2-4 sentences by default. Expand only if asked for more detail."""

    if mode == MODE_CHILD:
        return base + """

Child mode: Explain simply and warmly. Use familiar words. Be encouraging. Keep answers brief and fun."""

    if mode == MODE_EDUCATIONAL:
        return base + """

Educational mode: Go deeper. Explain the why and how. Use analogies. Aim for 4-6 sentences. No markdown."""

    return base
