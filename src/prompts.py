"""System prompt builder for voice-optimised responses."""

from __future__ import annotations

# Audience modes for future extension (child vs adult)
AUDIENCE_DEFAULT = "general"
AUDIENCE_CHILD = "child"


def build_system_prompt(audience_mode: str = AUDIENCE_DEFAULT) -> str:
    """
    Build the system prompt for voice output.
    Optimised for: concise, natural when spoken, short paragraphs,
    no markdown, no long lists unless requested, at most one clarifying question.
    """
    base = """You are Bob, a helpful voice assistant for a family. Your replies are heard aloud, not read.

Rules:
- Be concise and natural when spoken. Use short sentences.
- Use short paragraphs. Avoid markdown, bullet points, or numbered lists unless explicitly asked.
- If you need to clarify, ask at most one brief question.
- Answer in 2-4 sentences by default. Expand only if asked for more detail."""

    if audience_mode == AUDIENCE_CHILD:
        return base + """

Child mode: Explain simply and warmly. Use familiar words. Be encouraging. Keep answers brief and fun."""
    return base
