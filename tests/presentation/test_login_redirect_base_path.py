"""After the access key, the browser lands under the base path.

Prod runs under `/swarm`. The wall sent an unauthenticated browser to
`/swarm/login?next=/r/jrechet/concert-tour-app` — the app's own path, no
prefix — and after the key `_safe_next` returned that path as it was: the
browser went to `https://bots.jrec.fr/r/jrechet/concert-tour-app` and got
Traefik's "404 page not found" (owner, 2026-10-06).
"""

from __future__ import annotations

import pytest

from theswarm.presentation.web.routes.auth_routes import _safe_next


@pytest.mark.parametrize("raw,base,expected", [
    ("/r/jrechet/concert-tour-app", "/swarm", "/swarm/r/jrechet/concert-tour-app"),
    ("/swarm/r/jrechet/concert-tour-app", "/swarm", "/swarm/r/jrechet/concert-tour-app"),  # already prefixed
    ("/r/x?new=5", "/swarm", "/swarm/r/x?new=5"),
    ("/r/x", "", "/r/x"),
    ("", "/swarm", "/swarm/"),
    ("", "", "/"),
    ("//evil.example", "/swarm", "/swarm/"),  # never an absolute URL
    ("https://evil.example/", "/swarm", "/swarm/"),
])
def test_the_next_path_lands_under_the_base_path(raw, base, expected):
    assert _safe_next(raw, base) == expected


async def test_after_the_key_the_browser_lands_under_the_base_path(tmp_path, monkeypatch):
    """Prod's flow under /swarm: the wall's `next` is the app path; the
    redirect after the key must carry the prefix, or Traefik answers 404."""
    from httpx import ASGITransport, AsyncClient

    from theswarm.application.events.bus import EventBus
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository, SQLiteProjectRepository, init_db,
    )
    from theswarm.presentation.web import auth as auth_mod
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    monkeypatch.setenv("SWARM_AUTH_DISABLED", "")
    monkeypatch.setenv("SWARM_SESSION_SECRET", "s")
    monkeypatch.setenv("SWARM_ACCESS_KEY", "k")
    auth_mod.reset_login_throttle()
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(), SSEHub(),
                         base_path="/swarm")
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            walled = await client.get("/r/jrechet/concert-tour-app", headers={"Accept": "text/html"})
            assert walled.status_code == 303
            assert walled.headers["location"] == "/swarm/login?next=%2Fr%2Fjrechet%2Fconcert-tour-app"
            r = await client.post("/login", data={"access_key": "k", "next": "/r/jrechet/concert-tour-app"})
            assert r.status_code == 303
            assert r.headers["location"] == "/swarm/r/jrechet/concert-tour-app"
    finally:
        await conn.close()
