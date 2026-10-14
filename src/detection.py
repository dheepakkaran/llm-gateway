"""Pure runaway-agent detection rules. No AWS calls; unit-tested with pytest.

The gateway keeps one small "window state" per agent (stored inside the agent's
counters item) and feeds it to these functions. Each function returns either
None (fine) or a Detection with the rule name and evidence numbers.
"""
import hashlib
import re
from dataclasses import dataclass, field

_WS = re.compile(r"\s+")


@dataclass
class Detection:
    rule: str            # repeat_prompt | retry_storm | token_spike | repeated_violations
    summary: str         # short human text, e.g. "same prompt 6x in 2 min"
    evidence: dict = field(default_factory=dict)


def normalize_messages(messages):
    """Lowercase + collapse whitespace over all messages (role:content)."""
    parts = []
    for m in messages or []:
        content = m.get("content", "")
        if isinstance(content, list):  # OpenAI content parts
            content = " ".join(p.get("text", "") for p in content if isinstance(p, dict))
        parts.append(f"{m.get('role', '')}:{content}")
    return _WS.sub(" ", "\n".join(parts).lower()).strip()


def prompt_hash(messages):
    return hashlib.sha256(normalize_messages(messages).encode()).hexdigest()[:16]


def prompt_chars(messages):
    total = 0
    for m in messages or []:
        c = m.get("content", "")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        total += len(str(c))
    return total


def estimate_tokens(chars):
    return (int(chars) + 3) // 4


def _minutes(window_s):
    m = window_s / 60
    return f"{int(m)} min" if m == int(m) else f"{m:g} min"


# ---------------- sliding windows (lists of timestamps) ----------------

def prune(ts_list, now, window_s):
    """Keep timestamps inside (now - window_s, now]."""
    cutoff = now - window_s
    return [t for t in ts_list if t > cutoff]


# ---------------- individual rules ----------------

def check_token_bomb(prompt_tokens, limits):
    if prompt_tokens > limits["max_prompt_tokens"]:
        return Detection(
            "token_bomb",
            f"prompt ~{prompt_tokens} tokens > limit {limits['max_prompt_tokens']}",
            {"prompt_tokens": prompt_tokens, "limit": limits["max_prompt_tokens"]},
        )
    return None


def check_rate(minute_count, limits):
    """minute_count includes the current request."""
    if minute_count > limits["rpm"]:
        return Detection(
            "rate_limit",
            f"{minute_count} req in 1 min > rpm {limits['rpm']}",
            {"requests_this_minute": minute_count, "rpm": limits["rpm"]},
        )
    return None


def check_repeat(prompt_times, limits):
    """prompt_times: timestamps of this exact prompt hash inside the window,
    including the current request. Fires when count > repeat_threshold."""
    n = len(prompt_times)
    if n > limits["repeat_threshold"]:
        return Detection(
            "repeat_prompt",
            f"same prompt {n}x in {_minutes(limits['repeat_window_s'])}",
            {"repeats": n, "window_s": limits["repeat_window_s"]},
        )
    return None


def check_retry_storm(failure_times, limits):
    n = len(failure_times)
    if n >= limits["retry_storm_threshold"]:
        return Detection(
            "retry_storm",
            f"{n} failed/blocked calls in {_minutes(limits['retry_storm_window_s'])}",
            {"failures": n, "window_s": limits["retry_storm_window_s"]},
        )
    return None


def check_token_spike(tokens_this_minute, limits):
    if tokens_this_minute > limits["max_tokens_per_min"]:
        return Detection(
            "token_spike",
            f"{tokens_this_minute} tokens in 1 min > limit {limits['max_tokens_per_min']}",
            {"tokens_this_minute": tokens_this_minute, "limit": limits["max_tokens_per_min"]},
        )
    return None


def check_violations(violation_times, limits):
    n = len(violation_times)
    if n >= limits["violation_threshold"]:
        return Detection(
            "repeated_violations",
            f"{n} limit violations in {_minutes(limits['violation_window_s'])}",
            {"violations": n, "window_s": limits["violation_window_s"]},
        )
    return None
