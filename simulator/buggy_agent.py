#!/usr/bin/env python3
"""Buggy-agent simulator: offline proof that the protection works.

Hits the DEPLOYED gateway over HTTPS with its own sim-* agents, using the same
scenario code as the demo runner (src/scenarios.py) and the mock model, except
`real_provider` (20 Dolly prompts through Groq/Gemini). Every run is capped at
300 requests and ~3 req/s. Writes reports/results.md, reports/raw/<ts>.json and
dashboard/results.json. Numbers are only ever copied from measurements.

Usage: .venv/bin/python simulator/buggy_agent.py [--repeat 3] [--skip-real]
"""
import argparse
import json
import pathlib
import random
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import scenarios  # noqa: E402

HOME = pathlib.Path.home() / ".llm-gateway"
MAX_REQUESTS = 300

# simulator agents: flagged demo so they never page the owner or escalate
SIM_AGENTS = {
    "normal": ("sim-normal", {}),
    "loop": ("sim-loop", {}),
    "too_fast": ("sim-fast", {"rpm": 10}),
    "token_bomb": ("sim-bomb", {}),
    "retry_storm": ("sim-retry", {"mock_error_rate": 1.0}),
    # these two send 20-30 calls in well under a minute by design, so they get a
    # higher per-agent rpm (a normal per-agent override) to measure fallback alone
    "fallback": ("sim-fallback", {"mock_429_rate": 0.5, "rpm": 60}),
    "real_provider": ("sim-real", {"rpm": 60}),
}
CAPS = dict(scenarios.STAGE_CAPS, normal=20)


def gateway_url():
    return subprocess.run(["terraform", "output", "-raw", "gateway_url"], cwd=ROOT / "infra",
                          capture_output=True, text=True, check=True).stdout.strip().rstrip("/")


