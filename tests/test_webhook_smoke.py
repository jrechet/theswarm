"""The M8 webhook smoke check: a signed ping passes, a wrong one does not."""

from __future__ import annotations

import importlib.util
import pathlib
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _smoke():
    spec = importlib.util.spec_from_file_location("webhook_smoke", ROOT / "scripts/webhook_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server(secret: str | None):
    """A fake opener that answers like the route: 501 without a secret,
    200 for a good signature, 401 for a bad one."""
    smoke = _smoke()

    class Response:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout=20):
        if secret is None:
            raise urllib.error.HTTPError(request.full_url, 501, "closed", {}, None)
        expected = smoke.signature(secret, request.data)
        if request.headers["X-hub-signature-256"] != expected:
            raise urllib.error.HTTPError(request.full_url, 401, "bad", {}, None)
        return Response(200)

    return smoke, opener


def test_the_signature_is_github_s(monkeypatch):
    smoke = _smoke()
    import hashlib
    import hmac

    assert smoke.signature("s", b"x") == "sha256=" + hmac.new(b"s", b"x", hashlib.sha256).hexdigest()


def test_an_open_door_passes(monkeypatch, capsys):
    smoke, opener = _server("topsecret")
    monkeypatch.setenv("SWARM_WEBHOOK_SECRET", "topsecret")

    assert smoke.main(opener) == 0
    assert "signed ping: 200" in capsys.readouterr().out


def test_a_closed_door_says_so(monkeypatch, capsys):
    smoke, opener = _server(None)
    monkeypatch.delenv("SWARM_WEBHOOK_SECRET", raising=False)

    assert smoke.main(opener) == 1
    assert "501" in capsys.readouterr().out


def test_a_wrong_secret_fails(monkeypatch):
    smoke, opener = _server("the-real-one")
    monkeypatch.setenv("SWARM_WEBHOOK_SECRET", "a-stale-one")

    assert smoke.main(opener) == 1
