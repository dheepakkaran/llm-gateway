#!/usr/bin/env python3
"""Small CLI for the deployed gateway. Keys never get printed:
  - admin key is read from ~/.llm-gateway/admin_key
  - gateway keys returned at registration are saved to ~/.llm-gateway/keys/<id>.key

Usage:
  gw.py health
  gw.py register <agent_id> <owner> [purpose] [--team T] [--demo] [--limits '{"rpm":10}']
  gw.py agents
  gw.py kill|resume <agent_id>
  gw.py kill-all | unkill-all
  gw.py chat <agent_id> "<prompt>" [--model mock] [--max-tokens 64]
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

HOME = pathlib.Path.home() / ".llm-gateway"
KEYS = HOME / "keys"


def gateway_url():
    url = os.environ.get("GATEWAY_URL")
    if not url:
        infra = pathlib.Path(__file__).resolve().parent.parent / "infra"
        url = subprocess.run(["terraform", "output", "-raw", "gateway_url"], cwd=infra,
                             capture_output=True, text=True, check=True).stdout.strip()
    return url.rstrip("/")


def call(method, path, key=None, body=None):
    req = urllib.request.Request(gateway_url() + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json",
                                          **({"authorization": "Bearer " + key} if key else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def admin_key():
    return (HOME / "admin_key").read_text().strip()


def agent_key(agent_id):
    return (KEYS / f"{agent_id}.key").read_text().strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--team", default="")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--limits", default="{}")
    ap.add_argument("--model", default="mock")
    ap.add_argument("--max-tokens", type=int, default=64)
    a = ap.parse_args()

    if a.cmd == "health":
        out = call("GET", "/health")
    elif a.cmd == "register":
        aid, owner = a.args[0], a.args[1]
        purpose = a.args[2] if len(a.args) > 2 else ""
        st, body = call("POST", "/admin/agents", admin_key(),
                        {"agent_id": aid, "owner": owner, "purpose": purpose, "team": a.team,
                         "demo": a.demo, "limits": json.loads(a.limits)})
        if st == 201:
            KEYS.mkdir(parents=True, exist_ok=True)
            os.chmod(HOME, 0o700)
            path = KEYS / f"{aid}.key"
            path.write_text(body.pop("gateway_key"))
            os.chmod(path, 0o600)
            body["gateway_key_saved_to"] = str(path)
        out = (st, body)
    elif a.cmd == "agents":
        out = call("GET", "/admin/agents", admin_key())
    elif a.cmd in ("kill", "resume"):
        out = call("POST", f"/admin/agents/{a.args[0]}/{a.cmd}", admin_key(), {})
    elif a.cmd in ("kill-all", "unkill-all"):
        out = call("POST", f"/admin/{a.cmd}", admin_key(), {})
    elif a.cmd == "chat":
        out = call("POST", "/v1/chat/completions", agent_key(a.args[0]),
                   {"model": a.model, "max_tokens": a.max_tokens,
                    "messages": [{"role": "user", "content": a.args[1]}]})
    else:
        sys.exit(__doc__)
    print(out[0], json.dumps(out[1], indent=2))


if __name__ == "__main__":
    main()
