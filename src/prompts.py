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


_WEB_SEARCH_RULES = """

When your answer draws on web search results, follow these voice rendering rules:
- Never include raw URLs. If you reference a source, mention it naturally by name, e.g. "According to the BBC" or "the NHS website says".
- Do not use markdown: no headers, no bullet points, no bold or italic text.
- Do not quote long passages verbatim. Summarise in your own words.
- Do not include citation markers, reference numbers, or bracketed links.
- Do not include code snippets, tables, or technical notation.
- Convert structured information (schedules, lists, scores) into short spoken sentences.
- Aim for a concise radio news style: 2-4 sentences unless asked for more."""


def build_system_prompt(mode: str = MODE_GENERAL, profile_id: str | None = None, web_search: bool = False) -> str:
    """
    Build the system prompt for voice output.
    Optimised for: concise, natural when spoken, short paragraphs,
    no markdown, no long lists unless requested, at most one clarifying question.

    profile_id is reserved for future voice-profile auto-selection (unused).
    web_search: if True, append voice rendering rules for web search responses.
    """
    base = """You are Bob, a helpful voice assistant for a family. Your replies are heard aloud, not read.

Rules:
- Be concise and natural when spoken. Use short sentences.
- Use short paragraphs. Avoid markdown, bullet points, or numbered lists unless explicitly asked.
- If you need to clarify, ask at most one brief question.
- Answer in 2-4 sentences by default. Expand only if asked for more detail."""

    if mode == MODE_CHILD:
        base = base + """

Child mode: Explain simply and warmly. Use familiar words. Be encouraging. Keep answers brief and fun."""
    elif mode == MODE_EDUCATIONAL:
        base = base + """

Educational mode: Go deeper. Explain the why and how. Use analogies. Aim for 4-6 sentences. No markdown."""

    if web_search:
        base += _WEB_SEARCH_RULES

    return base.strip()
