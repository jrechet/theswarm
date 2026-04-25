"""SprintComposer — turns a free-form request into IssueDrafts."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.application.services.sprint_composer import (
    IssueDraft,
    SprintComposer,
    SprintDraft,
    _parse_response,
)


def _claude_returning(text: str):
    """Build a fake Claude factory returning a stubbed CLI."""
    fake_cli = type("FakeCLI", (), {"run": AsyncMock(return_value=type("R", (), {"text": text})())})()
    return lambda: fake_cli


class TestParseResponse:
    def test_parses_clean_json(self):
        text = '{"issues": [{"title": "Add LICENSE", "body": "MIT", "labels": ["status:backlog","role:dev"]}]}'
        d = _parse_response("req", text)
        assert len(d.issues) == 1
        assert d.issues[0].title == "Add LICENSE"
        assert "status:backlog" in d.issues[0].labels
        assert "role:dev" in d.issues[0].labels

    def test_strips_markdown_fences(self):
        text = '```json\n{"issues": [{"title": "X"}]}\n```'
        d = _parse_response("req", text)
        assert len(d.issues) == 1
        assert d.issues[0].title == "X"

    def test_enforces_required_labels(self):
        text = '{"issues": [{"title": "Y", "labels": ["component:api"]}]}'
        d = _parse_response("req", text)
        labels = d.issues[0].labels
        assert "status:backlog" in labels
        assert "role:dev" in labels
        assert "component:api" in labels

    def test_caps_at_five_issues(self):
        items = [{"title": f"Issue {i}"} for i in range(10)]
        import json as _json
        text = _json.dumps({"issues": items})
        d = _parse_response("req", text)
        assert len(d.issues) == 5

    def test_drops_invalid_entries(self):
        text = '{"issues": [{"title": ""}, "not-a-dict", {"title": "Good"}]}'
        d = _parse_response("req", text)
        titles = [i.title for i in d.issues]
        assert titles == ["Good"]

    def test_returns_empty_on_garbage(self):
        d = _parse_response("req", "lorem ipsum no json here")
        assert d.issues == ()
        assert d.raw_response.startswith("lorem")

    def test_returns_empty_on_bad_json(self):
        d = _parse_response("req", "{not json")
        assert d.issues == ()


class TestSprintComposer:
    async def test_calls_claude_and_parses(self):
        composer = SprintComposer(
            claude_factory=_claude_returning(
                '{"issues": [{"title": "Add tests", "body": "..."}]}'
            ),
        )
        d = await composer.draft("Add some tests please")
        assert len(d.issues) == 1
        assert d.issues[0].title == "Add tests"

    async def test_empty_request(self):
        composer = SprintComposer(claude_factory=_claude_returning("ignored"))
        d = await composer.draft("")
        assert d.issues == ()
        assert d.request == ""

    async def test_rejects_overlong_request(self):
        composer = SprintComposer(claude_factory=_claude_returning("ignored"))
        with pytest.raises(ValueError):
            await composer.draft("x" * 5000)
