import demo_lock
import guard
import incidents
import stats


def test_one_run_at_a_time_and_movie_interval():
    s = demo_lock.empty_state()
    v, new = demo_lock.decide(s, 1000, "movie")
    assert v == "start" and new["status"] == "running"
    v, same = demo_lock.decide(new, 1010, "scenario", "loop")
    assert v == "watch"
    done = dict(new, status="done")
    v, why = demo_lock.decide(done, 1100, "movie")
    assert v == "locked"
    assert demo_lock.decide(done, 1000 + 1200, "movie")[0] == "start"


def test_stale_run_is_not_blocking():
    s = dict(demo_lock.empty_state(), status="running", started_at=0)
    assert demo_lock.decide(s, 1000, "scenario", "loop")[0] == "start"


def test_six_scenarios_per_hour():
    s = demo_lock.empty_state()
    t = 10_000
    for i in range(6):
        v, s = demo_lock.decide(s, t + i * 10, "scenario", "loop")
        assert v == "start"
        s["status"] = "done"
    v, _ = demo_lock.decide(s, t + 100, "scenario", "normal")
    assert v == "locked"
    assert demo_lock.decide(s, t + 3601, "scenario", "normal")[0] == "start"


def test_invalid_and_hidden_scenarios():
    s = demo_lock.empty_state()
    assert demo_lock.decide(s, 1, "party")[0] == "invalid"
    assert demo_lock.decide(s, 1, "scenario", "real_trace")[0] == "invalid"


def test_stats_aggregate_has_no_prompt_text_and_counts():
    w = guard.new_window()
    w.update(st="SUSPENDED", cu=2000, tc=10, tb=4, h=1, hc=10, hb=4)
    agents = {"loop-bot": {"agent_id": "loop-bot", "owner": "demo", "demo": True,
                           "key_hash": "SECRET"}}
    inc = incidents.build(agents["loop-bot"], "SUSPENDED", 1500, "repeat_prompt",
                          "same prompt 6x in 2 min", {"time_to_detect_s": 2.5,
                                                      "calls_in_pattern": 6}, 0)
    usage = {"loop-bot": [{"sk": "00001500000000#a", "outcome": "blocked",
                           "reason": "loop_detected", "status": 429}]}
    snap = stats.aggregate(agents, {"loop-bot": w}, usage, {"loop-bot": [inc]}, 1600)
    card = snap["agents"][0]
    assert card["status"] == "SUSPENDED" and card["cooldown_left_s"] == 400
    assert "key_hash" not in str(snap)
    assert snap["counters"]["avg_time_to_suspend_s"] == 2.5
    assert snap["requests"][0]["reason"] == "loop_detected"


def test_alert_text_format():
    a = {"agent_id": "leetcode-bot", "owner": "dheepak"}
    inc = incidents.build(a, "SUSPENDED", 1, "repeat_prompt", "same prompt 6x in 2 min", {}, 3)
    t = incidents.alert_text("leetcode-bot", inc)
    assert t.startswith("leetcode-bot (owner dheepak) SUSPENDED: same prompt 6x in 2 min.")
    assert "Blocked 3 calls" in t and t.endswith("/resume leetcode-bot")
