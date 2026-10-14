"""Global demo limits (pure). The caller persists the new state with a
conditional write, so two visitors clicking at once can't both start a run.

  - only one run at a time (a run older than STALE_S counts as dead)
  - the full movie at most once every 20 minutes
  - single scenarios at most 6 per hour in total
"""
import uuid

import config

STALE_S = 330  # demo runner timeout is 300 s
SCENARIOS = ["normal", "loop", "too_fast", "token_bomb", "retry_storm", "real_trace"]
MOVIE = ["normal", "loop", "too_fast", "token_bomb", "retry_storm"]  # + real_trace after M3b
ENABLED = set(MOVIE)


def empty_state():
    return {"status": "idle", "run_id": None, "mode": None, "scenario": None,
            "stages": [], "current_stage": None, "started_at": None, "finished_at": None,
            "results": {}, "events": [], "summary": None,
            "last_movie_at": 0, "scenario_starts": []}


def running(state, now):
    return state["status"] == "running" and now - (state.get("started_at") or 0) < STALE_S


def next_allowed(state, now):
    last = state.get("last_movie_at") or 0
    movie = last + config.DEMO_MOVIE_MIN_INTERVAL_S if last else now
    recent = sorted(t for t in state.get("scenario_starts", []) if now - t < 3600)
    scen = recent[0] + 3600 if len(recent) >= config.DEMO_SCENARIOS_PER_HOUR else now
    return {"movie": int(max(now, movie)), "scenario": int(scen)}


def decide(state, now, mode, scenario=None):
    """-> ("start", new_state) | ("watch", state) | ("locked", reason) | ("invalid", reason)"""
    if mode not in ("movie", "scenario"):
        return "invalid", "mode must be 'movie' or 'scenario'"
    if mode == "scenario" and scenario not in SCENARIOS:
        return "invalid", f"scenario must be one of {SCENARIOS}"
    if mode == "scenario" and scenario not in ENABLED:
        return "invalid", f"scenario '{scenario}' is not available yet"
    if running(state, now):
        return "watch", state
    nxt = next_allowed(state, now)
    if mode == "movie" and nxt["movie"] > now:
        return "locked", "the full demo can run once every 20 minutes"
    if mode == "scenario" and nxt["scenario"] > now:
        return "locked", "6 single-scenario runs per hour reached"
    new = empty_state()
    new.update({"status": "running", "run_id": uuid.uuid4().hex[:10], "mode": mode,
                "scenario": scenario, "stages": MOVIE if mode == "movie" else [scenario],
                "started_at": int(now),
                "last_movie_at": int(now) if mode == "movie" else state.get("last_movie_at", 0),
                "scenario_starts": [t for t in state.get("scenario_starts", []) if now - t < 3600]
                + ([int(now)] if mode == "scenario" else [])})
    return "start", new


def public_view(state, now):
    s = dict(state or empty_state())
    s["next_allowed"] = next_allowed(s, now)
    s["is_running"] = running(s, now)
    s.pop("scenario_starts", None)
    return s
