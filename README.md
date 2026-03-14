# Brainy Bob — Alexa Custom Skill

An Amazon Alexa custom skill with a Python AWS Lambda backend. Uses the OpenAI Responses API to answer questions in a voice-optimised format, designed for domestic/family use.

## Architecture overview

```
User voice
    │
    ▼
Alexa NLU ──► Lambda (src/handler.py)
                   │
                   ├── src/memory.py      ◄──► DynamoDB (cross-session turns + mode)
                   ├── src/openai_client.py ◄──► OpenAI Responses API
                   ├── src/prompts.py     (system prompt + mode logic)
                   └── src/safety.py      (input/output sanitisation)
```

- **Runtime**: Python 3.11 on AWS Lambda (eu-west-1)
- **Deployment**: Serverless Framework v3
- **AI**: OpenAI Responses API (`/v1/responses`) — not the legacy Chat Completions endpoint
- **Secrets**: OpenAI API key stored in AWS Secrets Manager, cached at module level
- **Invocation**: Alexa invokes Lambda directly — no API Gateway

## Project structure

```
src/
  handler.py        # ASK SDK entrypoint, all intent handlers
  openai_client.py  # OpenAI Responses API, HTTP/2, Secrets Manager caching, retry logic
  prompts.py        # System prompt builder (mode-aware)
  memory.py         # DynamoDB-backed cross-session turn and mode persistence
  safety.py         # Input validation and output sanitisation
  util.py           # Structured logging, env helpers
skill-package/
  interactionModels/custom/en-GB.json   # Alexa interaction model
tests/
  test_handler.py
  test_memory.py
  test_openai_client.py
  test_prompts.py
  test_safety.py
serverless.yml
requirements.txt
```

## Intents

| Intent | Description |
|--------|-------------|
| `ChatIntent` | Conversational loop; uses `ElicitSlotDirective` to keep mic open between turns |
| `AskAIIntent` | One-shot Q&A; mic closes after response |
| `SetModeIntent` | Switch conversational mode by voice (see Modes below) |
| `ShortenIntent` | Ask for a shorter version of the last answer |
| `MoreDetailIntent` | Expand on the last answer |
| `RepeatIntent` | Repeat last answer without calling OpenAI |
| `AMAZON.HelpIntent` | Usage hint |
| `AMAZON.StopIntent` / `AMAZON.CancelIntent` | End session |
| `AMAZON.FallbackIntent` | Catch-all for unrecognised speech |

## Conversational modes

Bob has three modes, switchable by voice and persisted per-user in DynamoDB:

| Mode | Voice trigger examples | Behaviour |
|------|----------------------|-----------|
| `general` (default) | "switch to general mode" | Concise 2–4 sentence answers |
| `child` | "switch to kids mode", "use simple mode" | Warm, simple language; brief and fun |
| `educational` | "switch to educational mode", "use detailed mode" | Deeper explanations with analogies; 4–6 sentences |

Mode preference survives across sessions — the last mode set is restored at the start of each new session.

## Cross-session memory

Conversation history is persisted to DynamoDB (`alexa-bob-{stage}-memory` table) per Alexa user ID:

- Up to **20 turns** stored; the last **10** are injected as context at the start of each session
- Mode preference stored alongside turns in the same item
- **90-day TTL** — items expire automatically
- Feature-flagged via `ENABLE_MEMORY` env var (default: `true`)
- `save_turns` uses `PutItem` (full item write after each AI response)
- `save_mode` uses `UpdateItem` (mode-only patch, leaves turns untouched)

## Key design decisions

**Module-level caching** — the `httpx.Client` (HTTP/2) and the Secrets Manager API key are cached at module scope. Warm Lambda invocations skip cold-start overhead entirely.

**OpenAI Responses API** — uses `/v1/responses` not `/v1/chat/completions`. The response structure differs: output text is nested under `output[].content[].text` with `type == "output_text"`. See `_extract_output_text()` in `openai_client.py`.

