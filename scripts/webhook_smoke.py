"""Smoke-test the GitHub webhook door without starting a cycle (V2 M8).

A signed `ping` (what GitHub sends when a webhook is created) must answer
200 and trigger nothing; a wrongly signed one must answer 401; with no
secret configured the route answers 501. Stdlib only: the image does not
ship `scripts/`, so run it with the container's own environment, where the
secret lives and never leaves:

    docker exec -i $(docker ps -q -f name=theswarm_theswarm | head -1) \\
        /app/.venv/bin/python - < scripts/webhook_smoke.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get("SWARM_WEBHOOK_URL", "http://127.0.0.1:8091/webhooks/github")


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post(url: str, body: bytes, signed_with: str, opener=urllib.request.urlopen) -> int:
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "X-GitHub-Event": "ping",
        "X-Hub-Signature-256": signature(signed_with, body),
    })
    try:
        with opener(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def main(opener=urllib.request.urlopen) -> int:
    secret = os.environ.get("SWARM_WEBHOOK_SECRET", "")
    body = json.dumps({"zen": "Keep it logically awesome.", "hook_id": 0}).encode()
    good = post(URL, body, secret or "unset", opener)
    if good == 501:
        print("501: the webhook door is closed — SWARM_WEBHOOK_SECRET is not set in this container")
        return 1
    bad = post(URL, body, (secret or "unset") + "-wrong", opener)
    print(f"signed ping: {good} (want 200) · wrongly signed: {bad} (want 401)")
    return 0 if (good, bad) == (200, 401) else 1


if __name__ == "__main__":
    sys.exit(main())
