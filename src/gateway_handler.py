"""Gateway Lambda behind one Function URL (auth NONE; app-level keys).

Request pipeline for POST /v1/chat/completions (cheapest rejections first):
 1 global kill switch (SSM, cached 15 s)            -> 503
 2 parse key -> agent (cached 10 s) -> verify hash  -> 401
 3 status: KILLED / SUSPENDED (cooldown)             -> 403 (lazy reactivation)
 4 token bomb                                        -> 413 (violation)
 5 rate limit                                        -> 429 (violation)
 6 loop detection (repeat / token spike)             -> suspend
 7 daily token budget                                -> 429
 8 provider call with fallback
 9 usage record
Steps 3b-7 run on one window item: 1 consistent read + 1 conditional write.
"""
import base64
import json
import logging
import os
import time
import uuid

import config
import demo_lock
import detection as d
import guard
import incidents
import keys
import providers
import stats
import store
from state_machine import ACTIVE, KILLED, SUSPENDED, gate, on_detection

log = logging.getLogger()
log.setLevel(logging.INFO)

BOT_FN = os.environ.get("BOT_FUNCTION", "")
DEMO_FN = os.environ.get("DEMO_FUNCTION", "")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
PUBLIC_PATHS = {"/stats", "/demo/status", "/demo/start"}
FLUSH_EVERY_S = 5

_agents = {}            # agent_id -> (item or None, fetched_at)
_kill = {"on": False, "at": 0.0}
_pending = {}           # agent_id -> {"n", "last", "reason"} coalesced blocked calls
_cache = {}             # "stats" / "demo" -> (body, at)


# ---------------- helpers ----------------

def _resp(status, body, cors=False, extra=None):
    h = {"content-type": "application/json"}
    if cors:
        h.update({"access-control-allow-origin": ALLOWED_ORIGIN,
                  "access-control-allow-methods": "GET,POST,OPTIONS",
                  "access-control-allow-headers": "content-type"})
    h.update(extra or {})
    return {"statusCode": status, "headers": h, "body": json.dumps(body, separators=(",", ":"))}


def _err(status, code, message, agent_status=None, retry_after=0, extra=None):
    body = {"error": {"message": message, "type": "gateway_error", "code": code},
            "x_gateway": {"blocked": True, "reason": code, "agent_status": agent_status}}
    if retry_after:
        body["x_gateway"]["retry_after_s"] = retry_after
    body["x_gateway"].update(extra or {})
    hdr = {"retry-after": str(retry_after)} if retry_after else None
    return _resp(status, body, extra=hdr)


def _log(**kv):
    # "BLOCKED {...}" / "STATE_CHANGE {...}": the leading word feeds the two
    # CloudWatch metric filters. Never prompt text or keys.
    log.info("%s %s", str(kv.get("event", "")).upper(), json.dumps(kv, separators=(",", ":")))


def kill_all_on():
    if time.time() - _kill["at"] > config.KILL_SWITCH_CACHE_S:
        _kill["on"] = store.param("kill_all", decrypt=False, cache_s=0) == "on"
        _kill["at"] = time.time()
    return _kill["on"]


def load_agent(agent_id, fresh=False):
    hit = _agents.get(agent_id)
    if not fresh and hit and time.time() - hit[1] < config.AGENT_CACHE_S:
        return hit[0]
    a = store.get_agent(agent_id, consistent=fresh)
    _agents[agent_id] = (a, time.time())
    return a


def _remember_status(agent, status, cooldown_until=0, now=None, suspended_at=None):
    a = dict(agent, status=status, cooldown_until=int(cooldown_until))
    if suspended_at:
        a["last_suspended_at"] = int(suspended_at)
    _agents[agent["agent_id"]] = (a, time.time())


def _alert(agent, inc):
    if agent.get("demo") or not BOT_FN:
        return  # demo agents only show on the dashboard
    try:
        store.invoke_async(BOT_FN, {"type": "alert",
                                    "text": incidents.alert_text(agent["agent_id"], inc)})
    except Exception:
        log.exception("alert failed")


