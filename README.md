# Bob — Alexa Custom Skill

Production-quality Amazon Alexa custom skill with a Python AWS Lambda backend, using OpenAI for AI-powered responses. Designed for domestic use (family setting).

## Architecture

- **Runtime**: Python 3.11 on AWS Lambda
- **Deployment**: Serverless Framework
- **Region**: eu-west-2 (London)
- **AI**: OpenAI Responses API (not legacy Chat Completions)
- **Secrets**: API key stored in AWS Secrets Manager
- **Invocation**: Alexa invokes Lambda directly (no API Gateway)

## Project structure

```
src/
  handler.py        # Alexa ASK SDK entrypoint, all intents
  openai_client.py  # OpenAI Responses API, httpx, Secrets Manager
  prompts.py        # System prompt builder
  safety.py         # Optional content guardrails
  util.py           # Helpers, structured logging
serverless.yml
requirements.txt
skill-package/      # Interaction model for Alexa Developer Console
tests/
```

## Setup

1. **Install dependencies**

   ```bash
   npm install
   pip install -r requirements.txt
   ```

2. **Deploy**

   ```bash
   npx serverless deploy
   ```

3. **Configure secret**

   After first deploy, update the secret in AWS Secrets Manager:

   ```bash
   aws secretsmanager put-secret-value \
     --secret-id alexa-bob-dev/openai-api-key \
     --secret-string '{"OPENAI_API_KEY":"sk-your-openai-key"}'
   ```

4. **Create skill in Alexa Developer Console**

   - Create a new custom skill
   - Use the interaction model from `skill-package/interactionModels/custom/en-GB.json`
   - Set the skill endpoint to your Lambda ARN (direct invocation)
   - Invocation name: "Bob"

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `MAX_OUTPUT_TOKENS` | `280` | Hard cap on output length |
| `OPENAI_REQUEST_TIMEOUT` | `10` | Request timeout (seconds) |

## Intents

- **AskAIIntent** — Main AI Q&A (slot: `utterance`, type `AMAZON.SearchQuery`)
- **ShortenIntent** — Shorter version of last answer
- **MoreDetailIntent** — Expand on last answer
- **RepeatIntent** — Repeat last answer
- **AMAZON.HelpIntent**, **AMAZON.StopIntent**, **AMAZON.CancelIntent**, **AMAZON.FallbackIntent**

## Tests

```bash
pytest tests/ -v
```

## Future extensions

- Dynamic audience mode (child vs adult)
- Tool calling for web search
- Optional DynamoDB-based memory (opt-in)
