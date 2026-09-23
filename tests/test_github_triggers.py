"""V2 runtime, M8: the GitHub-native doors.

A label on an issue starts a targeted cycle the way ▶ Play does; `@swarm
<instruction>` from the owner on a pull request sends the instruction to
the Dev as a review's REQUEST_CHANGES would; the TechLead's verdict is a
commit status on the PR; the repo page links to what the swarm learned.
Owner only, signature-checked, one trigger per repo per minute.
"""

from __future__ import annotations

import hashlib
import hmac
import json
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


# ── The handler: parsing and decisions ───────────────────────────────


def _labeled(label="swarm:go", sender="jrechet", number=41, is_pr=False):
    issue = {"number": number, "title": "Do it", "body": "please"}
    if is_pr:
        issue["pull_request"] = {"url": "x"}
    return {"action": "labeled", "label": {"name": label}, "issue": issue,
            "repository": {"full_name": REPO}, "sender": {"login": sender}}


def _comment(body, sender="jrechet", number=77, is_pr=True):
    issue = {"number": number, "title": "[#5] Feature", "body": "Closes #5"}
    if is_pr:
        issue["pull_request"] = {"url": "x"}
    return {"action": "created", "comment": {"body": body}, "issue": issue,
            "repository": {"full_name": REPO}, "sender": {"login": sender}}


def test_a_go_label_on_an_issue_is_recognised():
    handler = WebhookHandler()
    event = handler.parse_event("issues", _labeled())
    assert event.label == "swarm:go" and event.issue_number == 41 and not event.issue_is_pr
    assert handler.is_go_label(event) is True
    assert handler.is_go_label(handler.parse_event("issues", _labeled(label="bug"))) is False
    assert handler.is_go_label(handler.parse_event("issues", _labeled(is_pr=True))) is False


def test_the_label_name_is_configurable(monkeypatch):
    monkeypatch.setenv("SWARM_GO_LABEL", "build-me")
    handler = WebhookHandler()
    assert handler.is_go_label(handler.parse_event("issues", _labeled(label="build-me"))) is True
    assert handler.is_go_label(handler.parse_event("issues", _labeled(label="swarm:go"))) is False


@pytest.mark.parametrize("body,expected", [
    ("@swarm add a test for the empty case", "add a test for the empty case"),
    ("@Swarm: rename the function", "rename the function"),
    ("@swarm", ""),
    ("@swarmbot hi", None),
    ("please @swarm do it", None),
    ("/swarm implement", None),
])
def test_an_instruction_is_the_text_after_the_mention(body, expected):
    handler = WebhookHandler()
    event = handler.parse_event("issue_comment", _comment(body))
    assert handler.swarm_instruction(event) == expected


def test_an_instruction_on_a_plain_issue_is_not_one():
    handler = WebhookHandler()
    event = handler.parse_event("issue_comment", _comment("@swarm do it", is_pr=False))
    assert handler.swarm_instruction(event) is None


def test_only_the_owner_counts():
    handler = WebhookHandler()
    event = handler.parse_event("issues", _labeled(sender="Jrechet"))
    assert handler.is_owner(event, "jrechet") is True
    assert handler.is_owner(event, "someone") is False
    assert handler.is_owner(event, "") is False


def test_the_cooldown_is_per_repository():
    webhooks_mod._last_trigger.clear()
    assert webhooks_mod._cooling_down("a/b", now=100.0) is False
    assert webhooks_mod._cooling_down("a/b", now=130.0) is True
    assert webhooks_mod._cooling_down("c/d", now=130.0) is False
    assert webhooks_mod._cooling_down("a/b", now=161.0) is False


# ── The route, signed ────────────────────────────────────────────────


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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app
    await conn.close()


def _signed(payload: dict, event: str) -> tuple[bytes, dict]:
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-GitHub-Event": event, "X-Hub-Signature-256": sig, "Content-Type": "application/json"}