def _update_window(agent_id, fn, tries=4):
    """Read-modify-write with optimistic locking. fn(window) -> (window, result);
    fn may return window=None to skip the write (nothing changed)."""
    for _ in range(tries):
        enc, ver = store.get_window(agent_id)
        w, result = fn(guard.decode(enc))
        if w is None or store.put_window(agent_id, guard.encode(w), ver):
            return result
    raise store.Busy()


def _count_blocked(agent, now, limits, reason, status_code):
    """Calls blocked at the status gate are counted in memory and flushed at
    most every 5 s per agent, so a runaway agent can't burn our write budget."""
    aid = agent["agent_id"]
    p = _pending.setdefault(aid, {"n": 0, "last": 0.0})
    p["n"] += 1
    if now - p["last"] < FLUSH_EVERY_S:
        return
    n, p["n"], p["last"] = p["n"], 0, now
    try:
        _update_window(aid, lambda w: (guard.add_blocked(w, now, limits, n), None))
        store.put_usage(aid, now, uuid.uuid4().hex[:8], {
            "outcome": "blocked", "reason": reason, "status": status_code, "count": n,
            "latency_ms": 0})
    except store.Busy:
        pass  # already blocked; dropping a count is fine


def _transition(agent, tr, now, rule, summary, evidence, blocked):
    """Persist a detection-driven state change: agent item, incident, alert."""
    aid = agent["agent_id"]
    ok = store.set_agent_status(aid, tr.new_status, now, tr.cooldown_until,
                                last_suspended_at=tr.last_suspended_at, expect=[ACTIVE])
    if not ok:
        return None  # another request already did it
    inc = incidents.build(agent, tr.action, now, rule, summary, evidence, blocked)
    store.put_incident(aid, now, inc)
    _remember_status(agent, tr.new_status, tr.cooldown_until, suspended_at=now)
    _log(event="state_change", agent=aid, action=tr.action, rule=rule)
    _alert(agent, inc)
    return inc


# ---------------- chat completions ----------------

