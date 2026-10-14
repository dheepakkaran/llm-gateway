"""Telegram ops-console Lambda (private). Three kinds of events:

  1. Telegram webhook via its Function URL: verify the secret header, accept
     commands only from the admin chat_id, then run /status /agents /kill ...
  2. {"type": "alert", "text": ...}   async-invoked by the gateway
  3. {"type": "daily_report"}         from EventBridge Scheduler
  4. {"type": "register_webhook", "url": ...}  run once from your laptop
"""
import hmac
import json
import logging
import os
import time

import config
import incidents as inc_mod
import stats
import store
import telegram

log = logging.getLogger()
log.setLevel(logging.INFO)
GATEWAY_FN = os.environ.get("GATEWAY_FUNCTION", "")

HELP = ("Commands:\n/status - totals and suspended agents\n/agents - all agents\n"
        "/kill <id>\n/resume <id>\n/killall\n/unkillall\n/incidents - last 10")


def _ok():
    return {"statusCode": 200, "body": "ok"}


def handler(event, context):
    kind = event.get("type")
    if kind == "alert":
        telegram.send(event["text"])
        return {"sent": True}
    if kind == "daily_report":
        telegram.send(daily_report(time.time()))
        return {"sent": True}
    if kind == "register_webhook":
        secret = store.param("telegram_webhook_secret")
        r = telegram.call("setWebhook", {"url": event["url"], "secret_token": secret,
                                         "allowed_updates": ["message"],
                                         "drop_pending_updates": True})
        return {"ok": bool(r and r.get("ok")), "description": (r or {}).get("description")}
    return webhook(event)


def webhook(event):
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    secret = store.param("telegram_webhook_secret") or ""
    got = headers.get("x-telegram-bot-api-secret-token", "")
    if not secret or not hmac.compare_digest(got, secret):
        return {"statusCode": 401, "body": "unauthorized"}
    try:
        update = json.loads(event.get("body") or "{}")
    except ValueError:
        return _ok()
    msg = update.get("message") or {}
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    admin_chat = store.param("telegram_chat_id", cache_s=60) or ""
    if chat_id and not admin_chat:
        # Setup mode only (no admin chat saved yet): tell the sender their own id.
        telegram.send(f"Your chat id is {chat_id}. Save it with scripts/put_chat_id.sh "
                      "and this bot will accept commands only from you.", chat_id)
        return _ok()
    if not chat_id or chat_id != admin_chat:
        log.info(json.dumps({"event": "ignored_chat"}))
        return _ok()  # silently ignore everyone else
    text = (msg.get("text") or "").strip()
    try:
        reply = command(text, time.time())
    except Exception:
        log.exception("command failed")
        reply = "Command failed; check CloudWatch logs."
    telegram.send(reply, chat_id)
    return _ok()


def _gateway_admin(path):
    """Admin actions go through the gateway Lambda (direct invoke, IAM-authorised)
    so state-change logic lives in exactly one place."""
    r = store._client("lambda").invoke(
        FunctionName=GATEWAY_FN, InvocationType="RequestResponse",
        Payload=json.dumps({"internal_admin": path}).encode())
    return json.loads(r["Payload"].read() or b"{}")


def command(text, now):
    parts = text.split()
    cmd = parts[0].split("@")[0].lower() if parts else ""
    arg = parts[1] if len(parts) > 1 else ""
    if cmd in ("/start", "/help"):
        return HELP
    if cmd == "/status":
        s = stats.rebuild(now)
        c = s["counters"]
        stopped = [a for a in s["agents"] if a["status"] != "ACTIVE"]
        lines = [f"Requests: {c['total_requests']} | blocked: {c['blocked_calls']} | "
                 f"est. cost avoided: ${c['est_cost_avoided']:.4f}",
                 f"Kill switch: {store.param('kill_all', decrypt=False, cache_s=0) or 'off'}"]
        lines += [f"{a['id']}: {a['status']}" + (f" ({a['cooldown_left_s']}s left)"
                                                 if a["cooldown_left_s"] else "") for a in stopped]
        return "\n".join(lines if stopped else lines + ["All agents ACTIVE."])
    if cmd == "/agents":
        s = stats.rebuild(now)
        return "\n".join(f"{a['id']} [{a['status']}] owner={a.get('owner')} "
                         f"calls/h={a['hour_calls']} blocked/h={a['hour_blocked']}"
                         for a in s["agents"]) or "No agents."
    if cmd == "/incidents":
        s = stats.rebuild(now)
        return "\n".join(time.strftime("%m-%d %H:%M", time.gmtime(i["ts"])) + " " + i["line"]
                         for i in s["incidents"][:10]) or "No incidents."
    if cmd in ("/kill", "/resume"):
        if not arg:
            return f"Usage: {cmd} <agent_id>"
        r = _gateway_admin(f"/admin/agents/{arg}/{cmd[1:]}")
        return r.get("error") or f"{arg} is now {r.get('status')}"
    if cmd in ("/killall", "/unkillall"):
        r = _gateway_admin("/admin/kill-all" if cmd == "/killall" else "/admin/unkill-all")
        return "Global kill switch is now " + ("ON" if r.get("kill_all") else "OFF")
    return HELP


def daily_report(now):
    """Real (non-demo) agents only: calls, blocked, incidents, cost avoided (last 24 h)."""
    since = now - 86400
    agents = store.batch_get(config.T_AGENTS, [{"agent_id": i} for i in store.registry_ids()])
    real = [a for a in agents if not a.get("demo")]
    lines = [f"Daily report ({time.strftime('%Y-%m-%d', time.gmtime(now))} UTC)"]
    total_avoided = 0.0
    for a in sorted(real, key=lambda x: x["agent_id"]):
        aid = a["agent_id"]
        usage = store.query_recent(config.T_USAGE, aid, limit=0, since=since)
        calls = sum(int(u.get("count", 1)) for u in usage)
        blocked = sum(int(u.get("count", 1)) for u in usage if u.get("outcome") == "blocked")
        cost = sum(float(u.get("est_cost", 0)) for u in usage)
        incs = store.query_recent(config.T_INCIDENTS, aid, limit=0, since=since)
        avoided = config.avoided_cost(blocked)
        total_avoided += avoided
        lines.append(f"{aid} ({a.get('owner')}): {calls} calls, {blocked} blocked, "
                     f"{len(incs)} incidents, est. cost ${cost:.4f}, avoided ${avoided:.4f}")
    if not real:
        lines.append("No real agents registered.")
    lines.append(f"Total est. cost avoided: ${total_avoided:.4f}")
    return "\n".join(lines)
