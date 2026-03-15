#!/usr/bin/env bash
# Usage: ./scripts/set-env.sh KEY=VALUE [KEY=VALUE ...]
# Patches one or more Lambda environment variables without a full redeploy.
# Example: ./scripts/set-env.sh ENABLE_WEB_SEARCH=false PROGRESSIVE_MIN_WORDS=5
set -euo pipefail

FUNCTION="alexa-bob-dev-alexa"
REGION="eu-west-1"

if [[ $# -eq 0 ]]; then
  echo "Usage: $0 KEY=VALUE [KEY=VALUE ...]"
  echo ""
  echo "Patchable variables:"
  echo "  ENABLE_WEB_SEARCH           true|false"
  echo "  ENABLE_PROGRESSIVE_RESPONSE true|false"
  echo "  ENABLE_MEMORY               true|false"
  echo "  OPENAI_MODEL                e.g. gpt-4o-mini"
  echo "  MAX_OUTPUT_TOKENS           e.g. 280"
  echo "  OPENAI_REQUEST_TIMEOUT      seconds, e.g. 10"
  echo "  OPENAI_SEARCH_TIMEOUT       seconds, e.g. 7"
  echo "  PROGRESSIVE_MIN_WORDS       e.g. 8"
  exit 1
fi

# Fetch current env vars
current=$(aws lambda get-function-configuration \
  --function-name "$FUNCTION" \
  --region "$REGION" \
  --query 'Environment.Variables' \
  --output json)

# Merge in the supplied KEY=VALUE pairs
merged=$(python3 - "$current" "$@" <<'EOF'
import json, sys
vars = json.loads(sys.argv[1])
for arg in sys.argv[2:]:
    k, v = arg.split("=", 1)
    vars[k] = v
print(json.dumps({"Variables": vars}))
EOF
)

echo "Applying: $*"
aws lambda update-function-configuration \
  --function-name "$FUNCTION" \
  --region "$REGION" \
  --environment "$merged" \
  --query 'LastUpdateStatus' \
  --output text

aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
echo "Done."
