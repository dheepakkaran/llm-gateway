import detection as d
import config

L = dict(config.DEFAULT_LIMITS)


def test_normalize_is_case_and_whitespace_insensitive():
    a = [{"role": "user", "content": "Hello   World\n"}]
    b = [{"role": "user", "content": "hello world"}]
    assert d.prompt_hash(a) == d.prompt_hash(b)


def test_hash_covers_all_messages():
    a = [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}]
    b = [{"role": "system", "content": "y"}, {"role": "user", "content": "hi"}]
    assert d.prompt_hash(a) != d.prompt_hash(b)


def test_content_parts_supported():
    m = [{"role": "user", "content": [{"type": "text", "text": "abcd"}]}]
    assert d.prompt_chars(m) == 4


def test_estimate_tokens_chars_div_4():
    assert d.estimate_tokens(0) == 0
    assert d.estimate_tokens(4) == 1
    assert d.estimate_tokens(50_000) == 12_500


def test_repeat_fires_only_above_threshold():
    assert d.check_repeat([1, 2, 3, 4, 5], L) is None          # 5 times: ok
    det = d.check_repeat([1, 2, 3, 4, 5, 6], L)                # 6th: loop
    assert det.rule == "repeat_prompt" and "6x in 2 min" in det.summary


def test_retry_storm_at_threshold():
    assert d.check_retry_storm(list(range(9)), L) is None
    assert d.check_retry_storm(list(range(10)), L).rule == "retry_storm"


def test_token_bomb_and_spike_and_rate():
    assert d.check_token_bomb(8000, L) is None
    assert d.check_token_bomb(8001, L).rule == "token_bomb"
    assert d.check_token_spike(40001, L).rule == "token_spike"
    assert d.check_rate(20, L) is None
    assert d.check_rate(21, L).rule == "rate_limit"


def test_violations_threshold():
    assert d.check_violations([1, 2], L) is None
    assert d.check_violations([1, 2, 3], L).rule == "repeated_violations"


def test_prune_window():
    assert d.prune([1, 50, 100, 119], now=120, window_s=60) == [100, 119]