**Dialog elicitation** — `ChatIntent` uses `ElicitSlotDirective` to re-open the microphone after every response without requiring the user to say the invocation phrase again.

**Voice optimisation** — all responses must be plain prose. No markdown, no bullet lists. `MAX_OUTPUT_TOKENS=280` enforces conciseness. The system prompt in `prompts.py` reinforces this.

**Retry logic** — `get_completion()` retries once on HTTP 429 or 5xx with a 100 ms backoff. Network errors (`NetworkError`, `RemoteProtocolError`) also trigger a single retry.

**Progressive response** — when web search is enabled, a `VoicePlayer.Speak` directive fires immediately ("Let me look that up") to reduce perceived latency while the Lambda is still running.

---

## Setup

### Prerequisites

- Node.js (for Serverless Framework and ASK CLI)
- Python 3.11+
- AWS CLI configured with appropriate credentials
- An Alexa Developer account

### 1. Install dependencies

```bash
npm install
pip install -r requirements.txt
```

### 2. Deploy

```bash
npx serverless deploy
# or for a specific stage:
npx serverless deploy --stage prod
```

This creates the Lambda function, DynamoDB table, Secrets Manager secret, and IAM roles via CloudFormation.

### 3. Configure the OpenAI API key

After first deploy, update the placeholder secret:

```bash
aws secretsmanager put-secret-value \
  --secret-id alexa-bob-dev/openai-api-key \
  --secret-string '{"OPENAI_API_KEY":"sk-your-openai-key"}'
```

### 4. Create and configure the Alexa skill

1. Go to the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask) and create a new custom skill
2. Set the invocation name to **brainy bob**
3. Set the skill endpoint to your Lambda ARN (use direct Lambda invocation, not HTTPS)
4. Copy the Skill ID and update `EventSourceToken` in `serverless.yml`, then redeploy
5. Push the interaction model (see below)

### 5. Push the interaction model

Install ASK CLI if not already done:

```bash
npm install -g ask-cli
ask configure   # link your Amazon Developer account
```

Push the local model to the console:

```bash
ask smapi set-interaction-model \
  -s <skill-id> -l en-GB -g development \
  --interaction-model file:skill-package/interactionModels/custom/en-GB.json
```

The model build takes ~30 seconds. Check status:

```bash
ask smapi get-skill-status -s <skill-id>
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model to use |
| `MAX_OUTPUT_TOKENS` | `280` | Hard cap on response length |
| `OPENAI_REQUEST_TIMEOUT` | `10` | Timeout (seconds) for standard requests |
| `OPENAI_SECRET_ARN` | _(set by CloudFormation)_ | ARN of the Secrets Manager secret |
| `ENABLE_WEB_SEARCH` | `false` | Enable OpenAI `web_search_preview` tool |
| `OPENAI_SEARCH_TIMEOUT` | `7` | Timeout (seconds) for web search requests |
| `ENABLE_MEMORY` | `true` | Enable DynamoDB cross-session memory |
| `MEMORY_TABLE` | _(set by CloudFormation)_ | DynamoDB table name |

---

## Running tests

```bash
pytest tests/ -v
```

All tests run without AWS credentials — DynamoDB and Secrets Manager calls are mocked. The test suite covers all intent handlers, memory persistence, OpenAI client retry/timeout behaviour, and safety guards.

---

## Post-deploy configuration

### Update the OpenAI model or token limit

Edit `serverless.yml` and redeploy, or set env vars before deploying:

```bash
OPENAI_MODEL=gpt-4o MAX_OUTPUT_TOKENS=400 npx serverless deploy
```

### Enable web search

```bash
ENABLE_WEB_SEARCH=true npx serverless deploy
```

### Disable cross-session memory

```bash
ENABLE_MEMORY=false npx serverless deploy
```

---

## Future extensions

- Auto-select mode based on recognised Alexa voice profile (`profile_id` hook is already in `build_system_prompt`)
- Additional language models / model routing per mode
- Multi-language interaction model support