async def test_the_go_label_starts_a_targeted_cycle_and_is_removed(web):
    client, app = web
    started = AsyncMock(return_value=MagicMock(id="cyc-1"))
    gh = MagicMock()
    gh.remove_label = AsyncMock()
    body, headers = _signed(_labeled(), "issues")
    with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle", started), \
         patch("theswarm.tools.github.GitHubClient", return_value=gh):
        response = await client.post("/webhooks/github", content=body, headers=headers)

    assert response.status_code == 200
    started.assert_awaited_once()
    args = started.await_args.args
    assert args[1:4] == ("jrechet", "concert-tour-app", 41)
    gh.remove_label.assert_awaited_once_with(41, "swarm:go")


async def test_a_label_from_someone_else_starts_nothing(web):
    client, app = web
    started = AsyncMock()
    body, headers = _signed(_labeled(sender="stranger"), "issues")
    with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle", started):
        response = await client.post("/webhooks/github", content=body, headers=headers)
    assert response.status_code == 200
    started.assert_not_awaited()


async def test_an_unsigned_label_is_refused(web):
    client, app = web
    body = json.dumps(_labeled()).encode()
    response = await client.post("/webhooks/github", content=body, headers={
        "X-GitHub-Event": "issues", "X-Hub-Signature-256": "sha256=nope",
        "Content-Type": "application/json",
    })
    assert response.status_code == 401


async def test_two_labels_in_a_minute_are_one_cycle(web):
    client, app = web
    started = AsyncMock(return_value=MagicMock(id="cyc-1"))
    gh = MagicMock(remove_label=AsyncMock())
    body, headers = _signed(_labeled(), "issues")
    with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle", started), \
         patch("theswarm.tools.github.GitHubClient", return_value=gh):
        await client.post("/webhooks/github", content=body, headers=headers)
        await client.post("/webhooks/github", content=body, headers=headers)
    assert started.await_count == 1


async def test_an_instruction_on_a_pr_goes_to_the_dev_as_a_changes_note(web):
    from theswarm.agents.techlead import CHANGES_MARKER

    client, app = web
    started = AsyncMock(return_value=MagicMock(id="cyc-2"))
    gh = MagicMock()
    gh.get_pr = AsyncMock(return_value={
        "number": 77, "title": "[#5] Feature", "body": "", "head": "feat/5", "head_sha": "abc",
    })
    gh.add_comment = AsyncMock()
    gh.add_labels = AsyncMock()
    gh.remove_label = AsyncMock()
    gh.create_pr_comment = AsyncMock()
    body, headers = _signed(_comment("@swarm add a test for the empty case"), "issue_comment")
    with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle", started), \
         patch("theswarm.tools.github.GitHubClient", return_value=gh):
        response = await client.post("/webhooks/github", content=body, headers=headers)

    assert response.status_code == 200
    note = gh.add_comment.await_args.args
    assert note[0] == 5
    assert CHANGES_MARKER in note[1]
    assert "PR #77 (branch `feat/5`)" in note[1]
    assert "add a test for the empty case" in note[1]
    gh.add_labels.assert_awaited_once_with(5, ["status:ready"])
    gh.remove_label.assert_awaited_once_with(5, "status:review")
    assert started.await_args.args[3] == 5          # the cycle is pinned to the task
    assert "cyc-2" in gh.create_pr_comment.await_args.args[1]


async def test_an_instruction_on_a_pr_without_a_task_is_answered_not_run(web):
    client, app = web
    started = AsyncMock()
    gh = MagicMock()
    gh.get_pr = AsyncMock(return_value={"number": 78, "title": "Untracked", "body": "", "head": "x", "head_sha": "y"})
    gh.create_pr_comment = AsyncMock()
    body, headers = _signed(_comment("@swarm do it", number=78), "issue_comment")
    with patch("theswarm.presentation.web.routes.v2.start_targeted_cycle", started), \
         patch("theswarm.tools.github.GitHubClient", return_value=gh):
        await client.post("/webhooks/github", content=body, headers=headers)
    started.assert_not_awaited()
    assert "can't tell which task" in gh.create_pr_comment.await_args.args[1]