def admin(url, method, path, body=None):
    req = urllib.request.Request(url + path, method=method,
                                 data=json.dumps(body or {}).encode(),
                                 headers={"content-type": "application/json",
                                          "authorization": "Bearer " + (HOME / "admin_key").read_text().strip()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def ensure_agents(url):
    keys = {}
    (HOME / "keys").mkdir(parents=True, exist_ok=True)
    for scen, (aid, limits) in SIM_AGENTS.items():
        path = HOME / "keys" / f"{aid}.key"
        if not path.exists():
            st, body = admin(url, "POST", "/admin/agents", {
                "agent_id": aid, "owner": "simulator", "team": "sim", "demo": True,
                "purpose": f"simulator: {scen}", "limits": limits})
            if st != 201:
                sys.exit(f"could not register {aid}: {st} {body}")
            path.write_text(body["gateway_key"])
            path.chmod(0o600)
        keys[aid] = path.read_text().strip()
        st, _ = admin(url, "POST", f"/admin/agents/{aid}/limits", {"limits": limits})
        assert st == 200, (aid, st)
    return keys


def reset(url, aid):
    st, _ = admin(url, "POST", f"/admin/agents/{aid}/resume")
    assert st == 200, st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3, help="runs per detection scenario")
    ap.add_argument("--skip-real", action="store_true")
    a = ap.parse_args()

    url = gateway_url()
    keys = ensure_agents(url)
    client = scenarios.Client(url, lambda aid: keys[aid])
    prompts = scenarios.load_prompts(ROOT / "simulator" / "prompts.jsonl")
    rng = random.Random(2026)
    plan = [("normal", 1)] + [(s, a.repeat) for s in ("loop", "too_fast", "token_bomb", "retry_storm")] \
        + [("fallback", 1)] + ([] if a.skip_real else [("real_provider", 1)])

    runs = []
    for scen, n in plan:
        for i in range(n):
            left = MAX_REQUESTS - client.sent
            if left <= 0:
                print("request cap reached; stopping")
                break
            aid = SIM_AGENTS[scen][0]
            reset(url, aid)
            r = scenarios.run(scen, client, prompts, cap=min(left, CAPS[scen]), rng=rng, agent=aid,
                              normal_interval=3.1, caps=CAPS)
            r.pop("problem", None)
            runs.append(r)
            print(f"{scen:13} run {i + 1}: sent={r['sent']} caught={r.get('caught')} "
                  f"calls_to_catch={r.get('calls_to_catch')} s={r.get('seconds_to_catch')} "
                  f"reached_provider={r['reached_provider']}")
    write_reports(runs, client.sent)


def agg(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return "–"
    if len(xs) == 1 or min(xs) == max(xs):
        return f"{xs[0]}"
    return f"{statistics.mean(xs):.2f} (min {min(xs)}, max {max(xs)})"


def write_reports(runs, total):
    ts = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    (ROOT / "reports" / "raw").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / "raw" / f"{int(time.time())}.json").write_text(json.dumps(runs, indent=2))
    by = {}
    for r in runs:
        by.setdefault(r["scenario"], []).append(r)

    lines = [f"# Simulator results", "",
             f"Measured {ts} against the deployed gateway (us-east-1), {total} requests in total "
             f"(cap 300, ~3 req/s). Mock model except `real_provider`. Generated by "
             f"`simulator/buggy_agent.py`; numbers are copied from the run, never edited.", "",
             "## Runaway-agent detection", "",
             "| Scenario | Runs | Caught | Calls sent before suspension | Seconds to suspend | Calls that reached a provider |",
             "|---|---|---|---|---|---|"]
    dash = []
    for scen in ("loop", "too_fast", "token_bomb", "retry_storm"):
        rs = by.get(scen, [])
        if not rs:
            continue
        caught = sum(1 for r in rs if r.get("caught"))
        lines.append(f"| {scen} | {len(rs)} | {caught}/{len(rs)} | {agg([r['calls_to_catch'] for r in rs])} | "
                     f"{agg([r['seconds_to_catch'] for r in rs])} | {agg([r['reached_provider'] for r in rs])} |")
        r0 = rs[-1]
        dash.append({"scenario": scen, "sent": r0["sent"], "calls_to_catch": r0["calls_to_catch"],
                     "seconds_to_catch": r0["seconds_to_catch"], "reached_provider": r0["reached_provider"],
                     "note": f"caught {caught}/{len(rs)} runs"})
    lines += ["", "Notes: `too_fast` is throttled (429) first and suspended after 3 violations; "
              "`calls sent before suspension` counts the call that triggered it. `token_bomb` is "
              "rejected (413) on the first call before any provider sees it.", ""]
    n = by.get("normal", [])
    if n:
        r = n[0]
        lines += ["## False positives (normal agent)", "",
                  f"{r['sent']} different Dolly prompts at a normal pace (one every ~3 s): "
                  f"**{r['false_blocks']} blocked** ({r['allowed']} allowed).", ""]
        dash.insert(0, {"scenario": "normal", "sent": r["sent"], "calls_to_catch": None,
                        "seconds_to_catch": None, "reached_provider": r["reached_provider"],
                        "note": f"{r['false_blocks']} false blocks"})
    f = by.get("fallback", [])
    if f:
        r = f[0]
        lines += ["## Provider fallback", "",
                  f"Primary mock model fails with 429 on 50% of calls; backup model healthy. "
                  f"{r['sent']} requests: **{r['allowed']} succeeded** "
                  f"(fallback success rate {r['fallback_success_rate']:.0%}), "
                  f"{r['fallback_used']} of them served by the backup after a 429.", ""]
        dash.append({"scenario": "fallback", "sent": r["sent"], "calls_to_catch": None,
                     "seconds_to_catch": None, "reached_provider": r["reached_provider"],
                     "note": f"{r['fallback_success_rate']:.0%} success, {r['fallback_used']} via backup"})
    rp = by.get("real_provider", [])
    if rp:
        r = rp[0]
        lines += ["## Real providers (Groq, then Gemini)", "",
                  f"{r['sent']} Dolly prompts with model alias `fast`: {r['allowed']} succeeded. "
                  f"Gateway-measured provider latency p50 **{r['latency_p50_ms']} ms**, "
                  f"p95 **{r['latency_p95_ms']} ms**. Served by: {r['providers']}; "
                  f"fallback used {r['fallback_used']} times.", ""]
        dash.append({"scenario": "real_provider", "sent": r["sent"], "calls_to_catch": None,
                     "seconds_to_catch": None, "reached_provider": r["reached_provider"],
                     "note": f"p50 {r['latency_p50_ms']} ms, p95 {r['latency_p95_ms']} ms"})
    (ROOT / "reports" / "results.md").write_text("\n".join(lines))
    (ROOT / "dashboard" / "results.json").write_text(json.dumps(
        {"measured_at": ts, "total_requests": total, "scenarios": dash}, indent=2))
    print("\nwrote reports/results.md and dashboard/results.json")


if __name__ == "__main__":
    main()
