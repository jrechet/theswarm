"""A GitHub door answers within GitHub's timeout, then does its work.

GitHub gives a webhook ten seconds. The label door started its cycle
within a second (hook 686683585, 2026-09-27 19:50:54) and then took the
label off with a fresh GitHub client, fifteen seconds in all: GitHub
recorded the delivery as failed (status 500 after 10 s) although the
cycle ran. The doors now answer 202 at once and finish in a background
task; a task that fails is a log line, never a lost delivery.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.scheduling.webhook_handler import WebhookHandler
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.routes import webhooks as webhooks_mod
from theswarm.presentation.web.sse import SSEHub

SECRET = "s3cret"
REPO = "jrechet/concert-tour-app"


@pytest.fixture
async def web(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_OWNER_LOGIN", "jrechet")
    webhooks_mod._last_trigger.clear()
    conn = await init_db(str(tmp_path / "test.db"))
    app = create_web_app(
        SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
        EventBus(), SSEHub(), base_path="/swarm", db=conn,
    )
    app.state.webhook_handler = WebhookHandler(webhook_secret=SECRET)
    app.state.allowed_repos = [REPO]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c, app
    await conn.close()


def _labeled() -> dict:
    return {
        "action": "labeled", "label": {"name": "swarm:go"},
        "issue": {"number": 41, "title": "Stats", "labels": [{"name": "swarm:go"}]},
        "repository": {"full_name": REPO}, "sender": {"login": "jrechet"},
    }


def _signed(payload: dict, event: str) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-GitHub-Event": event, "X-Hub-Signature-256": sig, "Content-Type": "application/json"}


async def test_the_door_answers_before_its_work_is_done(web):
    client, app = web
    started = AsyncMock(return_value=MagicMock(id="cyc-1"))

    async def slow_remove(number, label):
        await asyncio.sleep(0.4)

    gh = MagicMock(remove_label=AsyncMock(side_effect=slow_remove))
    body, headers = _signed(_labeled(), "issues")
    with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle", started), \
         patch("theswarm.tools.github.GitHubClient", return_value=gh):
        before = time.monotonic()
        response = await client.post("/webhooks/github", content=body, headers=headers)
        answered_in = time.monotonic() - before
        assert response.status_code == 202
        assert answered_in < 0.3  # not the 0.4 s the label removal takes
        assert not gh.remove_label.await_count
        await webhooks_mod.drain_background(app)

    started.assert_awaited_once()
    gh.remove_label.assert_awaited_once_with(41, "swarm:go")


async def test_work_that_fails_is_a_log_line_not_a_lost_delivery(web, caplog):
    client, app = web
    started = AsyncMock(side_effect=RuntimeError("GitHub is down"))
    body, headers = _signed(_labeled(), "issues")
    with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle", started):
        response = await client.post("/webhooks/github", content=body, headers=headers)
        await webhooks_mod.drain_background(app)

    assert response.status_code == 202
    assert "GitHub is down" in caplog.text
    assert not app.state.webhook_tasks


async def test_a_stranger_s_label_is_still_answered_and_starts_nothing(web):
    client, app = web
    started = AsyncMock()
    payload = _labeled()
    payload["sender"] = {"login": "stranger"}
    body, headers = _signed(payload, "issues")
    with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle", started):
        response = await client.post("/webhooks/github", content=body, headers=headers)
        await webhooks_mod.drain_background(app)

    assert response.status_code == 202
    started.assert_not_awaited()