# ── The verdict as a commit status ───────────────────────────────────


async def test_the_review_verdict_is_published_as_a_commit_status():
    from theswarm.agents.techlead import _publish_review_status

    gh = MagicMock()
    gh.create_commit_status = AsyncMock()
    pr = {"number": 9, "head_sha": "deadbeef"}
    await _publish_review_status(gh, pr, "REQUEST_CHANGES", "injection in x.py")
    gh.create_commit_status.assert_awaited_once()
    args, kwargs = gh.create_commit_status.await_args
    assert args[0] == "deadbeef" and args[1] == "failure"
    assert args[2].startswith("Changes requested: injection")
    assert kwargs["context"] == "theswarm/review"

    gh.create_commit_status.reset_mock()
    await _publish_review_status(gh, pr, "APPROVE", "clean")
    assert gh.create_commit_status.await_args.args[1] == "success"

    gh.create_commit_status.reset_mock()
    await _publish_review_status(gh, {"number": 9}, "APPROVE", "no sha")
    gh.create_commit_status.assert_not_awaited()


async def test_a_status_that_fails_to_post_is_a_log_line():
    from theswarm.agents.techlead import _publish_review_status

    gh = MagicMock()
    gh.create_commit_status = AsyncMock(side_effect=RuntimeError("403"))
    await _publish_review_status(gh, {"number": 1, "head_sha": "a"}, "APPROVE", "ok")


# ── What the swarm learned ───────────────────────────────────────────


async def test_the_memory_page_groups_entries_by_category(web):
    client, app = web
    lines = [
        {"category": "conventions", "content": "Tests live in tests/.", "confidence": 0.9, "timestamp": "2026-09-20T07:00:00"},
        {"category": "errors", "content": "Never hardcode port 8000.", "confidence": 0.8, "timestamp": "2026-09-21T07:00:00"},
        {"category": "errors", "content": "pytest needs the venv.", "confidence": 0.7, "timestamp": "2026-09-22T07:00:00"},
    ]
    gh = MagicMock()
    gh.get_file_content = AsyncMock(return_value="\n".join(json.dumps(l) for l in lines))
    with patch("theswarm.tools.github.GitHubClient", return_value=gh):
        response = await client.get(f"/r/{REPO}/memory")
    assert response.status_code == 200
    html = response.text
    assert 'data-testid="memory-errors"' in html and 'data-testid="memory-conventions"' in html
    assert "Never hardcode port 8000." in html
    assert html.index("pytest needs the venv.") < html.index("Never hardcode port 8000.")  # newest first
    assert "3 entries" in html


async def test_the_repo_page_links_to_the_memory(web):
    client, app = web
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issues = AsyncMock(return_value=[])
        response = await client.get(f"/r/{REPO}")
    assert f"/swarm/r/{REPO}/memory" in response.text


def test_the_deploy_chain_carries_the_webhook_secret_only_when_present():
    from pathlib import Path

    import yaml

    action = yaml.safe_load(Path(".github/actions/write-env/action.yml").read_text())
    assert action["inputs"]["swarm_webhook_secret"].get("required", False) is False
    script = action["runs"]["steps"][0]["run"]
    assert 'if [ -n "$SWARM_WEBHOOK_SECRET" ]' in script
    cd = yaml.safe_load(Path(".github/workflows/cd.yml").read_text())
    for job in cd["jobs"].values():
        for step in job.get("steps", []):
            if "write-env" in str(step.get("uses", "")):
                assert step["with"]["swarm_webhook_secret"] == "${{ secrets.SWARM_WEBHOOK_SECRET }}"
