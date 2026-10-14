#!/bin/bash
# Saves the Telegram bot token and your chat id to SSM (hidden input, nothing printed).
set -euo pipefail
D="$(cd "$(dirname "$0")" && pwd)"
echo "Step 1/2: paste the FULL bot token from BotFather (like 123456789:AAE...), once."
bash "$D/put_secret.sh" telegram_bot_token
echo "Step 2/2: your chat id is the number @userinfobot shows you in Telegram."
bash "$D/put_chat_id.sh"
echo "Done. Telegram is set up."
