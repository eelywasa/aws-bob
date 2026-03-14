# Setup and Deployment

## Prerequisites

- Node.js (for Serverless Framework and ASK CLI)
- Python 3.11+
- AWS CLI configured with appropriate credentials
- An Alexa Developer account

---

## 1. Install dependencies

```bash
npm install
pip install -r requirements.txt
```

---

## 2. Deploy to AWS

```bash
npx serverless deploy
# or for a specific stage:
npx serverless deploy --stage prod
```

This creates via CloudFormation:
- Lambda function (Python 3.11, 1024 MB)
- DynamoDB table for cross-session memory
- Secrets Manager secret for the OpenAI API key
- SSM Parameters for progressive response phrases
- IAM roles with least-privilege policies

---

## 3. Configure the OpenAI API key

After first deploy, update the placeholder secret:

```bash
aws secretsmanager put-secret-value \
  --secret-id alexa-bob-dev/openai-api-key \
  --secret-string '{"OPENAI_API_KEY":"sk-your-openai-key"}'
```

---

## 4. Create and configure the Alexa skill

1. Go to the [Alexa Developer Console](https://developer.amazon.com/alexa/console/ask) and create a new custom skill
2. Set the invocation name to **brainy bob**
3. Set the skill endpoint to your Lambda ARN (use direct Lambda invocation, not HTTPS)
4. Copy the Skill ID and update `EventSourceToken` in `serverless.yml`, then redeploy

---

## 5. Push the interaction model

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

> **Note:** Use ASK CLI only for interaction model sync and testing — not `ask deploy`, which would conflict with the Serverless Framework Lambda setup.

---

## Running tests

All tests run without AWS credentials — external calls are mocked.

```bash
# Run all tests
pytest tests/ -v

# Run a single file
pytest tests/test_handler.py -v
```
