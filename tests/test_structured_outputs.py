"""V2 runtime, M3: no decision of code is taken by reading prose.

Breakdown, review verdict and the Dev's outcome come back as validated
JSON when the SDK backend runs (``output_schema`` on ``ClaudeCLI.run`` →
``ClaudeResult.structured``). The text parsers stay only as the CLI
backend's fallback (invariant I13: the rollback exists until M7).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, SystemMessage

from theswarm.agents.schemas import Breakdown, DevOutcome, ReviewVerdict
from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import ClaudeCLI, ClaudeResult


# ── The schemas themselves ───────────────────────────────────────────


def test_schemas_are_draft_07_friendly_objects():
    for model in (Breakdown, ReviewVerdict, DevOutcome):
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert "format" not in str(schema)  # the SDK validator ignores it; keep it out


def test_review_verdict_defaults_and_enums():
    verdict = ReviewVerdict.model_validate({"decision": "APPROVE", "summary": "fine"})
    assert verdict.issues == []
    with pytest.raises(Exception):
        ReviewVerdict.model_validate({"decision": "MAYBE", "summary": "x"})


def test_dev_outcome_carries_the_file_fallback():
    outcome = DevOutcome.model_validate({
        "status": "implemented", "summary": "done",
        "files": [{"path": "src/x.py", "content": "print(1)\n"}],
    })
    assert outcome.files[0].path == "src/x.py"


# ── The SDK backend asks for, and returns, the structure ─────────────


def _init() -> SystemMessage:
    return SystemMessage(subtype="init", data={"apiKeySource": "none", "session_id": "s-1"})


def _result(**overrides) -> ResultMessage:
    fields = dict(
        subtype="success", duration_ms=10, duration_api_ms=8, is_error=False,
        num_turns=1, session_id="s-1", total_cost_usd=0.1,
        usage={"input_tokens": 10, "output_tokens": 5}, result='{"decision": "APPROVE"}',
    )
    fields.update(overrides)
    return ResultMessage(**fields)


def _queries(*message_lists):
    calls: list[dict] = []
    remaining = list(message_lists)

    async def fake(prompt, options):
        calls.append({"prompt": prompt, "options": options})
        for message in remaining.pop(0):
            yield message

    return fake, calls


@pytest.fixture
def sdk(monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    return ClaudeCLI(model="haiku", timeout=30)


async def test_a_schema_becomes_output_format_and_structured_output_comes_back(sdk, monkeypatch):
    schema = ReviewVerdict.model_json_schema()
    payload = {"decision": "APPROVE", "summary": "fine", "issues": []}
    fake, calls = _queries([_init(), _result(structured_output=payload)])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)

    result = await sdk.run("review", output_schema=schema)

    options = calls[0]["options"]
    assert isinstance(options, ClaudeAgentOptions)
    assert options.output_format == {"type": "json_schema", "schema": schema}
    assert result.structured == payload
    assert result.backend == "sdk"


async def test_no_schema_means_no_output_format(sdk, monkeypatch):
    fake, calls = _queries([_init(), _result()])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)
    result = await sdk.run("plan")
    assert calls[0]["options"].output_format is None
    assert result.structured is None


async def test_a_schema_without_a_structured_answer_is_a_failed_call(sdk, monkeypatch):
    fake, _ = _queries([_init(), _result(structured_output=None)])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)
    with pytest.raises(RuntimeError, match="structured"):
        await sdk.run("review", output_schema=ReviewVerdict.model_json_schema())


async def test_exhausted_structured_retries_is_a_failed_call(sdk, monkeypatch):
    fake, _ = _queries([_init(), _result(
        subtype="error_max_structured_output_retries", is_error=True, result=None,
    )])
    monkeypatch.setattr(claude_mod, "_sdk_query", fake)
    with pytest.raises(RuntimeError, match="error_max_structured_output_retries"):
        await sdk.run("review", output_schema=ReviewVerdict.model_json_schema())


async def test_a_resumed_timeout_keeps_the_schema(sdk):
    from theswarm.tools.claude import _SDKTimeout

    seen: list[dict] = []

    async def run_sdk(prompt, *, workdir, timeout, permission_mode, drop_oauth_env=False,
                      resume=None, output_schema=None):
        seen.append({"resume": resume, "schema": output_schema})
        if len(seen) == 1:
            raise _SDKTimeout("SDK timed out after 30s", session_id="s-1")
        return ClaudeResult(text="{}", backend="sdk", structured={"decision": "COMMENT"})

    schema = ReviewVerdict.model_json_schema()
    from unittest.mock import patch
    with patch.object(sdk, "_run_sdk", side_effect=run_sdk):
        result = await sdk.run("review", output_schema=schema)
    assert seen[1]["resume"] == "s-1"
    assert seen[1]["schema"] == schema
    assert result.structured == {"decision": "COMMENT"}


# ── The agents use the structure first, the text only as fallback ────


def _claude_returning(structured=None, text=""):
    claude = MagicMock()
    claude.run = AsyncMock(return_value=ClaudeResult(
        text=text, backend="sdk", structured=structured, input_tokens=1, output_tokens=1,
        total_tokens=2, cost_usd=0.01,
    ))
    return claude


async def test_breakdown_creates_the_tasks_from_the_structure():
    from theswarm.agents.techlead import breakdown_stories

    story = {"number": 7, "title": "Story", "body": "Do it", "labels": ["status:ready"]}
    github = AsyncMock()
    # first call: the ready stories; second: the `role:dev` children (none yet)
    github.get_issues = AsyncMock(side_effect=[[story], []])
    github.create_issue = AsyncMock(return_value={"number": 8})
    claude = _claude_returning(structured={"tasks": [
        {"title": "Implement X", "body": "Body", "labels": ["role:dev", "status:ready"]},
        {"title": "Test X", "body": "Tests"},
    ]}, text="not json at all")

    await breakdown_stories({
        "github": github, "claude": claude, "workspace": "/ws", "context": "",
    })

    assert claude.run.await_args.kwargs.get("output_schema") == Breakdown.model_json_schema()
    assert github.create_issue.await_count == 2
    second = github.create_issue.await_args_list[1].kwargs
    assert second["labels"] == ["role:dev", "status:ready"]  # the schema's default
    assert "Parent: #7" in second["body"]


async def test_breakdown_falls_back_to_the_text_on_a_text_backend():
    from theswarm.agents.techlead import breakdown_stories

    story = {"number": 7, "title": "Story", "body": "Do it", "labels": ["status:ready"]}
    github = AsyncMock()
    github.get_issues = AsyncMock(side_effect=[[story], []])
    github.create_issue = AsyncMock(return_value={"number": 8})
    claude = _claude_returning(structured=None, text='[{"title": "From text", "body": "b"}]')

    await breakdown_stories({"github": github, "claude": claude, "workspace": "/ws", "context": ""})

    assert github.create_issue.await_args.kwargs["title"] == "From text"


async def test_review_takes_the_verdict_from_the_structure_not_the_prose():
    from theswarm.agents.techlead import _review_single_pr

    github = AsyncMock()
    github.get_pr_files = AsyncMock(return_value=[{"filename": "x.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "+1"}])
    github.create_pr_review = AsyncMock(return_value={"id": 1})
    github.get_issue_comments = AsyncMock(return_value=[])
    claude = _claude_returning(
        structured={"decision": "REQUEST_CHANGES", "summary": "broken",
                    "issues": [{"severity": "critical", "file": "x.py", "description": "injection"}]},
        text="APPROVE",  # the prose says the opposite; it must not be read
    )
    pr = {"number": 42, "title": "[#5] T", "body": "Closes #5", "head": {"sha": "abc", "ref": "b"}}

    review = await _review_single_pr(github, claude, pr, context="")

    assert claude.run.await_args.kwargs.get("output_schema") == ReviewVerdict.model_json_schema()
    assert review["decision"] == "REQUEST_CHANGES"
    assert github.create_pr_review.await_args.kwargs["event"] == "REQUEST_CHANGES"


async def test_a_structured_approve_is_never_downgraded_as_salvaged():
    from theswarm.agents.techlead import _review_single_pr

    github = AsyncMock()
    github.get_pr_files = AsyncMock(return_value=[])
    github.create_pr_review = AsyncMock(return_value={"id": 1})
    claude = _claude_returning(
        structured={"decision": "APPROVE", "summary": "clean", "issues": []},
        text="I'm not going to run through that wrap-up checklist. APPROVE",
    )
    pr = {"number": 43, "title": "T", "body": "", "head": {"sha": "abc", "ref": "b"}}

    review = await _review_single_pr(github, claude, pr, context="")

    assert review["decision"] == "APPROVE"


async def test_dev_outcome_already_satisfied_closes_without_regex(tmp_path, monkeypatch):
    from unittest.mock import patch

    from theswarm.agents import dev as dev_mod

    github = AsyncMock()
    github.get_issue_comments = AsyncMock(return_value=[])
    github.get_open_prs = AsyncMock(return_value=[])
    claude = _claude_returning(
        structured={"status": "already_satisfied", "summary": "", "reason": "sibling #3 did it",
                    "already_satisfied_file": "src/x.py"},
        text="some prose with no marker",
    )

    with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
         patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)), \
         patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="")):
        out = await dev_mod.implement_task({
            "task": {"number": 5, "title": "T", "body": "B"}, "claude": claude,
            "workspace": str(tmp_path), "github": github, "context": "",
        })

    assert claude.run.await_args.kwargs.get("output_schema") == DevOutcome.model_json_schema()
    assert out["already_satisfied"] is True
    github.close_issue.assert_awaited_once()


async def test_a_structured_implemented_claim_on_a_clean_tree_is_no_changes(tmp_path):
    """I3: the tree is the truth. 'implemented' with nothing in the tree is
    'no changes produced', and the prose is not consulted for a marker."""
    from unittest.mock import patch

    from theswarm.agents import dev as dev_mod

    github = AsyncMock()
    github.get_issue_comments = AsyncMock(return_value=[])
    github.get_open_prs = AsyncMock(return_value=[])
    claude = _claude_returning(
        structured={"status": "implemented", "summary": "done"},
        text="ALREADY_SATISFIED: src/x.py - stale marker in prose",
    )

    with patch("theswarm.tools.git.create_branch", new=AsyncMock()), \
         patch("theswarm.tools.git.commit_all", new=AsyncMock(return_value=False)), \
         patch("theswarm.tools.git.get_diff_stat", new=AsyncMock(return_value="")):
        out = await dev_mod.implement_task({
            "task": {"number": 5, "title": "T", "body": "B"}, "claude": claude,
            "workspace": str(tmp_path), "github": github, "context": "",
        })

    assert out["result"] == "no changes produced"
    assert not out.get("already_satisfied")
    github.close_issue.assert_not_awaited()


async def test_dev_outcome_files_are_written_with_the_same_path_rules(tmp_path, monkeypatch):
    from theswarm.agents import dev as dev_mod

    written = dev_mod._write_outcome_files([
        {"path": "src/new.py", "content": "print(1)"},
        {"path": "../escape.py", "content": "x"},
        {"path": "/abs/escape.py", "content": "x"},
    ], str(tmp_path))
    assert written == 1
    assert (tmp_path / "src" / "new.py").read_text() == "print(1)\n"
    assert not (tmp_path.parent / "escape.py").exists()
