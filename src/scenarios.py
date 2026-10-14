"""Buggy-agent scenarios, shared by the demo runner Lambda and the offline
simulator. Each scenario plays one agent against the DEPLOYED gateway over
HTTPS, exactly like a real agent would, using the mock model (except
real_provider). Every number in a result is measured client-side in this run.
"""
import json
import os
import random
import statistics
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

DEMO_AGENTS = {
    "good-bot": {"purpose": "Normal Q&A agent: different questions, normal pace", "limits": {}},
    "loop-bot": {"purpose": "Stuck in a bug loop: repeats one question", "limits": {}},
    "speedy-bot": {"purpose": "Sends different questions faster than its rpm", "limits": {"rpm": 10}},
    "bomb-bot": {"purpose": "Sends one giant ~50,000-character prompt", "limits": {}},
    "retry-bot": {"purpose": "Retries instantly after every error (its provider is down)",
                  "limits": {"mock_error_rate": 1.0}},
    "trace-bot": {"purpose": "Replays a real stuck-agent trace (MAST-Data)", "limits": {}},
}
STAGE_AGENT = {"normal": "good-bot", "loop": "loop-bot", "too_fast": "speedy-bot",
               "token_bomb": "bomb-bot", "retry_storm": "retry-bot", "real_trace": "trace-bot"}
STAGE_TEXT = {
    "normal": "A healthy agent asks different questions at a normal pace.",
    "loop": "A buggy agent is stuck in a loop and keeps asking the same question.",
    "too_fast": "An agent fires requests faster than its allowed rate.",
    "token_bomb": "An agent sends one gigantic prompt that would be very expensive.",
    "retry_storm": "An agent's provider is failing, and it retries instantly, forever.",
    "real_trace": "A real multi-agent system stuck repeating its steps.",
}
STAGE_CAPS = {"normal": 5, "loop": 15, "too_fast": 25, "token_bomb": 4, "retry_storm": 20,
              "real_trace": 30, "fallback": 30, "real_provider": 20}


def load_prompts(path=None):
    path = path or os.path.join(HERE, "prompts.jsonl")
    with open(path) as f:
        return [json.loads(line)["instruction"] for line in f if line.strip()]


