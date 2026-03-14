# Architecture

## Overview

```
User voice
    │
    ▼
Alexa NLU ──► Lambda (src/handler.py)
                   │
                   ├── src/memory.py        ◄──► DynamoDB (cross-session turns + mode)
                   ├── src/openai_client.py ◄──► OpenAI Responses API
                   ├── src/prompts.py       (system prompt + mode logic)
                   ├── src/phrases.py       (progressive response phrases, SSM-backed)
                   ├── src/telemetry.py     (EMF latency metrics → CloudWatch)
                   └── src/safety.py        (input/output sanitisation)
```

- **Runtime**: Python 3.11 on AWS Lambda (eu-west-1)
- **Deployment**: Serverless Framework v3
- **AI**: OpenAI Responses API (`/v1/responses`) — not the legacy Chat Completions endpoint
- **Secrets**: OpenAI API key stored in AWS Secrets Manager, cached at module level
- **Invocation**: Alexa invokes Lambda directly — no API Gateway

---

## Project structure

```
src/
  handler.py        # ASK SDK entrypoint, all intent handlers
  openai_client.py  # OpenAI Responses API, HTTP/2, Secrets Manager caching, retry logic
  prompts.py        # System prompt builder (mode-aware)
  memory.py         # DynamoDB-backed cross-session turn and mode persistence
  phrases.py        # Progressive response phrase management (SSM-backed, cached)
  telemetry.py      # Cold-start detection, EMF metric emission
  safety.py         # Input validation and output sanitisation
  util.py           # Structured logging, env helpers
skill-package/
  interactionModels/custom/en-GB.json   # Alexa interaction model
tests/
  test_handler.py
  test_memory.py
  test_openai_client.py
  test_phrases.py
  test_prompts.py
  test_safety.py
  test_telemetry.py
serverless.yml
requirements.txt
```

---

## Intents

| Intent | Description |
|--------|-------------|
| `ChatIntent` | Conversational loop; uses `ElicitSlotDirective` to keep mic open between turns |
| `AskAIIntent` | One-shot Q&A; mic closes after response |
| `SetModeIntent` | Switch conversational mode by voice |
| `ShortenIntent` | Ask for a shorter version of the last answer |
| `MoreDetailIntent` | Expand on the last answer |
| `RepeatIntent` | Repeat last answer without calling OpenAI |
| `AMAZON.HelpIntent` | Usage hint |
| `AMAZON.StopIntent` / `AMAZON.CancelIntent` | End session |
| `AMAZON.FallbackIntent` | Catch-all for unrecognised speech |

---

## Conversational modes

Bob has three modes, switchable by voice and persisted per-user in DynamoDB:

| Mode | Voice trigger examples | Behaviour |
|------|----------------------|-----------|
| `general` (default) | "switch to general mode" | Concise 2–4 sentence answers |
| `child` | "switch to kids mode", "use simple mode" | Warm, simple language; brief and fun |
| `educational` | "switch to educational mode", "use detailed mode" | Deeper explanations with analogies; 4–6 sentences |

Mode preference survives across sessions — the last mode set is restored at the start of each new session.

---

## Cross-session memory

Conversation history is persisted to DynamoDB (`alexa-bob-{stage}-memory` table) per Alexa user ID:

- Up to **20 turns** stored; the last **10** are injected as context at the start of each session
- Mode preference stored alongside turns in the same item
- **90-day TTL** — items expire automatically
- Feature-flagged via `ENABLE_MEMORY` env var (default: `true`)
- `save_turns` uses `PutItem` (full item write after each AI response)
- `save_mode` uses `UpdateItem` (mode-only patch, leaves turns untouched)

---

## Key design decisions

**Module-level caching** — the `httpx.Client` (HTTP/2) and the Secrets Manager API key are cached at module scope. Warm Lambda invocations skip cold-start overhead entirely.

**OpenAI Responses API** — uses `/v1/responses` not `/v1/chat/completions`. The response structure differs: output text is nested under `output[].content[].text` with `type == "output_text"`. See `_extract_output_text()` in `openai_client.py`.

**Dialog elicitation** — `ChatIntent` uses `ElicitSlotDirective` to re-open the microphone after every response without requiring the user to say the invocation phrase again.

**Voice optimisation** — all responses must be plain prose. No markdown, no bullet lists. `MAX_OUTPUT_TOKENS=280` enforces conciseness. The system prompt in `prompts.py` reinforces this.

**Retry logic** — `get_completion()` retries once on HTTP 429 or 5xx with a 100 ms backoff. Network errors (`NetworkError`, `RemoteProtocolError`) also trigger a single retry.

**Progressive response** — a `VoicePlayer.Speak` directive fires immediately before the OpenAI call to reduce perceived latency. Phrases are context-aware (question vs conversational) and suppressed for short utterances. Stored in SSM Parameter Store and updatable without redeploying.

**Latency telemetry** — Embedded Metric Format (EMF) JSON is printed to stdout on every AI request. CloudWatch automatically extracts these as custom metrics under the `BrainyBob` namespace, split by intent and cold/warm start.
