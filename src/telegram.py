"""Telegram Bot API over urllib (used only by the bot Lambda)."""
import json
import urllib.request

import store

API = "https://api.telegram.org/bot{token}/{method}"


def call(method, payload, timeout=8):
    token = store.param("telegram_bot_token")
    if not token:
        return None
    req = urllib.request.Request(API.format(token=token, method=method),
                                 data=json.dumps(payload).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def send(text, chat_id=None):
    chat_id = chat_id or store.param("telegram_chat_id", cache_s=60)
    if not chat_id:
        return None
    return call("sendMessage", {"chat_id": chat_id, "text": text[:4000],
                                "disable_web_page_preview": True})