def bomb_text(prompts, size=50_000):
    body = " ".join(prompts)
    text = "Summarize everything below.\n" + (body + " ") * (size // max(1, len(body)) + 1)
    return text[:size]


class Client:
    """Talks to the gateway like any agent. Paces itself to <= ~3 req/s."""

    def __init__(self, base_url, key_for, min_interval=0.34, timeout=40):
        self.base = base_url.rstrip("/")
        self.key_for = key_for
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0
        self.sent = 0

    def send(self, agent, text, model="mock", max_tokens=64):
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        body = json.dumps({"model": model, "max_tokens": max_tokens,
                           "messages": [{"role": "user", "content": text}]}).encode()
        req = urllib.request.Request(self.base + "/v1/chat/completions", data=body, headers={
            "content-type": "application/json", "authorization": "Bearer " + self.key_for(agent)})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                code, data = r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            code = e.code
            try:
                data = json.loads(e.read())
            except ValueError:
                data = {}
        self.sent += 1
        x = data.get("x_gateway") or {}
        return {"t": round(time.time(), 2), "agent": agent, "code": code,
                "reason": x.get("reason") or ("ok" if code == 200 else str(code)),
                "ms": int((time.time() - t0) * 1000), "agent_status": x.get("agent_status"),
                "provider": x.get("provider"), "fallback": bool(x.get("fallback_used")),
                "gw_ms": x.get("latency_ms")}


STOPPED = ("agent_suspended", "agent_killed")


def _caught(r):
    return r["agent_status"] in ("SUSPENDED", "KILLED") or r["reason"] in STOPPED


def run(scenario, client, prompts, cap=None, on_event=None, rng=None, agent=None,
        normal_interval=0.6, caps=None):
    rng = rng or random.Random()
    limit = (caps or STAGE_CAPS)[scenario]
    cap = min(cap or limit, limit)
    agent = agent or STAGE_AGENT.get(scenario, scenario.replace("_", "-") + "-bot")
    events, t_start = [], time.time()
    catch = {}

    def send(text, **kw):
        r = client.send(agent, text, **kw)
        events.append(r)
        if on_event:
            on_event(r)
        if "first_block" not in catch and r["code"] != 200:
            catch["first_block"] = (len(events), r["reason"], r["t"] - t_start)
        if "stop" not in catch and _caught(r):
            catch["stop"] = (len(events), r["reason"], r["t"] - t_start)
        return r

    if scenario == "normal":
        for q in rng.sample(prompts, cap):
            send(q)
            time.sleep(normal_interval)
    elif scenario == "loop":
        q = rng.choice(prompts)
        while len(events) < cap and len(events) < catch.get("stop", (cap,))[0] + 2:
            send(q)
    elif scenario == "too_fast":
        for q in rng.sample(prompts, cap):
            if len(events) >= catch.get("stop", (cap,))[0] + 1:
                break
            send(q)
    elif scenario == "token_bomb":
        big = bomb_text(prompts)
        while len(events) < cap and "stop" not in catch:
            send(big)
    elif scenario == "retry_storm":
        tasks = iter(rng.sample(prompts, cap))
        while len(events) < cap and len(events) < catch.get("stop", (cap,))[0] + 1:
            q = next(tasks)
            for _ in range(3):  # "retry right away" up to 3x per task
                if len(events) >= cap:
                    break
                r = send(q)
                if r["code"] == 200 or _caught(r):
                    break
    elif scenario == "fallback":
        for q in rng.sample(prompts, cap):
            send(q, model="mock-fallback")
    elif scenario == "real_provider":
        for q in rng.sample(prompts, cap):
            send(q, model="fast", max_tokens=96)
            time.sleep(1.0)  # be gentle with free tiers
    else:
        raise ValueError(f"unknown scenario {scenario}")

    return summarize(scenario, agent, events, catch)


def summarize(scenario, agent, events, catch):
    ok = [e for e in events if e["code"] == 200]
    reached = [e for e in events if e["code"] in (200, 502)]
    res = {"scenario": scenario, "agent": agent, "problem": STAGE_TEXT.get(scenario, ""),
           "sent": len(events), "allowed": len(ok), "blocked": len(events) - len(ok),
           "reached_provider": len(reached),
           "first_block_call": catch.get("first_block", (None,))[0],
           "first_block_reason": catch.get("first_block", (None, None))[1],
           "calls_to_catch": catch.get("stop", (None,))[0],
           "seconds_to_catch": round(catch["stop"][2], 2) if "stop" in catch else None,
           "final_status": next((e["agent_status"] for e in reversed(events) if e["agent_status"]),
                                "ACTIVE"),
           "reasons": {}}
    for e in events:
        res["reasons"][e["reason"]] = res["reasons"].get(e["reason"], 0) + 1
    if scenario == "normal":
        res["caught"] = False
        res["false_blocks"] = res["blocked"]
        res["guard_did"] = ("Nothing: all requests were allowed." if not res["blocked"]
                            else f"Blocked {res['blocked']} normal requests (false positives).")
    elif scenario == "token_bomb":
        res["caught"] = bool(events) and events[0]["code"] == 413
        res["calls_to_catch"] = 1 if res["caught"] else None
        res["seconds_to_catch"] = round(events[0]["ms"] / 1000, 2) if res["caught"] else None
        res["guard_did"] = "Rejected the giant prompt (413) before any provider saw it" + (
            "; after repeated tries the agent was suspended." if "stop" in catch else ".")
    elif scenario == "too_fast":
        res["caught"] = res["first_block_reason"] == "rate_limit"
        res["throttled_at_call"] = res["first_block_call"]
        res["guard_did"] = (f"Throttled it at call {res['first_block_call']} (429)"
                            + (f" and suspended it at call {catch['stop'][0]}." if "stop" in catch
                               else "."))
        if not res["calls_to_catch"] and res["caught"]:
            res["calls_to_catch"] = res["first_block_call"]
            res["seconds_to_catch"] = round(catch["first_block"][2], 2)
    elif scenario in ("loop", "retry_storm", "real_trace"):
        res["caught"] = "stop" in catch
        res["guard_did"] = (f"Suspended the agent after {catch['stop'][0]} calls "
                            f"({res['seconds_to_catch']}s)." if res["caught"] else "Did not catch it.")
    elif scenario == "fallback":
        fb = [e for e in ok if e["fallback"]]
        res["fallback_used"] = len(fb)
        res["fallback_success_rate"] = round(len(ok) / len(events), 3) if events else None
        res["caught"] = None
    elif scenario == "real_provider":
        lat = sorted(e["gw_ms"] for e in ok if e["gw_ms"] is not None)
        res["latency_p50_ms"] = int(statistics.median(lat)) if lat else None
        res["latency_p95_ms"] = int(lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))]) if lat else None
        res["providers"] = {}
        for e in ok:
            res["providers"][e["provider"]] = res["providers"].get(e["provider"], 0) + 1
        res["fallback_used"] = sum(1 for e in ok if e["fallback"])
        res["caught"] = None
    return res
