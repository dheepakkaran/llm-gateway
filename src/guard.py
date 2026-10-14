"""Pure request-pipeline decisions (steps 3-7 of the pipeline). No AWS calls.

Each agent has ONE small "window" item in the counters table. It is read once
per request and written back once with a version check (optimistic locking),
so a normal request costs 1 read + 1 window write (+1 usage write).

Window fields (short names keep the item < 1 KB = 1 WCU per write):
  st, cu, sc   status mirror, cooldown_until, status_changed_at
  m, mr, mt    current epoch-minute, requests in it, tokens in it
  h, hc, hb    current epoch-hour, calls in it, blocked in it
  dy, dt       UTC day, tokens reserved today
  p            {prompt_hash: [times]} inside the repeat window
  f            [times] failed/blocked requests (retry-storm window)
  v            [times] limit violations (token bomb / rate limit)
  bl           calls blocked since the last state change
  tc, tb       lifetime calls / blocked
"""
import json
import time
from dataclasses import dataclass
from typing import Optional

import detection as d
from state_machine import ACTIVE, KILLED, SUSPENDED

MAX_PROMPT_KEYS = 40
_LISTS = ("f", "v")


def new_window():
    return {"st": ACTIVE, "cu": 0, "sc": 0,
            "m": 0, "mr": 0, "mt": 0, "h": 0, "hc": 0, "hb": 0,
            "dy": "", "dt": 0, "p": {}, "f": [], "v": [],
            "bl": 0, "tc": 0, "tb": 0}


# ---------- compact (de)serialization: times as deciseconds from a base ----------

def encode(w):
    times = [t for ts in w["p"].values() for t in ts] + w["f"] + w["v"]
    base = int(min(times)) if times else 0

    def rel(ts):
        return [int(round((t - base) * 10)) for t in ts]

    out = {k: v for k, v in w.items() if k not in ("p",) + _LISTS}
    out["b"] = base
    out["p"] = {h: rel(ts) for h, ts in w["p"].items()}
    for k in _LISTS:
        out[k] = rel(w[k])
    return json.dumps(out, separators=(",", ":"))


def decode(s):
    w = new_window()
    if not s:
        return w
    raw = json.loads(s)
    base = raw.get("b", 0)
    for k in w:
        if k in raw and k not in ("p",) + _LISTS:
            w[k] = raw[k]
    w["p"] = {h: [base + x / 10 for x in v] for h, v in raw.get("p", {}).items()}
    for k in _LISTS:
        w[k] = [base + x / 10 for x in raw.get(k, [])]
    return w


def copy_window(w):
    c = dict(w)
    c["p"] = {h: list(ts) for h, ts in w["p"].items()}
    for k in _LISTS:
        c[k] = list(w[k])
    return c


