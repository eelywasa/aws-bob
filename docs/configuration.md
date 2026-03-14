# Configuration

## Environment variables

All variables are set in `serverless.yml` and can be overridden at deploy time via environment variables.

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
| `ENABLE_PROGRESSIVE_RESPONSE` | `true` | Enable spoken acknowledgement before AI call |
| `PROGRESSIVE_MIN_WORDS` | `8` | Minimum utterance word count to trigger progressive response |
| `PROGRESSIVE_QUESTION_PHRASES_PARAM` | _(set by CloudFormation)_ | SSM parameter name for question phrases |
| `PROGRESSIVE_CHAT_PHRASES_PARAM` | _(set by CloudFormation)_ | SSM parameter name for chat phrases |

---

## Common configuration tasks

### Change the OpenAI model or token limit

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

### Disable progressive responses

```bash
ENABLE_PROGRESSIVE_RESPONSE=false npx serverless deploy
```

### Tune the short-utterance cutoff

Progressive responses are suppressed for utterances below `PROGRESSIVE_MIN_WORDS` words (default: 8):

```bash
PROGRESSIVE_MIN_WORDS=5 npx serverless deploy
```

---

## Updating progressive response phrases (no redeploy needed)

Phrases are stored in SSM Parameter Store and loaded on Lambda cold start. Update them at any time:

```bash
# Question-type utterances (what/why/how/when/where/who…)
aws ssm put-parameter \
  --name /alexa-bob/dev/progressive-question-phrases \
  --value '["Let me think about that.", "Good question, let me think.", "One moment."]' \
  --type String --overwrite --region eu-west-1

# Conversational utterances
aws ssm put-parameter \
  --name /alexa-bob/dev/progressive-chat-phrases \
  --value '["Let me think about that.", "Hmm, let me think."]' \
  --type String --overwrite --region eu-west-1
```

Changes take effect on the next Lambda cold start. The value must be a JSON array of non-empty strings.