def chat(headers, raw):
    now = time.time()
    rid = uuid.uuid4().hex[:10]

    # 1. global kill switch
    if kill_all_on():
        return _err(503, "kill_all", "All agents are stopped by the global kill switch.")

    # 2. key -> agent -> hash
    key = keys.bearer(headers)
    aid = keys.parse_gateway_key(key)
    agent = load_agent(aid) if aid else None
    if not agent or not keys.matches(key, agent.get("key_hash")):
        return _err(401, "invalid_key", "Missing or invalid gateway key.")
    limits = config.agent_limits(agent)

    # 3. status from the cached agent (cheapest possible rejection)
    g = gate(agent, now)
    if not g.allowed:
        _count_blocked(agent, now, limits, g.reason, g.http_status)
        return _err(g.http_status, g.reason, _status_msg(g.reason, g.retry_after_s),
                    agent["status"], g.retry_after_s)

    try:
        req = json.loads(raw or "{}")
    except ValueError:
        return _err(400, "bad_json", "Body must be JSON.")
    messages, model = req.get("messages"), str(req.get("model") or "")
    if not isinstance(messages, list) or not messages or not all(isinstance(m, dict) for m in messages):
        return _err(400, "bad_request", "messages must be a non-empty list of objects.")
    chain = providers.resolve(model)
    if not chain:
        return _err(400, "unknown_model", f"Unknown model '{model}'. Use one of {sorted(config.MODEL_ALIASES)}.")
    try:
        max_tokens = int(req.get("max_tokens") or limits["default_max_tokens"])
    except (TypeError, ValueError):
        return _err(400, "bad_request", "max_tokens must be an integer.")
    max_tokens = max(1, min(max_tokens, limits["max_tokens_cap"]))
    ptok = d.estimate_tokens(d.prompt_chars(messages))
    phash = d.prompt_hash(messages)

    # 3b-7. one window read + one conditional write
    ctx = {}

    def step(w):
        ctx.clear()
        sg = guard.status_gate(w, now)
        if sg.blocked:
            ctx["gate"] = sg
            ctx["w"] = (w["st"], w["cu"])
            return None, None
        if sg.reactivate:
            ctx["reactivated"] = guard.apply_transition(w, now, ACTIVE, 0, reset_history=False)
        w, dec = guard.evaluate(w, now, limits, phash, ptok, ptok + max_tokens)
        if dec.detection:
            fresh = store.get_agent(aid, consistent=True) or agent
            if "reactivated" in ctx:
                fresh = dict(fresh, status=ACTIVE)
            tr = on_detection(fresh, now, limits)
            ctx["tr"] = tr
            ctx["blocked_before"] = guard.apply_transition(w, now, tr.new_status, tr.cooldown_until,
                                                           reset_history=True)
        return w, dec

    dec = _update_window(aid, step)

    if "gate" in ctx:  # agent cache was stale; the window knows better
        sg = ctx["gate"]
        st, cu = ctx["w"]
        _remember_status(agent, st, cu)
        _count_blocked(agent, now, limits, sg.reason, sg.http_status)
        return _err(sg.http_status, sg.reason, _status_msg(sg.reason, sg.retry_after_s), st,
                    sg.retry_after_s)

    if "reactivated" in ctx and store.set_agent_status(aid, ACTIVE, now, 0, expect=[SUSPENDED]):
        inc = incidents.build(agent, "AUTO_RESUMED", now, summary="cooldown over",
                              blocked=ctx["reactivated"])
        store.put_incident(aid, now, inc)
        _remember_status(agent, ACTIVE)
        _alert(agent, inc)

    agent_status = ACTIVE
    if "tr" in ctx:
        det = dec.detection
        _transition(agent, ctx["tr"], now, det.rule, det.summary, det.evidence, ctx["blocked_before"])
        agent_status = ctx["tr"].new_status

    if not dec.allowed:
        store.put_usage(aid, now, rid, {"outcome": "blocked", "reason": dec.reason,
                                        "status": dec.http_status, "latency_ms": 0})
        _log(event="blocked", agent=aid, reason=dec.reason, status=dec.http_status)
        extra = {"rule": dec.detection.rule, "evidence": dec.detection.evidence} if dec.detection else None
        return _err(dec.http_status, dec.reason, dec.message, agent_status, extra=extra)

    # 8. provider with fallback
    t0 = time.time()
    try:
        status, data, prov, mdl, attempts = providers.call(
            chain, messages, max_tokens, limits, lambda k: store.param(k))
    except providers.ProviderError as e:
        fail_now = time.time()
        fctx = {}

        def fail_step(w):
            w, det = guard.record_failure(w, fail_now, limits)
            if det and w["st"] == ACTIVE:
                fresh = store.get_agent(aid, consistent=True) or agent
                tr = on_detection(fresh, fail_now, limits)
                fctx.update(tr=tr, det=det,
                            blocked=guard.apply_transition(w, fail_now, tr.new_status,
                                                           tr.cooldown_until, reset_history=True))
            return w, None

        _update_window(aid, fail_step)
        if "tr" in fctx:
            _transition(agent, fctx["tr"], fail_now, fctx["det"].rule, fctx["det"].summary,
                        fctx["det"].evidence, fctx["blocked"])
        ms = int((fail_now - t0) * 1000)
        store.put_usage(aid, now, rid, {"outcome": "error", "reason": f"provider_{e.status}",
                                        "status": 502, "latency_ms": ms,
                                        "attempts": len(e.attempts)})
        _log(event="provider_error", agent=aid, status=e.status, attempts=len(e.attempts))
        return _err(502, "provider_error", f"All providers failed (last status {e.status}).",
                    fctx["tr"].new_status if "tr" in fctx else ACTIVE,
                    extra={"attempts": e.attempts})

    # 9. usage
    ms = int((time.time() - t0) * 1000)
    u = data.get("usage") or {}
    pt = int(u.get("prompt_tokens") or ptok)
    ct = int(u.get("completion_tokens") or d.estimate_tokens(len(_content(data))))
    cost = config.est_cost(mdl, pt, ct)
    store.put_usage(aid, now, rid, {"outcome": "allowed", "reason": "ok", "status": 200,
                                    "latency_ms": ms, "provider": prov, "model": mdl,
                                    "prompt_tokens": pt, "completion_tokens": ct,
                                    "est_cost": cost, "fallback": len(attempts) > 1})
    _log(event="ok", agent=aid, provider=prov, model=mdl, ms=ms, attempts=len(attempts))
    data["x_gateway"] = {"provider": prov, "model": mdl, "latency_ms": ms, "est_cost": cost,
                         "agent_status": ACTIVE, "fallback_used": len(attempts) > 1,
                         "attempts": attempts, "request_id": rid}
    return _resp(200, data)


