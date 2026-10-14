"""Incident records + alert text (pure)."""
import config


def build(agent, action, now, rule="", summary="", evidence=None, blocked=0, by="auto"):
    return {
        "owner": agent.get("owner", ""), "team": agent.get("team", ""),
        "demo": bool(agent.get("demo")), "action": action, "rule": rule,
        "summary": summary, "evidence": evidence or {}, "blocked": int(blocked),
        "cost_avoided": config.avoided_cost(blocked), "by": by, "ts": int(now),
    }


def _calls(n):
    return f"{n} call{'' if n == 1 else 's'}"


def alert_text(agent_id, inc):
    """Short Telegram alert, e.g.
    'leetcode-bot SUSPENDED: same prompt 6x in 2 min. Blocked 3 calls. ...'"""
    owner = f" (owner {inc['owner']})" if inc.get("owner") else ""
    a = inc["action"]
    if a in ("SUSPENDED", "KILLED") and inc.get("summary"):
        cmd = f"/resume {agent_id}"
        return (f"{agent_id}{owner} {a}: {inc['summary']}. Blocked {_calls(inc['blocked'])}. "
                f"Est. cost avoided ${inc['cost_avoided']:.4f}. {cmd}")
    if a in ("RESUMED", "AUTO_RESUMED"):
        return (f"{agent_id}{owner} {a.replace('_', ' ')}. Blocked {_calls(inc['blocked'])} "
                f"while stopped (est. ${inc['cost_avoided']:.4f} avoided).")
    return f"{agent_id}{owner} {a} by {inc.get('by', 'admin')}."


def dashboard_line(agent_id, inc):
    """'loop-bot SUSPENDED: same prompt 6x in 2 min, 4 calls blocked'"""
    text = f"{agent_id} {inc['action']}"
    if inc.get("summary"):
        text += f": {inc['summary']}"
    n = inc.get("blocked", 0)
    return text + f", {n} call{'' if n == 1 else 's'} blocked"
