"""Demo runner Lambda (timeout 5 min). Invoked asynchronously by POST /demo/start
({"job": "demo"}) and every 15 min by EventBridge Scheduler ({"job": "traffic"}).

It calls the deployed gateway over HTTPS like a real agent (mock model only)
and writes progress + per-stage results into the demo-state item, which the
dashboard polls through GET /demo/status.
"""
import json
import logging
import os
import random
import time

import config
import demo_lock
import guard
import keys
import scenarios
import store

log = logging.getLogger()
log.setLevel(logging.INFO)
GATEWAY_URL = os.environ.get("GATEWAY_URL", "")
INTRO_S, RESULT_S = 6, 12  # time for viewers to read each stage panel (~100 s movie)


def ensure_agent(aid, secret, reset):
    """Upsert a demo agent (demo=true) with its derived key; optionally reset it."""
    spec = scenarios.DEMO_AGENTS[aid]
    existing = store.get_agent(aid, consistent=True)
    key_hash = keys.sha256(keys.demo_key(aid, secret))
    if existing and not reset and existing.get("key_hash") == key_hash:
        return
    store.put_agent(store._ddb_safe({
        "agent_id": aid, "owner": "demo", "team": "demo", "purpose": spec["purpose"],
        "key_hash": key_hash, "status": "ACTIVE", "cooldown_until": 0, "demo": True,
        "limits": spec["limits"], "created_at": int(time.time())}), overwrite=True)
    store.registry_add(aid)
    if reset:
        def fresh(w):
            n = guard.new_window()
            n["tc"], n["tb"] = w["tc"], w["tb"]   # keep lifetime totals for the dashboard
            return n, None
        for _ in range(4):
            enc, ver = store.get_window(aid)
            n, _ = fresh(guard.decode(enc))
            if store.put_window(aid, guard.encode(n), ver):
                break


class Publisher:
    """Writes the demo state, at most once a second unless forced."""

    def __init__(self, state):
        self.state, self.last = state, 0.0

    def __call__(self, force=False):
        if not force and time.time() - self.last < 1.0:
            return
        for _ in range(3):
            _, ver, _ = store.get_blob("demo", consistent=True)
            if store.put_blob("demo", self.state, ver, time.time()):
                break
        self.last = time.time()


def run_demo(run_id):
    state, _, _ = store.get_blob("demo", consistent=True)
    if not state or state.get("run_id") != run_id or state.get("status") != "running":
        log.info(json.dumps({"event": "demo_skip", "run_id": run_id}))
        return {"skipped": True}
    secret = store.param("demo_key_secret")
    prompts = scenarios.load_prompts()
    stages = state["stages"]
    for s in stages:
        ensure_agent(scenarios.STAGE_AGENT[s], secret, reset=True)

    client = scenarios.Client(GATEWAY_URL, lambda a: keys.demo_key(a, secret))
    publish = Publisher(state)
    cap_total = config.DEMO_MOVIE_MAX_REQUESTS if state["mode"] == "movie" \
        else config.DEMO_SCENARIO_MAX_REQUESTS
    rng = random.Random()

    def on_event(e):
        state["events"] = (state["events"] + [{k: e[k] for k in ("t", "agent", "code", "reason", "ms")}])[-14:]
        live = state["results"].setdefault(state["current_stage"], {"live": True})
        live["sent"] = live.get("sent", 0) + 1
        publish()

    try:
        for i, stage in enumerate(stages):
            state["current_stage"], state["stage_phase"] = stage, "intro"
            publish(force=True)
            time.sleep(INTRO_S if state["mode"] == "movie" else 2)
            state["stage_phase"] = "running"
            publish(force=True)
            remaining = cap_total - client.sent
            if remaining <= 0:
                break
            res = scenarios.run(stage, client, prompts, cap=remaining, on_event=on_event, rng=rng)
            state["results"][stage] = res
            state["stage_phase"] = "result"
            publish(force=True)
            if i < len(stages) - 1:
                time.sleep(RESULT_S)
        state["summary"] = summary(state["results"], stages)
        state["status"] = "done"
    except Exception as e:
        log.exception("demo failed")
        state["status"], state["error"] = "failed", type(e).__name__
    state["finished_at"], state["current_stage"] = int(time.time()), None
    state["total_requests"] = client.sent
    publish(force=True)
    return {"status": state["status"], "requests": client.sent}


def summary(results, stages):
    problems = [s for s in stages if s != "normal" and s in results]
    caught = [s for s in problems if results[s].get("caught")]
    times = [results[s]["seconds_to_catch"] for s in caught
             if results[s].get("seconds_to_catch") is not None]
    return {"problems": len(problems), "caught": len(caught),
            "false_blocks": results.get("normal", {}).get("false_blocks"),
            "avg_seconds_to_catch": round(sum(times) / len(times), 2) if times else None,
            "requests": sum(results[s].get("sent", 0) for s in results)}


def traffic():
    """Background traffic so the live feed is never empty: good-bot asks 3 different
    Dolly questions through the gateway with the mock model."""
    secret = store.param("demo_key_secret")
    ensure_agent("good-bot", secret, reset=False)
    client = scenarios.Client(GATEWAY_URL, lambda a: keys.demo_key(a, secret), min_interval=1.0)
    rng = random.Random(int(time.time() // 900))
    out = [client.send("good-bot", q)["code"] for q in rng.sample(scenarios.load_prompts(), 3)]
    return {"codes": out}


def handler(event, context):
    job = event.get("job")
    if job == "traffic":
        return traffic()
    if job == "demo":
        return run_demo(event["run_id"])
    return {"error": "unknown job"}
