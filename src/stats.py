"""Public dashboard snapshot. `aggregate` is pure; `rebuild` does the reads.

Cost of one rebuild (at most once every 20 s, enforced by a conditional write):
1 registry read + 2 BatchGets + 2 small queries per agent. No scans, and no
prompt text or secrets ever leave this module.
"""
import time

import config
import guard
import incidents as inc_mod
import store

PUBLIC_AGENT_FIELDS = ("owner", "team", "purpose", "demo")


def aggregate(agents, windows, usage, incidents, now):
    """agents: {id: item}, windows: {id: decoded window},
    usage/incidents: {id: [items newest first]}."""
    hour = int(now // 3600)
    cards, total_calls, total_blocked = [], 0, 0
    for aid in sorted(agents):
        a, w = agents[aid], windows.get(aid) or guard.new_window()
        status, cu = w["st"], w["cu"]
        if status == "SUSPENDED" and now >= cu:
            status = "ACTIVE"   # cooldown over; flips for real on its next request
        card = {"id": aid, "status": status,
                "cooldown_left_s": max(0, int(cu - now)) if status == "SUSPENDED" else 0,
                "hour_calls": w["hc"] if w["h"] == hour else 0,
                "hour_blocked": w["hb"] if w["h"] == hour else 0,
                "calls_total": w["tc"], "blocked_total": w["tb"]}
        card.update({k: a.get(k) for k in PUBLIC_AGENT_FIELDS})
        cards.append(card)
        total_calls += w["tc"]
        total_blocked += w["tb"]

    feed = []
    for aid, items in usage.items():
        for u in items:
            feed.append({"ts": int(u["sk"][:14]) / 1000, "agent": aid,
                         "outcome": u.get("outcome"), "reason": u.get("reason", ""),
                         "status": u.get("status"), "latency_ms": u.get("latency_ms", 0),
                         "count": u.get("count", 1), "provider": u.get("provider", "")})
    feed.sort(key=lambda r: r["ts"], reverse=True)

    timeline, catch_times, catch_calls = [], [], []
    for aid, items in incidents.items():
        for i in items:
            ev = i.get("evidence") or {}
            timeline.append({"ts": i["ts"], "agent": aid, "owner": i.get("owner"),
                             "action": i["action"], "rule": i.get("rule", ""),
                             "summary": i.get("summary", ""), "blocked": i.get("blocked", 0),
                             "demo": i.get("demo", False),
                             "line": inc_mod.dashboard_line(aid, i)})
            if i["action"] in ("SUSPENDED", "KILLED") and "time_to_detect_s" in ev:
                catch_times.append(ev["time_to_detect_s"])
                catch_calls.append(ev.get("calls_in_pattern", 0))
    timeline.sort(key=lambda r: r["ts"], reverse=True)

    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    return {
        "built_at": int(now), "agents": cards, "requests": feed[:20], "incidents": timeline[:20],
        "counters": {"total_requests": total_calls, "blocked_calls": total_blocked,
                     "est_cost_avoided": config.avoided_cost(total_blocked),
                     "avg_time_to_suspend_s": avg(catch_times),
                     "avg_calls_to_suspend": avg(catch_calls),
                     "suspensions_counted": len(catch_times)},
    }


def rebuild(now=None):
    now = now or time.time()
    ids = store.registry_ids()
    agents = {a["agent_id"]: a for a in store.batch_get(config.T_AGENTS, [{"agent_id": i} for i in ids])}
    wins = store.batch_get(config.T_COUNTERS, [store.wkey(i) for i in ids])
    windows = {w["pk"][2:]: guard.decode(w.get("w", "")) for w in wins}
    usage = {i: store.query_recent(config.T_USAGE, i, 20) for i in agents}
    incs = {i: store.query_recent(config.T_INCIDENTS, i, 5) for i in agents}
    return aggregate(agents, windows, usage, incs, now)
