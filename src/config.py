"""Single source of defaults: thresholds, providers, model aliases, prices.

Every per-agent limit can be overridden by the agent's `limits` map stored in
DynamoDB (see `agent_limits`). Provider base URLs / model IDs live here, not in
code paths, so they can be changed without touching logic.
"""
import os

REGION = os.environ.get("AWS_REGION", "us-east-1")
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/llm-gateway")

# DynamoDB table names (set by Terraform, defaults for tests)
T_AGENTS = os.environ.get("T_AGENTS", "llmgw-agents")
T_COUNTERS = os.environ.get("T_COUNTERS", "llmgw-counters")
T_USAGE = os.environ.get("T_USAGE", "llmgw-usage")
T_INCIDENTS = os.environ.get("T_INCIDENTS", "llmgw-incidents")

# ---- Per-agent limit defaults (overridable per agent) ----
DEFAULT_LIMITS = {
    "rpm": 20,                      # requests per minute
    "max_prompt_tokens": 8000,      # token-bomb threshold (chars/4 estimate)
    "max_tokens_per_min": 40000,    # token-spike threshold (reserved tokens/min)
    "daily_token_budget": 200000,
    "repeat_threshold": 5,          # same prompt seen MORE than this ...
    "repeat_window_s": 120,         # ... within this window -> loop
    "retry_storm_threshold": 10,    # failed/blocked requests ...
    "retry_storm_window_s": 60,     # ... within this window
    "violation_threshold": 3,       # token-bomb / rate-limit violations ...
    "violation_window_s": 300,      # ... within this window
    "cooldown_s": 900,              # 15 min for real agents
    "demo_cooldown_s": 120,         # 2 min for demo agents
    "escalation_window_s": 86400,   # 2nd detection within 24h -> KILLED
    "max_tokens_cap": 1024,         # cap on requested max_tokens
    "default_max_tokens": 256,      # reserved when the request omits max_tokens
    # mock provider behaviour (per agent, used by demo/simulator)
    "mock_latency_ms": 120,
    "mock_error_rate": 0.0,         # 0..1, returns 500
    "mock_429_rate": 0.0,           # 0..1, returns 429 (fallback test)
}

# ---- Providers (OpenAI-compatible). Verify URLs/models at setup time. ----
PROVIDERS = {
    "mock": {"type": "mock"},
    "groq": {
        "type": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "ssm_key": "groq_api_key",
    },
    "gemini": {
        "type": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "ssm_key": "gemini_api_key",
    },
}

# alias -> ordered list of (provider, model). Fallback goes left to right.
MODEL_ALIASES = {
    "mock": [("mock", "mock-1")],
    "mock-fallback": [("mock", "mock-1"), ("mock", "mock-2")],
    # IDs verified 2026-10-14 against each provider's /models with free keys:
    # Groq retired its Llama models; gemini-2.5-* is closed to new users.
    # (gpt-oss-20b spends small max_tokens budgets on hidden reasoning, so it
    # returns empty answers; qwen3.8-27b answers directly.)
    "fast": [("groq", "qwen/qwen3.8-27b"), ("gemini", "gemini-flash-lite-latest")],
    "smart": [("groq", "openai/gpt-oss-120b"), ("gemini", "gemini-flash-latest")],
}

PROVIDER_TIMEOUT_S = 10

# USD per 1M tokens (input, output): approximate paid-tier list prices, used
# only for estimates. These are
# used for est_cost and "cost avoided" even on free tiers, so the numbers mean
# "what this traffic would cost on a paid plan".
PRICES = {
    "mock-1": (0.15, 0.60),
    "mock-2": (0.15, 0.60),
    "qwen/qwen3.8-27b": (0.29, 0.59),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "gemini-flash-lite-latest": (0.10, 0.40),
    "gemini-flash-latest": (0.30, 2.50),
}
DEFAULT_PRICE = (0.15, 0.60)

# Assumed size of one blocked call, used for "est. cost avoided".
AVOIDED_CALL_TOKENS = (500, 300)

# ---- Caches / dashboard ----
KILL_SWITCH_CACHE_S = 15
AGENT_CACHE_S = 10
STATS_CACHE_S = 10
DEMO_STATUS_CACHE_S = 2
STATS_REBUILD_S = 20

# ---- Demo limits ----
DEMO_MOVIE_MIN_INTERVAL_S = 20 * 60
DEMO_SCENARIOS_PER_HOUR = 6
DEMO_MOVIE_MAX_REQUESTS = 120
DEMO_SCENARIO_MAX_REQUESTS = 40
DEMO_AGENTS = ["good-bot", "loop-bot", "speedy-bot", "bomb-bot", "retry-bot", "trace-bot"]


def agent_limits(agent):
    """Defaults merged with the agent's own overrides (numbers only)."""
    merged = dict(DEFAULT_LIMITS)
    for k, v in (agent.get("limits") or {}).items():
        if k in DEFAULT_LIMITS:
            merged[k] = float(v) if isinstance(DEFAULT_LIMITS[k], float) else int(v)
    return merged


def price_for(model):
    return PRICES.get(model, DEFAULT_PRICE)


def est_cost(model, prompt_tokens, completion_tokens):
    p_in, p_out = price_for(model)
    return round((prompt_tokens * p_in + completion_tokens * p_out) / 1_000_000, 8)


def avoided_cost(blocked_calls, model="mock-1"):
    t_in, t_out = AVOIDED_CALL_TOKENS
    return round(blocked_calls * est_cost(model, t_in, t_out), 6)