def _content(data):
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _status_msg(reason, retry):
    if reason == "agent_killed":
        return "This agent was killed. An admin must resume it."
    return f"This agent is suspended for runaway behaviour. Retry in {retry}s."


# ---------------- admin ----------------

def _is_admin(headers):
    k = keys.bearer(headers)
    return bool(k) and keys.matches(k, store.param("admin_key_hash"))


def _internal_admin(path):
    return _admin_routes("POST", path, "{}")


def admin(method, path, headers, raw):
    if not _is_admin(headers):
        return _resp(401, {"error": "admin key required"})
    return _admin_routes(method, path, raw)


def _admin_routes(method, path, raw):
    now = time.time()
    parts = path.strip("/").split("/")  # admin, agents, {id}, kill
    try:
        body = json.loads(raw or "{}")
    except ValueError:
        return _resp(400, {"error": "body must be JSON"})

    if parts == ["admin", "agents"] and method == "POST":
        return register(body, now)
    if parts == ["admin", "agents"] and method == "GET":
        return _resp(200, {"agents": list_agents(now)})
    if len(parts) == 4 and parts[1] == "agents" and method == "POST" and parts[3] in ("kill", "resume"):
        return set_status(parts[2], parts[3], now)
    if len(parts) == 4 and parts[1] == "agents" and method == "POST" and parts[3] == "limits":
        limits = {k: v for k, v in (body.get("limits") or {}).items() if k in config.DEFAULT_LIMITS}
        if not store.set_agent_limits(parts[2], limits):
            return _resp(404, {"error": f"no agent '{parts[2]}'"})
        _agents.pop(parts[2], None)
        return _resp(200, {"agent_id": parts[2], "limits": limits})
    if parts in (["admin", "kill-all"], ["admin", "unkill-all"]) and method == "POST":
        on = parts[1] == "kill-all"
        store.set_param("kill_all", "on" if on else "off")
        _kill.update(on=on, at=time.time())
        g = {"agent_id": "_global", "owner": "admin"}
        inc = incidents.build(g, "KILL_ALL" if on else "UNKILL_ALL", now, by="admin")
        store.put_incident("_global", now, inc)
        _alert(g, inc)
        return _resp(200, {"kill_all": on})
    return _resp(404, {"error": "unknown admin route"})


def register(body, now):
    aid = str(body.get("agent_id", "")).strip()
    owner = str(body.get("owner", "")).strip()
    if not keys.AGENT_ID_RE.match(aid):
        return _resp(400, {"error": "agent_id: 2-40 chars, lowercase letters, digits, '-'"})
    if not owner:
        return _resp(400, {"error": "owner is required"})
    limits = {k: v for k, v in (body.get("limits") or {}).items() if k in config.DEFAULT_LIMITS}
    key = keys.new_gateway_key(aid)
    item = {"agent_id": aid, "owner": owner[:80], "team": str(body.get("team", ""))[:80],
            "purpose": str(body.get("purpose", ""))[:200], "key_hash": keys.sha256(key),
            "status": ACTIVE, "cooldown_until": 0, "created_at": int(now),
            "demo": bool(body.get("demo", False)), "limits": limits}
    if not store.put_agent(store._ddb_safe(item)):
        return _resp(409, {"error": f"agent '{aid}' already exists"})
    store.registry_add(aid)
    return _resp(201, {"agent_id": aid, "gateway_key": key,
                       "note": "Shown once. Only its SHA-256 hash is stored."})


def list_agents(now):
    snap = stats.rebuild(now)
    return snap["agents"]


