#!/bin/bash
# Re-enter ONE secret, hidden. Usage: scripts/put_secret.sh groq_api_key
set -euo pipefail
export AWS_REGION=us-east-1 AWS_PROFILE="${AWS_PROFILE:-llm-gateway}"
NAME="${1:?usage: put_secret.sh <name>}"
read -rsp "Paste $NAME ONCE, then press Enter (nothing will show): " V; echo
V="$(printf %s "$V" | tr -d '[:space:]')"
[ -n "$V" ] || { echo "empty, nothing saved"; exit 1; }
aws ssm put-parameter --name "/llm-gateway/$NAME" --type SecureString --tier Standard \
  --value "$V" --overwrite >/dev/null
echo "saved /llm-gateway/$NAME (length ${#V})"
