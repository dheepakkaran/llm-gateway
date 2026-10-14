import config
from state_machine import ACTIVE, KILLED, SUSPENDED, gate, on_detection

L = dict(config.DEFAULT_LIMITS)


def test_gate_states():
    assert gate({"status": ACTIVE}, 100).allowed
    k = gate({"status": KILLED}, 100)
    assert not k.allowed and k.http_status == 403
    s = gate({"status": SUSPENDED, "cooldown_until": 160}, 100)
    assert not s.allowed and s.retry_after_s == 60
    r = gate({"status": SUSPENDED, "cooldown_until": 90}, 100)
    assert r.allowed and r.reactivate


def test_first_detection_suspends_real_agent_15_min():
    t = on_detection({"status": ACTIVE}, 1000, L)
    assert t.new_status == SUSPENDED and t.cooldown_until == 1000 + 900


def test_demo_agent_gets_2_min_cooldown():
    t = on_detection({"status": ACTIVE, "demo": True}, 1000, L)
    assert t.cooldown_until == 1000 + 120


def test_second_detection_within_24h_kills_real_agent():
    t = on_detection({"status": ACTIVE, "last_suspended_at": 1000}, 1000 + 3600, L)
    assert t.new_status == KILLED


def test_second_detection_after_24h_only_suspends():
    t = on_detection({"status": ACTIVE, "last_suspended_at": 0}, 90_000, L)
    assert t.new_status == SUSPENDED


def test_demo_agents_never_escalate():
    t = on_detection({"status": ACTIVE, "demo": True, "last_suspended_at": 1000}, 1100, L)
    assert t.new_status == SUSPENDED
