#!/bin/bash
# Stores llm-gateway secrets in SSM Parameter Store: Standard tier, SecureString,
# default AWS-managed key (alias/aws/ssm). Run it yourself in a separate terminal.
# Your typing is hidden and nothing secret is printed (the admin key goes to
# ~/.llm-gateway/admin_key and your clipboard). Re-runnable: empty input = skip.
#
# Each secret is stored with:
#   aws ssm put-parameter --name /llm-gateway/<name> --type SecureString \
#       --tier Standard --value <secret> --overwrite
set -euo pipefail
export AWS_REGION=us-east-1
export AWS_PROFILE="${AWS_PROFILE:-llm-gateway}"
P=/llm-gateway

put() { # <name> <value>
  aws ssm put-parameter --name "$P/$1" --type SecureString --tier Standard \
    --value "$2" --overwrite >/dev/null
  echo "  saved $P/$1"
}

ask() { # <name> <prompt>
  local v
  read -rsp "$2 (Enter to skip): " v; echo
  if [ -n "$v" ]; then put "$1" "$v"; else echo "  skipped $P/$1"; fi
}

aws sts get-caller-identity --query Account --output text >/dev/null \
  || { echo "Not logged in. Run: aws login --profile llm-gateway"; exit 1; }

ask groq_api_key   "Groq API key"
ask gemini_api_key "Gemini API key"

read -rsp "Telegram bot token from BotFather (Enter to skip): " TG; echo
if [ -n "$TG" ]; then
  put telegram_bot_token "$TG"
  echo "  Looking up your chat_id (you must have sent 'hi' to your bot first)..."
  CHAT_ID="$( (curl -fsS --max-time 10 "https://api.telegram.org/bot${TG}/getUpdates" 2>/dev/null || echo "{}") | python3 -c '
import sys, json
r = json.load(sys.stdin).get("result", [])
ids = [u["message"]["chat"]["id"] for u in r
       if "message" in u and u["message"]["chat"].get("type") == "private"]
print(ids[-1] if ids else "")')"
  if [ -z "$CHAT_ID" ]; then
    echo "  Could not get chat_id (no 'hi' message yet, or this network blocks api.telegram.org)."
    echo "  Get it from @userinfobot in Telegram, then run: scripts/put_chat_id.sh"
  else
    put telegram_chat_id "$CHAT_ID"
  fi
  # Telegram sends this back in X-Telegram-Bot-Api-Secret-Token; only [A-Za-z0-9_-] allowed.
  aws ssm get-parameter --name "$P/telegram_webhook_secret" >/dev/null 2>&1 \
    || put telegram_webhook_secret "$(openssl rand -hex 32)"
fi
unset TG

# Server-side secret the demo runner / background traffic use to derive the
# demo agents' gateway keys (so no demo key is ever stored anywhere).
aws ssm get-parameter --name "$P/demo_key_secret" >/dev/null 2>&1 \
  || put demo_key_secret "$(openssl rand -hex 32)"

# Admin key: never printed. Saved to ~/.llm-gateway/admin_key (only you can
# read it, outside the repo) and copied to your clipboard. SSM keeps only its hash.
KEYFILE="$HOME/.llm-gateway/admin_key"
if aws ssm get-parameter --name "$P/admin_key_hash" >/dev/null 2>&1 && [ "${ROTATE_ADMIN:-0}" != 1 ]; then
  echo "  admin_key_hash already exists (re-run with ROTATE_ADMIN=1 to replace it)"
else
  mkdir -p "$HOME/.llm-gateway" && chmod 700 "$HOME/.llm-gateway"
  ADMIN_KEY="adm_$(openssl rand -hex 24)"
  put admin_key_hash "$(printf %s "$ADMIN_KEY" | shasum -a 256 | cut -d' ' -f1)"
  (umask 077 && printf %s "$ADMIN_KEY" > "$KEYFILE")
  printf %s "$ADMIN_KEY" | pbcopy 2>/dev/null || true
  unset ADMIN_KEY
  echo "  admin key saved to $KEYFILE (chmod 600) and copied to your clipboard."
  echo "  Paste it into your password manager now as a backup."
fi

echo "Stored parameters:"
aws ssm describe-parameters --parameter-filters "Key=Name,Option=BeginsWith,Values=$P/" \
  --query 'Parameters[].[Name,Type,Tier]' --output table
