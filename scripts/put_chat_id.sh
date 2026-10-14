#!/bin/bash
# Stores your Telegram chat_id (from @userinfobot) in SSM. Use when the main
# script couldn't look it up (e.g. a network that blocks api.telegram.org).
set -euo pipefail
export AWS_REGION=us-east-1 AWS_PROFILE="${AWS_PROFILE:-llm-gateway}"
read -rp "Your Telegram chat id (numbers only): " CID
[[ "$CID" =~ ^-?[0-9]+$ ]] || { echo "Not a number."; exit 1; }
aws ssm put-parameter --name /llm-gateway/telegram_chat_id --type SecureString \
  --tier Standard --value "$CID" --overwrite >/dev/null
echo "saved /llm-gateway/telegram_chat_id"
