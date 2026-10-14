import random

import config
import keys
import providers

L = dict(config.DEFAULT_LIMITS, mock_latency_ms=0)


def test_key_roundtrip_and_hash_only_storage():
    k = keys.new_gateway_key("loop-bot")
    assert keys.parse_gateway_key(k) == "loop-bot"
    assert keys.matches(k, keys.sha256(k))
    assert not keys.matches(k + "x", keys.sha256(k))


def test_bad_keys_rejected():
    for bad in ["", "sk-abc", "gw_", "gw_Bad_x", "gw_a_", "gw_UPPER_secret", "gw_x_secret"]:
        assert keys.parse_gateway_key(bad) is None, bad
    # the secret part may contain underscores; the agent id never does
    assert keys.parse_gateway_key("gw_ok-bot_ab_cd") == "ok-bot"


def test_demo_key_is_deterministic():
    assert keys.demo_key("good-bot", "s") == keys.demo_key("good-bot", "s")
    assert keys.demo_key("good-bot", "s") != keys.demo_key("good-bot", "t")
    assert keys.parse_gateway_key(keys.demo_key("good-bot", "s")) == "good-bot"


def test_bearer():
    assert keys.bearer({"authorization": "Bearer abc"}) == "abc"
    assert keys.bearer({}) == ""


def test_resolve():
    assert providers.resolve("fast")[0][0] == "groq"
    assert providers.resolve("groq/openai/gpt-oss-120b") == [("groq", "openai/gpt-oss-120b")]
    assert providers.resolve("nope") is None


def test_mock_works_without_any_key():
    st, data, prov, model, att = providers.call(
        [("mock", "mock-1")], [{"role": "user", "content": "hi"}], 50, L, lambda k: None,
        sleep=lambda s: None)
    assert st == 200 and prov == "mock" and data["usage"]["total_tokens"] > 0


def test_fallback_on_429_to_next_provider():
    lim = dict(L, mock_429_rate=1.0)
    st, data, prov, model, att = providers.call(
        [("mock", "mock-1"), ("mock", "mock-2")], [{"role": "user", "content": "hi"}], 50, lim,
        lambda k: None, sleep=lambda s: None)
    assert model == "mock-2" and [a["status"] for a in att] == [429, 200]


def test_real_provider_fallback_without_network():
    calls = []

    def fake_transport(url, headers, body, timeout):
        calls.append(url)
        if "groq" in url:
            return 503, {"error": {"message": "down"}}
        return 200, {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1}}

    st, data, prov, model, att = providers.call(
        providers.resolve("fast"), [{"role": "user", "content": "hi"}], 50, L,
        lambda k: "test-key", transport=fake_transport)
    assert prov == "gemini" and len(calls) == 2


def test_missing_key_skips_provider():
    def fake_transport(url, headers, body, timeout):
        return 200, {"choices": [{"message": {"content": "ok"}}]}

    st, data, prov, model, att = providers.call(
        providers.resolve("fast"), [{"role": "user", "content": "hi"}], 50, L,
        lambda k: None if k == "groq_api_key" else "k", transport=fake_transport)
    assert prov == "gemini" and att[0]["status"] == "no_key"


def test_all_fail_raises_and_400_does_not_fall_back():
    def bad(url, headers, body, timeout):
        return 400, {"error": {"message": "bad"}}

    try:
        providers.call(providers.resolve("fast"), [{"role": "user", "content": "x"}], 5, L,
                       lambda k: "k", transport=bad)
        assert False
    except providers.ProviderError as e:
        assert e.status == 400 and len(e.attempts) == 1


def test_mock_error_rate():
    lim = dict(L, mock_error_rate=1.0)
    try:
        providers.call([("mock", "mock-1")], [{"role": "user", "content": "x"}], 5, lim,
                       lambda k: None, rng=random.Random(1), sleep=lambda s: None)
        assert False
    except providers.ProviderError as e:
        assert e.status == 500
