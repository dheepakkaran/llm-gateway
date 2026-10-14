"""Pipeline steps 4-7 on the window, simulated in time. No AWS."""
import config
import detection as d
import guard
from state_machine import ACTIVE, SUSPENDED

L = dict(config.DEFAULT_LIMITS)


def msgs(text):
    return [{"role": "user", "content": text}]


def send(w, now, text, limits=L, max_tokens=64):
    m = msgs(text)
    pt = d.estimate_tokens(d.prompt_chars(m))
    return guard.evaluate(w, now, limits, d.prompt_hash(m), pt, pt + max_tokens)


def test_normal_agent_with_different_prompts_is_never_blocked():
    w = guard.new_window()
    for i in range(20):                      # 20 different prompts in ~60 s
        w, dec = send(w, 1000 + i * 3, f"question number {i}")
        assert dec.allowed, (i, dec)


def test_loop_is_caught_on_sixth_identical_prompt():
    w = guard.new_window()
    for i in range(5):
        w, dec = send(w, 1000 + i, "same question")
        assert dec.allowed
    w, dec = send(w, 1005, "same question")
    assert not dec.allowed and dec.reason == "loop_detected"
    assert dec.detection.rule == "repeat_prompt"
    assert dec.detection.evidence["calls_in_pattern"] == 6
    assert dec.detection.evidence["time_to_detect_s"] == 5.0


def test_repeats_spread_beyond_2_minutes_are_fine():
    w = guard.new_window()
    for i in range(10):                      # one repeat every 30 s
        w, dec = send(w, 1000 + i * 30, "daily status check")
        assert dec.allowed, i


def test_rate_limit_then_repeated_violations_suspend():
    lim = dict(L, rpm=10)
    w = guard.new_window()
    results = []
    for i in range(13):
        w, dec = send(w, 6000 + i * 0.3, f"q{i}", lim)
        results.append(dec)
    assert all(r.allowed for r in results[:10])
    assert results[10].reason == "rate_limit" and results[10].http_status == 429
    assert results[12].detection and results[12].detection.rule == "repeated_violations"


def test_token_bomb_rejected_first_call_413():
    w = guard.new_window()
    w, dec = send(w, 1000, "x" * 50_000)
    assert not dec.allowed and dec.http_status == 413 and dec.violation
    assert dec.detection is None
    w, dec = send(w, 1001, "x" * 50_000)
    w, dec = send(w, 1002, "x" * 50_000)
    assert dec.detection and dec.detection.rule == "repeated_violations"


def test_retry_storm_from_provider_failures():
    w = guard.new_window()
    det = None
    for i in range(10):
        w, dec = send(w, 1000 + i * 0.5, f"task {i // 3}")   # each task retried 3x
        assert dec.allowed
        w, det = guard.record_failure(w, 1000 + i * 0.5 + 0.1, L)
        if i < 9:
            assert det is None
    assert det and det.rule == "retry_storm"


def test_token_spike():
    lim = dict(L, max_tokens_per_min=1000)
    w = guard.new_window()
    w, dec = send(w, 1000, "a", lim, max_tokens=600)
    assert dec.allowed
    w, dec = send(w, 1001, "b", lim, max_tokens=600)
    assert dec.detection and dec.detection.rule == "token_spike"


def test_daily_budget():
    lim = dict(L, daily_token_budget=1000)
    w = guard.new_window()
    w, dec = send(w, 1000, "a", lim, max_tokens=900)
    assert dec.allowed
    w, dec = send(w, 1100, "b", lim, max_tokens=900)
    assert not dec.allowed and dec.reason == "daily_budget" and not dec.detection


def test_status_gate_and_transition_mirror():
    w = guard.new_window()
    w["bl"] = 4
    blocked = guard.apply_transition(w, 1000, SUSPENDED, 1120, reset_history=True)
    assert blocked == 4 and w["bl"] == 0
    g = guard.status_gate(w, 1050)
    assert g.blocked and g.retry_after_s == 71
    assert guard.status_gate(w, 1121).reactivate


def test_encode_roundtrip_and_size_under_1kb():
    w = guard.new_window()
    for i in range(40):                     # worst case: 40 distinct prompts in window
        w, _ = send(w, 1_760_000_000 + i * 3, f"distinct prompt {i}")
    enc = guard.encode(w)
    assert len(enc.encode()) < 1024, len(enc)
    back = guard.decode(enc)
    assert back["tc"] == 40 and len(back["p"]) == 40
    some = next(iter(back["p"].values()))[0]
    assert abs(some - 1_760_000_000) < 200


def test_blocked_counts_are_tracked():
    w = guard.new_window()
    w = guard.add_blocked(w, 1000, L, 7)
    assert w["bl"] == 7 and w["tb"] == 7 and w["hb"] == 7


def test_resume_resets_minute_rate_window():
    lim = dict(L, rpm=10)
    w = guard.new_window()
    for i in range(10):
        w, dec = send(w, 6000 + i, f"q{i}", lim)
    guard.apply_transition(w, 6011, ACTIVE, 0, reset_history=True)
    w, dec = send(w, 6012, "fresh start", lim)
    assert dec.allowed and w["mr"] == 1