def set_status(aid, action, now):
    agent = store.get_agent(aid, consistent=True)
    if not agent:
        return _resp(404, {"error": f"no agent '{aid}'"})
    new = KILLED if action == "kill" else ACTIVE
    store.set_agent_status(aid, new, now, 0)
    blocked = _update_window(aid, lambda w: (w, guard.apply_transition(
        w, now, new, 0, reset_history=(new == ACTIVE))))
    inc = incidents.build(agent, "KILLED" if new == KILLED else "RESUMED", now, by="admin",
                          blocked=blocked, summary="manual")
    store.put_incident(aid, now, inc)
    _remember_status(agent, new)
    _alert(agent, inc)
    return _resp(200, {"agent_id": aid, "status": new})


# ---------------- public (dashboard) ----------------

def public_stats():
    hit = _cache.get("stats")
    if hit and time.time() - hit[1] < config.STATS_CACHE_S:
        return _resp(200, hit[0], cors=True)
    now = time.time()
    snap, _, built = store.get_blob("stats")
    if not snap or now - built >= config.STATS_REBUILD_S:
        snap = stats.rebuild(now)
        store.put_blob("stats", snap, 0, now, cond_built_before=now - config.STATS_REBUILD_S)
    snap = dict(snap, kill_all=kill_all_on())
    _cache["stats"] = (snap, time.time())
    return _resp(200, snap, cors=True)


def demo_status():
    hit = _cache.get("demo")
    if hit and time.time() - hit[1] < config.DEMO_STATUS_CACHE_S:
        return _resp(200, hit[0], cors=True)
    state, _, _ = store.get_blob("demo")
    view = demo_lock.public_view(state, time.time())
    _cache["demo"] = (view, time.time())
    return _resp(200, view, cors=True)


def demo_start(raw):
    try:
        body = json.loads(raw or "{}")
    except ValueError:
        return _resp(400, {"error": "body must be JSON"}, cors=True)
    for _ in range(3):
        now = time.time()
        state, ver, _ = store.get_blob("demo", consistent=True)
        state = state or demo_lock.empty_state()
        verdict, out = demo_lock.decide(state, now, body.get("mode"), body.get("scenario"))
        if verdict == "invalid":
            return _resp(400, {"error": out}, cors=True)
        if verdict == "watch":
            return _resp(200, dict(demo_lock.public_view(state, now), watching=True), cors=True)
        if verdict == "locked":
            return _resp(429, dict(demo_lock.public_view(state, now), locked=True, reason=out),
                         cors=True)
        if store.put_blob("demo", out, ver, now):
            store.invoke_async(DEMO_FN, {"job": "demo", "run_id": out["run_id"]})
            _cache.pop("demo", None)
            return _resp(202, dict(demo_lock.public_view(out, now), started=True), cors=True)
    return _resp(409, {"error": "busy, try again"}, cors=True)


# ---------------- router ----------------

def handler(event, context):
    if "internal_admin" in event and "requestContext" not in event:
        # Direct Lambda invoke from the Telegram bot (IAM-authorised; a Function
        # URL request always carries requestContext, so it can't reach this).
        r = _internal_admin(event["internal_admin"])
        return json.loads(r["body"])
    http = (event.get("requestContext") or {}).get("http") or {}
    method = http.get("method", "GET")
    path = (event.get("rawPath") or "/").rstrip("/") or "/"
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    raw = event.get("body") or ""
    if event.get("isBase64Encoded") and raw:
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    public = path in PUBLIC_PATHS
    try:
        if method == "OPTIONS":
            return _resp(204, {}, cors=public)
        if path == "/health":
            return _resp(200, {"ok": True, "service": "llm-gateway"})
        if path == "/v1/chat/completions" and method == "POST":
            return chat(headers, raw)
        if path.startswith("/admin/"):
            return admin(method, path, headers, raw)
        if path == "/stats" and method == "GET":
            return public_stats()
        if path == "/demo/status" and method == "GET":
            return demo_status()
        if path == "/demo/start" and method == "POST":
            return demo_start(raw)
        return _resp(404, {"error": "not found"}, cors=public)
    except store.Busy:
        return _err(429, "gateway_busy", "Gateway is at its free-tier capacity; request was "
                    "not sent to any provider. Retry shortly.")
    except Exception:
        log.exception("unhandled error")
        return _resp(500, {"error": "internal error"}, cors=public)
