# Brainy Bob — Alexa Custom Skill

An Amazon Alexa custom skill with a Python AWS Lambda backend. Uses the OpenAI Responses API to answer questions in a voice-optimised format, designed for domestic/family use.

- **Invocation**: "Alexa, open Brainy Bob"
- **Runtime**: Python 3.11 · AWS Lambda (eu-west-1) · Serverless Framework v3
- **AI**: OpenAI Responses API · DynamoDB cross-session memory · CloudWatch EMF metrics

## Quick start

```bash
npm install && pip install -r requirements.txt
npx serverless deploy
pytest tests/ -v
```

See [docs/setup.md](docs/setup.md) for the full first-time setup guide including Alexa skill creation and interaction model deployment.

## Documentation

| Doc | Contents |
|-----|----------|
| [docs/architecture.md](docs/architecture.md) | System design, intents, conversational modes, memory, key decisions |
| [docs/setup.md](docs/setup.md) | Prerequisites, deployment, Alexa skill setup, running tests |
| [docs/configuration.md](docs/configuration.md) | Environment variables and common configuration tasks |
| [docs/observability.md](docs/observability.md) | CloudWatch metrics, Logs Insights queries, structured logging |
| [docs/backlog.md](docs/backlog.md) | Phased feature backlog and roadmap |

## Licence

MIT — see [LICENSE](LICENSE).