def roll(w, now, limits):
    """Copy of the window with expired buckets reset and old times pruned."""
    w = copy_window(w)
    minute, hour = int(now // 60), int(now // 3600)
    if w["m"] != minute:
        w["m"], w["mr"], w["mt"] = minute, 0, 0
    if w["h"] != hour:
        w["h"], w["hc"], w["hb"] = hour, 0, 0
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if w["dy"] != day:
        w["dy"], w["dt"] = day, 0
    p = {h: d.prune(ts, now, limits["repeat_window_s"]) for h, ts in w["p"].items()}
    w["p"] = {h: ts for h, ts in p.items() if ts}
    w["f"] = d.prune(w["f"], now, limits["retry_storm_window_s"])
    w["v"] = d.prune(w["v"], now, limits["violation_window_s"])
    return w


# ---------- status gate from the (fresh) window mirror ----------

@dataclass
class StatusGate:
    blocked: bool
    http_status: int = 200
    reason: str = ""
    retry_after_s: int = 0
    reactivate: bool = False


def status_gate(w, now):
    if w["st"] == KILLED:
        return StatusGate(True, 403, "agent_killed")
    if w["st"] == SUSPENDED:
        if now < w["cu"]:
            return StatusGate(True, 403, "agent_suspended", int(w["cu"] - now) + 1)
        return StatusGate(False, reactivate=True)
    return StatusGate(False)


# ---------- steps 4-7 ----------

@dataclass
class Decision:
    allowed: bool
    http_status: int = 200
    reason: str = "ok"
    message: str = ""
    detection: Optional[d.Detection] = None
    violation: bool = False


def _evidence(det, first_t, calls, now):
    det.evidence["time_to_detect_s"] = round(max(0.0, now - first_t), 1)
    det.evidence["calls_in_pattern"] = calls
    return det


def _count_block(w, now, limits, violation):
    w["f"].append(now)
    w["bl"] += 1
    w["hb"] += 1
    w["tb"] += 1
    if violation:
        w["v"].append(now)
        det = d.check_violations(w["v"], limits)
        if det:
            return _evidence(det, w["v"][0], len(w["v"]), now)
    det = d.check_retry_storm(w["f"], limits)
    if det:
        return _evidence(det, w["f"][0], len(w["f"]), now)
    return None


def evaluate(w, now, limits, phash, prompt_tokens, reserve_tokens):
    """Run steps 4-7 on a rolled window copy. Mutates and returns (w, Decision)."""
    w = roll(w, now, limits)
    w["mr"] += 1
    w["hc"] += 1
    w["tc"] += 1

    def block(status, reason, message, violation=False, det=None):
        extra = _count_block(w, now, limits, violation)
        return w, Decision(False, status, reason, message, det or extra, violation)

    # 4. token bomb (counts as a violation)
    det = d.check_token_bomb(prompt_tokens, limits)
    if det:
        return block(413, "token_bomb", det.summary, violation=True)

    # 5. rate limit (counts as a violation)
    det = d.check_rate(w["mr"], limits)
    if det:
        return block(429, "rate_limit", det.summary, violation=True)

    # 6. loop detection (8 hex chars of the hash keep the item small; a
    # collision among <=40 live prompts is ~1 in 10^8)
    phash = phash[:8]
    times = w["p"].get(phash, []) + [now]
    w["p"][phash] = times
    if len(w["p"]) > MAX_PROMPT_KEYS:
        for h in sorted(w["p"], key=lambda k: w["p"][k][-1])[: len(w["p"]) - MAX_PROMPT_KEYS]:
            del w["p"][h]
    det = d.check_repeat(times, limits)
    if det:
        return block(429, "loop_detected", det.summary, det=_evidence(det, times[0], len(times), now))
    det = d.check_token_spike(w["mt"] + reserve_tokens, limits)
    if det:
        return block(429, "token_spike", det.summary, det=_evidence(det, w["m"] * 60, w["mr"], now))

    # 7. daily token budget
    if w["dt"] + reserve_tokens > limits["daily_token_budget"]:
        return block(429, "daily_budget", "daily token budget exceeded")

    # Reserve tokens now (prompt estimate + max_tokens) so we never need a
    # second write on the happy path. Actual usage goes to the usage record.
    w["mt"] += reserve_tokens
    w["dt"] += reserve_tokens
    return w, Decision(True)


def record_failure(w, now, limits):
    """Provider call failed after all fallbacks: counts toward a retry storm."""
    w = roll(w, now, limits)
    w["f"].append(now)
    det = d.check_retry_storm(w["f"], limits)
    if det:
        det = _evidence(det, w["f"][0], len(w["f"]), now)
    return w, det


def add_blocked(w, now, limits, n):
    """Coalesced count of calls blocked at the status gate (suspended/killed)."""
    w = roll(w, now, limits)
    w["bl"] += n
    w["hb"] += n
    w["tb"] += n
    w["tc"] += n
    w["hc"] += n
    return w


def apply_transition(w, now, new_status, cooldown_until, reset_history):
    """Mirror a state change into the window. Returns calls blocked before it."""
    blocked_before = w["bl"]
    w["st"], w["cu"], w["sc"], w["bl"] = new_status, int(cooldown_until), int(now), 0
    if reset_history:  # suspension or manual resume: start the agent from a clean slate
        w["p"], w["f"], w["v"] = {}, [], []
        w["mr"], w["mt"] = 0, 0
    return blocked_before
