# Observability

## Latency metrics

Every AI request emits an [Embedded Metric Format (EMF)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Specification.html) JSON object to stdout. CloudWatch Logs automatically extracts these as custom metrics — no SDK or extra infrastructure required.

Metrics appear under **CloudWatch → Metrics → Custom Namespaces → BrainyBob**.

### Metrics emitted

| Metric | Unit | Description |
|--------|------|-------------|
| `total_duration_ms` | Milliseconds | End-to-end request time |
| `openai_duration_ms` | Milliseconds | OpenAI API call time (including retries) |
| `ddb_load_ms` | Milliseconds | DynamoDB `GetItem` time (`null` on warm session) |
| `ddb_save_ms` | Milliseconds | DynamoDB `PutItem` time (`null` on AI failure) |

### Dimensions

| Dimension | Values | Description |
|-----------|--------|-------------|
| `intent` | `ChatIntent`, `AskAIIntent`, … | Alexa intent that triggered the request |
| `cold_start` | `"true"` / `"false"` | Whether the Lambda container was cold |

`null` metrics are omitted from the payload rather than emitted as zero, so they do not skew CloudWatch averages.

---

## Useful CloudWatch Logs Insights queries

Run these against the `/aws/lambda/alexa-bob-dev-alexa` log group.

### Latency breakdown by intent

```
fields @timestamp, intent, total_duration_ms, openai_duration_ms, ddb_load_ms, cold_start
| filter ispresent(total_duration_ms)
| stats avg(total_duration_ms), p90(total_duration_ms), p99(total_duration_ms) by intent
```

### Cold vs warm comparison

```
fields @timestamp, total_duration_ms, cold_start
| filter ispresent(total_duration_ms)
| stats avg(total_duration_ms), p90(total_duration_ms) by cold_start
```

### OpenAI vs DynamoDB time split

```
fields @timestamp, openai_duration_ms, ddb_load_ms, ddb_save_ms
| filter ispresent(total_duration_ms)
| stats avg(openai_duration_ms), avg(ddb_load_ms), avg(ddb_save_ms) by bin(1h)
```

### Slow requests

```
fields @timestamp, intent, total_duration_ms, cold_start
| filter total_duration_ms > 3000
| sort total_duration_ms desc
| limit 20
```

---

## Suggested CloudWatch dashboard widgets

- **Line chart**: `avg(total_duration_ms)` by `intent` over 24h
- **Stacked bar**: `avg(openai_duration_ms)` + `avg(ddb_load_ms)` per hour
- **Single value**: `avg(total_duration_ms)` filtered to `cold_start = "true"` vs `"false"`

---

## Structured logs

All log output uses structured JSON fields via `util.logger`. Fields are nested under the `structured` key to avoid CloudWatch Logs Insights parsing ambiguity. No user transcript content is logged.

Example:

```json
{"level": "WARNING", "message": "OpenAI request failed", "structured": {"error_type": "TimeoutException"}}
```
