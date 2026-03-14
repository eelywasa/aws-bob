# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Bob is an Amazon Alexa custom skill with a Python AWS Lambda backend. It uses the OpenAI Responses API (not legacy Chat Completions) to answer questions in a voice-optimised format, designed for domestic/family use.

- **Runtime**: Python 3.11 on AWS Lambda (eu-west-1)
- **Deployment**: Serverless Framework (`serverless.yml`)
- **Alexa invokes Lambda directly** — no API Gateway
- **Secrets**: OpenAI API key stored in AWS Secrets Manager, fetched and cached at module level

## Commands

```bash
# Install dependencies
npm install
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_openai_client.py -v

# Deploy
npx serverless deploy
```

## Architecture

### Request flow

1. Alexa sends a JSON event to `src/handler.lambda_handler`
2. ASK SDK routes to the appropriate handler via `can_handle()` / `handle()`
3. `handle_user_utterance()` calls `openai_client.get_completion()` with the session history
4. Response is built using `ask()` (mic stays open) or `tell()` (mic closes)

### Key design decisions

**Two conversational modes:**
- `AskAIIntent` — one-shot Q&A, mic closes after response
- `ChatIntent` — conversational loop; uses `ElicitSlotDirective` to re-open mic without requiring the carrier phrase again

**Module-level caching in `openai_client.py`:** The httpx.Client (with HTTP/2) and the Secrets Manager API key are cached at module scope so warm Lambda invocations skip cold-start overhead.

**Session history** is stored in Alexa session attributes, capped at 4 turns. Last answer is also cached for `ShortenIntent`, `MoreDetailIntent`, and `RepeatIntent`.

**OpenAI Responses API** is used (not `/v1/chat/completions`). The response structure is nested differently — see `_extract_output_text()` in `openai_client.py`.

**Voice optimisation:** Responses must be plain prose — no markdown, no lists. `MAX_OUTPUT_TOKENS=280` enforces conciseness. The system prompt in `prompts.py` reinforces this.

### Source files

| File | Purpose |
|------|---------|
| `src/handler.py` | All Alexa intent handlers, session management, dialog elicitation |
| `src/openai_client.py` | OpenAI API calls, Secrets Manager caching, HTTP/2, retry logic |
| `src/prompts.py` | System prompt builder (audience-aware) |
| `src/safety.py` | Input validation and output sanitisation hooks |
| `src/util.py` | Structured logging (no transcript leakage), env helpers |
| `skill-package/interactionModels/custom/en-GB.json` | Alexa interaction model — intents, slots, dialog config |

## Development workflow

Improvements and new features are tracked in `BACKLOG.md`. The standard workflow for picking up a backlog item is:

1. **Read** `BACKLOG.md` and identify the next item to work on
2. **Plan** — enter plan mode and produce a detailed implementation plan covering architecture, files to change, and test strategy; review with the user before proceeding
3. **Implement** — make the code changes per the agreed plan
4. **Test** — run `pytest tests/ -v` and confirm all tests pass
5. **Deploy** — `npx serverless deploy`; push updated interaction model if intents changed; run smoke tests
6. **Commit and push** — commit all changes with a descriptive message and push to `origin/main`

When a backlog item is fully complete, note it as done in `BACKLOG.md` before moving on.

## Post-deploy configuration

After first deploy, set the OpenAI API key:

```bash
aws secretsmanager put-secret-value \
  --secret-id alexa-bob-dev/openai-api-key \
  --secret-string '{"OPENAI_API_KEY":"sk-your-openai-key"}'
```

## Alexa Developer Console

- Interaction model: `skill-package/interactionModels/custom/en-GB.json`
- Invocation name: "brainy bob"
- Skill endpoint: Lambda ARN (direct invocation, no API Gateway)
- Skill ID must match the `EventSourceToken` in `serverless.yml`

## ASK CLI

Install with `npm install -g ask-cli`, then `ask configure` to link your Amazon Developer account.

Use ASK CLI **only for interaction model sync and testing** — not `ask deploy`, which would conflict with the Serverless Framework Lambda setup.

```bash
# Push local interaction model to the console
ask smapi set-interaction-model -s <skill-id> -l en-GB -g development --interaction-model file:skill-package/interactionModels/custom/en-GB.json

# Pull interaction model from the console
ask smapi get-interaction-model -s <skill-id> -l en-GB -g development

# Simulate an utterance
ask simulate -t "ask brainy bob what is the speed of light" -l en-GB -s <skill-id>
```
