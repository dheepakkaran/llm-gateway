"""Run every demo scenario against an in-memory gateway built from the same
pure functions the Lambda uses (guard + state machine). No network, no AWS."""
import random

import config
import detection as d
import guard
import scenarios
from state_machine import ACTIVE, on_detection


class FakeGateway:
    def __init__(self):
        self.now = 1_760_000_000.0
        self.windows, self.agents = {}, {}

    def send(self, agent, text, model="mock", max_tokens=64):
        self.now += 0.34
        spec = scenarios.DEMO_AGENTS.get(agent, {"limits": {}})
        a = self.agents.setdefault(agent, {"agent_id": agent, "demo": True, "limits": spec["limits"]})
        lim = config.agent_limits(a)
        w = self.windows.get(agent, guard.new_window())
        sg = guard.status_gate(w, self.now)
        if sg.blocked:
            return self._r(agent, 403, sg.reason, w["st"])
        if sg.reactivate:
            guard.apply_transition(w, self.now, ACTIVE, 0, False)
        m = [{"role": "user", "content": text}]
        pt = d.estimate_tokens(d.prompt_chars(m))
        w, dec = guard.evaluate(w, self.now, lim, d.prompt_hash(m), pt, pt + max_tokens)
        if dec.detection:
            tr = on_detection(a, self.now, lim)
            guard.apply_transition(w, self.now, tr.new_status, tr.cooldown_until, True)
        self.windows[agent] = w
        if not dec.allowed:
            return self._r(agent, dec.http_status, dec.reason, w["st"])
        if lim["mock_error_rate"] >= 1.0:
            w, det = guard.record_failure(w, self.now, lim)
            if det:
                tr = on_detection(a, self.now, lim)
                guard.apply_transition(w, self.now, tr.new_status, tr.cooldown_until, True)
            self.windows[agent] = w
            return self._r(agent, 502, "provider_error", w["st"])
        return self._r(agent, 200, None, "ACTIVE")

    def _r(self, agent, code, reason, status):
        self.sent = getattr(self, "sent", 0) + 1
        return {"t": self.now, "agent": agent, "code": code, "reason": reason or "ok", "ms": 5,
                "agent_status": status, "provider": "mock", "fallback": False, "gw_ms": 5}


PROMPTS = scenarios.load_prompts()


def run(name):
    return scenarios.run(name, FakeGateway(), PROMPTS, rng=random.Random(7))


def test_prompts_file_has_200_dolly_prompts():
    assert len(PROMPTS) == 200 and len(set(PROMPTS)) == 200


def test_normal_has_no_false_blocks(monkeypatch):
    monkeypatch.setattr(scenarios.time, "sleep", lambda s: None)
    r = run("normal")
    assert r["sent"] == 5 and r["false_blocks"] == 0


def test_loop_caught_on_sixth_call():
    r = run("loop")
    assert r["caught"] and r["calls_to_catch"] == 6 and r["final_status"] == "SUSPENDED"
    assert r["sent"] == 8 and r["reached_provider"] == 5


def test_too_fast_throttled_then_suspended():
    r = run("too_fast")
    assert r["caught"] and r["throttled_at_call"] == 11 and r["calls_to_catch"] == 13


def test_token_bomb_rejected_first_call():
    r = run("token_bomb")
    assert r["caught"] and r["first_block_call"] == 1 and r["reached_provider"] == 0
    assert r["sent"] == 3  # 3 violations -> suspended


def test_retry_storm_suspended_after_10_failures():
    r = run("retry_storm")
    assert r["caught"] and r["calls_to_catch"] == 10 and r["sent"] == 11


def test_demo_movie_fits_request_cap():
    total = sum(run(s)["sent"] for s in ["loop", "too_fast", "token_bomb", "retry_storm"]) + 5
    assert total <= config.DEMO_MOVIE_MAX_REQUESTS
