"""LLM providers: a zero-key mock plus OpenAI-compatible HTTP providers, with
ordered fallback on 429 / 5xx / timeout. HTTP via urllib only (no packages).

`transport` and `sleep` are injectable so tests never call real providers.
"""
import json
import random
import socket
import time
import urllib.error
import urllib.request
import uuid

import config

# Fall back on 429 / 5xx / timeout (504) as specified, and also when a provider
# rejects our key or model (401/403/404): the next provider may still work.
# A 400/413/422 means the request itself is bad, so retrying elsewhere won't help.
NO_FALLBACK_STATUSES = {400, 413, 422}


class ProviderError(Exception):
    def __init__(self, status, message, attempts):
        super().__init__(message)
        self.status = status
        self.attempts = attempts


def resolve(model):
    """'fast' -> alias chain; 'groq/<model>' -> single provider; else None."""
    if model in config.MODEL_ALIASES:
        return list(config.MODEL_ALIASES[model])
    if "/" in model:
        prov, m = model.split("/", 1)
        if prov in config.PROVIDERS:
            return [(prov, m)]
    return None


def _mock(model, messages, max_tokens, limits, rng, sleep):
    sleep(limits["mock_latency_ms"] / 1000)
    # Only the first mock model is flaky, so "mock-fallback" has a healthy backup.
    if model == "mock-1":
        if rng.random() < limits["mock_429_rate"]:
            return 429, {"error": {"message": "mock rate limited"}}
        if rng.random() < limits["mock_error_rate"]:
            return 500, {"error": {"message": "mock internal error"}}
    prompt_chars = sum(len(str(m.get("content", ""))) for m in messages)
    text = "This is a mock response from llm-gateway; no real model was called."
    completion = min(max_tokens, len(text) // 4)
    return 200, {
        "id": "mock-" + uuid.uuid4().hex[:12], "object": "chat.completion",
        "created": int(time.time()), "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": (prompt_chars + 3) // 4, "completion_tokens": completion,
                  "total_tokens": (prompt_chars + 3) // 4 + completion},
    }


def http_transport(url, headers, body, timeout):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read() or b"{}")
        except ValueError:
            payload = {}
        return e.code, payload
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        return 504, {"error": {"message": "provider timeout or unreachable"}}


def _openai(prov_cfg, model, messages, max_tokens, api_key, transport):
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens}).encode()
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json",
               "User-Agent": "llm-gateway/1.0"}
    return transport(prov_cfg["base_url"].rstrip("/") + "/chat/completions", headers, body,
                     config.PROVIDER_TIMEOUT_S)


def call(chain, messages, max_tokens, limits, get_key, transport=http_transport,
         rng=None, sleep=time.sleep):
    """Try each (provider, model) in order. Returns (status, json, provider, model, attempts)."""
    rng = rng or random.Random()
    attempts = []
    last = (502, "no provider available")
    for prov, model in chain:
        cfg = config.PROVIDERS.get(prov)
        if not cfg:
            continue
        t0 = time.time()
        if cfg["type"] == "mock":
            status, data = _mock(model, messages, max_tokens, limits, rng, sleep)
        else:
            key = get_key(cfg["ssm_key"])
            if not key:
                attempts.append({"provider": prov, "model": model, "status": "no_key", "ms": 0})
                continue
            status, data = _openai(cfg, model, messages, max_tokens, key, transport)
        ms = int((time.time() - t0) * 1000)
        attempts.append({"provider": prov, "model": model, "status": status, "ms": ms})
        if status == 200:
            return status, data, prov, model, attempts
        last = (status, (data.get("error") or {}).get("message", "provider error")
                if isinstance(data, dict) else "provider error")
        if status in NO_FALLBACK_STATUSES:
            break
    raise ProviderError(last[0], last[1], attempts)
