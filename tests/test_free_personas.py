"""Free personas (phase B, B3, second half): what the owner adds to a flow.

A prompt the owner writes, run at an insertion point with one effect. Before
the merge it reads each approved pull request once per head and comments or
blocks; after QA it writes a note on the feature's issue. It reads, it never
writes; a call that fails is a persona that did not speak.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from theswarm.agents import ci_gate, extras, techlead
from theswarm.application.services import team_yaml
from theswarm.application.services.agent_settings import AgentSettingsService
from theswarm.application.services.personas import PersonaService
from theswarm.application.services.team_yaml import TeamYamlError
from theswarm.domain.teams.extras import Extra, ExtraError, key_from
from theswarm.infrastructure.persistence.agent_settings_repo import SQLiteAgentSettingsRepository
from theswarm.infrastructure.persistence.persona_repo import SQLitePersonaRepository
from theswarm.infrastructure.persistence.sqlite_repos import init_db

APP = "jrechet/concert-tour-app"
SECURITY = {"key": "security", "name": "Security reviewer", "prompt": "Refuse a secret in the code.",
            "point": "before_merge", "effect": "block", "model": ""}
WRITER = {"key": "changelog", "name": "Changelog writer", "prompt": "One changelog line.",
          "point": "after_qa", "effect": "comment", "model": ""}


# ── The record ─────────────────────────────────────────────────────────


def test_a_free_persona_has_a_point_and_an_effect_that_fits_it():
    assert Extra(scope=APP, key="security", name="Security reviewer", prompt="x", point="before_merge", effect="block")
    assert key_from("Security reviewer!") == "security-reviewer"
    for bad in (dict(point="before_dev"),            # not a point yet
                dict(point="after_qa", effect="block"),  # nothing left to block
                dict(key="dev"),                      # a role of the team
                dict(key="Security"), dict(prompt=" "), dict(model="gpt")):
        with pytest.raises(ExtraError):
            Extra(**{"scope": APP, "key": "security", "name": "Security reviewer", "prompt": "x",
                     "point": "before_merge", "effect": "comment", **bad})


# ── The team carries them ──────────────────────────────────────────────


@pytest.fixture
async def personas(tmp_path):
    conn = await init_db(str(tmp_path / "e.db"))
    yield PersonaService(SQLitePersonaRepository(conn), AgentSettingsService(SQLiteAgentSettingsRepository(conn)))
    await conn.close()


async def test_a_project_s_persona_replaces_the_instance_s_and_a_disabled_one_is_left_out(personas):
    await personas.save_extra("", name="Security", prompt="Every project's.", point="before_merge")
    await personas.save_extra("", name="Changelog", prompt="One line.", point="after_qa")
    await personas.save_extra(APP, name="Security", prompt="This project's: no raw SQL.", point="before_merge", effect="block")
    await personas.save_extra(APP, name="Changelog", prompt="One line.", point="after_qa", enabled=False)

    assert [(e.key, e.prompt) for e in personas.extras_for(APP)] == [("security", "This project's: no raw SQL.")]
    assert [e.key for e in personas.extras_for("o/other")] == ["changelog", "security"]


async def test_the_team_file_and_the_cycle_s_pin_carry_them(personas):
    await personas.save_extra(APP, name="Security reviewer", prompt="Refuse a secret\nin the code.", point="before_merge",
                              effect="block", model="opus")
    text = personas.export_yaml(APP)
    assert "extras:" in text and "security-reviewer:" in text and "effect: block" in text

    await personas.delete_extra(APP, "security-reviewer")
    assert "extras" not in personas.export_yaml(APP)
    await personas.import_yaml(APP, text)
    assert personas.export_yaml(APP) == text

    _, _, label = await personas.for_thread("thread-1", APP)
    pinned = personas.extras_of_thread("thread-1")
    assert pinned == [{"key": "security-reviewer", "name": "Security reviewer", "prompt": "Refuse a secret\nin the code.",
                       "point": "before_merge", "effect": "block", "model": "opus"}]
    await personas.delete_extra(APP, "security-reviewer")  # edited while the cycle runs
    await personas.for_thread("thread-1", APP)
    assert personas.extras_of_thread("thread-1") == pinned  # a resume meets the team it started with

    with pytest.raises(TeamYamlError, match="extras.x"):
        team_yaml.load_team("format: 1\npersonas: {}\nextras:\n  x: {point: after_qa, effect: block, prompt: y}", APP)


# ── Before the merge ───────────────────────────────────────────────────


class _GitHub:
    def __init__(self, statuses=()):
        self.statuses: list[dict] = list(statuses)
        self.pr_comments: list[tuple[int, str]] = []
        self.issue_comments: dict[int, list[str]] = {}
        self.labels: dict[int, set] = {}
        self.merged: list[int] = []
        self.prs = [{"number": 7, "title": "[#11] Add the route", "body": "Closes #11", "head": "feat/issue-11-x",
                     "head_sha": "h1", "base": "main"}]

    async def get_open_prs(self):
        return [p for p in self.prs if p["number"] not in self.merged]

    async def get_ci_checks(self, sha):
        return [{"name": s["context"], "state": s["state"]} for s in self.statuses if s["sha"] == sha]

    async def get_pr_files(self, number):
        return [{"filename": "src/app.py", "status": "modified", "additions": 1, "deletions": 0,
                 "patch": "+API_KEY = 'sk-123'"}]

    async def create_commit_status(self, sha, state, description, *, context=""):
        self.statuses.append({"sha": sha, "state": state, "description": description, "context": context})

    async def create_pr_comment(self, number, body):
        self.pr_comments.append((number, body))

    async def add_comment(self, number, body):
        self.issue_comments.setdefault(number, []).append(body)

    async def get_issue_comments(self, number):
        return [{"body": b} for b in self.issue_comments.get(number, [])]

    async def add_labels(self, number, labels):
        self.labels.setdefault(number, set()).update(labels)

    async def remove_label(self, number, label):
        self.labels.setdefault(number, set()).discard(label)

    async def get_review_status(self, sha):
        return None

    async def behind_by(self, head, base="main"):
        return 0

    async def merge_pr(self, number, merge_method="squash"):
        self.merged.append(number)
        return True

    async def delete_branch(self, name):
        pass

    async def get_issue(self, number):
        return None

    async def get_issues(self, labels=None, state="open"):
        return []


class _Claude:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def run(self, prompt, **kw):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(structured=answer, text="", cost_usd=0.2, total_tokens=100)


def _state(github, claude, *team):
    return {"github": github, "claude": claude, "github_repo": "o/r", "extras": list(team),
            "reviews": [{"pr_number": 7, "decision": "APPROVE"}]}


async def test_a_blocking_persona_sends_the_approved_pr_back_and_it_does_not_merge():
    github = _GitHub()
    claude = _Claude({"ok": False, "summary": "A key is committed.",
                      "findings": [{"file": "src/app.py", "description": "API_KEY is hardcoded"}]})

    result = await techlead.merge_approved_prs(_state(github, claude, SECURITY), ci_wait_seconds=0)

    assert github.merged == [] and result["extra_blocked_prs"] == [7] and result["cost_usd"] == 0.2
    assert "status:ready" in github.labels[11]  # the task is back with the Dev
    assert any("API_KEY is hardcoded" in body for body in github.issue_comments[11])
    assert github.pr_comments and "Security reviewer" in github.pr_comments[0][1]
    assert "Refuse a secret in the code." in claude.prompts[0] and "API_KEY = 'sk-123'" in claude.prompts[0]
    assert "Where your instructions come from" in claude.prompts[0]
    assert {s["context"]: s["state"] for s in github.statuses}["theswarm/extra-security"] == "failure"


async def test_a_persona_that_finds_nothing_lets_it_merge_and_is_not_asked_twice():
    github = _GitHub()
    claude = _Claude({"ok": True, "summary": "No secret."})
    await techlead.merge_approved_prs(_state(github, claude, SECURITY), ci_wait_seconds=0)
    assert github.merged == [7] and len(claude.prompts) == 1 and github.pr_comments == []

    github.merged.clear()  # the same head, a later pass: its word stands
    silent = _Claude()
    await techlead.merge_approved_prs(_state(github, silent, SECURITY), ci_wait_seconds=0)
    assert silent.prompts == [] and github.merged == [7]


async def test_a_commenting_persona_never_stops_the_merge():
    github = _GitHub()
    reviewer = {**SECURITY, "effect": "comment"}
    claude = _Claude({"ok": False, "summary": "A key is committed.", "findings": []})
    result = await techlead.merge_approved_prs(_state(github, claude, reviewer), ci_wait_seconds=0)
    assert github.merged == [7] and result["extra_blocked_prs"] == [] and len(github.pr_comments) == 1


async def test_a_persona_that_fails_did_not_speak():
    github = _GitHub()
    claude = _Claude(RuntimeError("SDK timed out after 300s"))
    result = await techlead.merge_approved_prs(_state(github, claude, SECURITY), ci_wait_seconds=0)
    assert github.merged == [7] and result["extra_blocked_prs"] == []

    odd = _Claude({"verdict": "fine"})  # no shape this code reads
    github.merged.clear()
    await techlead.merge_approved_prs(_state(github, odd, SECURITY), ci_wait_seconds=0)
    assert github.merged == [7]


async def test_without_a_free_persona_the_merge_is_what_it_was():
    github, claude = _GitHub(), _Claude()
    result = await techlead.merge_approved_prs(_state(github, claude), ci_wait_seconds=0)
    assert github.merged == [7] and claude.prompts == [] and "cost_usd" not in result


def test_a_persona_s_word_is_never_read_as_ci():
    """Its `failure` on the head read as red CI would send the PR back a second time, as a bug."""
    verdict = ci_gate.ci_verdict([{"name": "theswarm/extra-security", "state": "failure"},
                                  {"name": "theswarm/review", "state": "success"},
                                  {"name": "tests", "state": "success"}])
    assert verdict.state == "green"


# ── After QA ───────────────────────────────────────────────────────────


async def test_after_qa_a_persona_writes_its_note_once():
    github = _GitHub()
    claude = _Claude({"ok": True, "summary": "- Added: the venue search."})
    state = {"claude": claude, "extras": [WRITER, SECURITY]}
    delivered = [{"number": 7, "title": "[#11] Add the route"}]

    out = await extras.run_after_qa(state, github, issue=10, cycle_id="abc123abc123", delivered=delivered,
                                    demo_report={"quality_gates": {"unit_tests": {"status": "pass"}}})
    assert out["spoke"] == ["Changelog writer"] and len(claude.prompts) == 1  # the reviewer is not placed here
    note = github.issue_comments[10][0]
    assert "<!-- swarm:extra changelog abc123abc123 -->" in note and "the venue search" in note
    assert "**Changelog writer**\n" in note and "nothing to change" not in note  # a note, not a verdict
    assert "PR #7" in claude.prompts[0] and "unit_tests: pass" in claude.prompts[0]

    again = await extras.run_after_qa(state, github, issue=10, cycle_id="abc123abc123", delivered=delivered,
                                      demo_report=None)  # the node re-run after a restart
    assert again["spoke"] == [] and len(github.issue_comments[10]) == 1


def test_the_graph_has_the_node_and_the_flows_name_it():
    from theswarm import cycle_graph
    from theswarm.domain.teams.templates import template

    assert "extras_after_qa" in cycle_graph.build_cycle_graph().get_graph().nodes
    assert "extras_after_qa" in template("feature").path and "extras_after_qa" in template("fix").path
    assert "extras_after_qa" not in template("review").path  # no QA, nothing after it


# ── Settings → Agents ──────────────────────────────────────────────────


async def test_the_page_adds_changes_and_removes_a_free_persona(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from theswarm.application.events.bus import EventBus
    from theswarm.domain.projects.entities import Project
    from theswarm.domain.projects.value_objects import RepoUrl
    from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, SQLiteProjectRepository
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    conn = await init_db(str(tmp_path / "page.db"))
    try:
        projects = SQLiteProjectRepository(conn)
        await projects.save(Project(id="concert-tour-app", repo=RepoUrl(APP)))
        app = create_web_app(projects, SQLiteCycleRepository(conn), EventBus(), SSEHub(), base_path="/swarm", db=conn)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            page = (await client.get("/settings/agents", headers={"accept": "text/html"})).text
            assert 'data-testid="extras"' in page and 'data-testid="extra-new"' in page

            added = await client.post("/settings/agents/extra", data={
                "team": APP, "name": "Security reviewer", "point": "before_merge", "effect": "block",
                "prompt": "Refuse a secret in the code."})
            assert added.status_code == 303 and "team_saved=extra" in added.headers["location"]
            assert [e.key for e in app.state.personas.extras_for(APP)] == ["security-reviewer"]

            page = (await client.get(f"/settings/agents?team={APP}", headers={"accept": "text/html"})).text
            assert 'data-key="security-reviewer"' in page and "Refuse a secret in the code." in page

            off = await client.post("/settings/agents/extra", data={  # the box unticked: out of the flow, kept
                "team": APP, "key": "security-reviewer", "name": "Security reviewer", "point": "before_merge",
                "effect": "block", "prompt": "Refuse a secret in the code."})
            assert off.status_code == 303 and app.state.personas.extras_for(APP) == []
            assert len(app.state.personas.extras_of(APP)) == 1

            wrong = await client.post("/settings/agents/extra", data={
                "team": APP, "name": "Changelog", "point": "after_qa", "effect": "block", "prompt": "One line."})
            assert wrong.status_code == 400 and "may comment" in wrong.text

            await client.post("/settings/agents/extra", data={"team": APP, "key": "security-reviewer", "remove": "1"})
            assert app.state.personas.extras_of(APP) == []
    finally:
        await conn.close()
