"""Gateway / admin key helpers (pure).

Gateway key format: gw_<agent_id>_<secret>. agent_id has no underscores, so it
can be parsed straight from the key and checked against the stored SHA-256
hash with a single GetItem (no index needed). Plain keys are never stored.
"""
import hashlib
import hmac
import re
import secrets

AGENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")


def sha256(s):
    return hashlib.sha256(s.encode()).hexdigest()


def new_gateway_key(agent_id):
    return f"gw_{agent_id}_{secrets.token_urlsafe(24)}"


def demo_key(agent_id, demo_secret):
    """Deterministic key for demo agents: derived, never stored anywhere."""
    sig = hmac.new(demo_secret.encode(), agent_id.encode(), hashlib.sha256).hexdigest()[:40]
    return f"gw_{agent_id}_{sig}"


def parse_gateway_key(key):
    """'gw_<agent>_<secret>' -> agent_id, or None if malformed."""
    if not key or not key.startswith("gw_"):
        return None
    parts = key.split("_", 2)
    if len(parts) != 3 or not parts[2] or not AGENT_ID_RE.match(parts[1]):
        return None
    return parts[1]


def matches(key, stored_hash):
    return bool(stored_hash) and hmac.compare_digest(sha256(key), stored_hash)


def bearer(headers):
    h = (headers or {}).get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""
