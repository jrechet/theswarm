"""An empty breakdown is asked again, never taken for "nothing to build".

concert-tour-app#897 ("Change a venue", a PATCH route main did not have) was
broken down on 2026-11-15 into an empty task list — the schema let `tasks`
default to `[]` — and its cycle ended "completed" with nothing built, beside
#898's three merged PRs in the same batch.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from theswarm.agents import techlead
from theswarm.agents.schemas import Breakdown


def _answer(tasks):
    return SimpleNamespace(structured={"tasks": tasks}, text="", total_tokens=10, cost_usd=0.1)


class _Claude:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def run(self, prompt, **kw):
        self.prompts.append(prompt)
        return self.answers.pop(0)


class _GitHub:
    def __init__(self):
        self.created: list[str] = []

    async def get_issue(self, number):
        return {"number": number, "title": "Change a venue", "body": "PATCH /api/v1/venues/{id}",
                "state": "open", "labels": [{"name": "status:backlog"}]}

    async def get_issues(self, labels=None, state="open"):
        return []

    async def create_issue(self, title, body, labels):
        self.created.append(title)
        return {"number": 900 + len(self.created)}

    async def remove_label(self, number, label):
        pass

    async def add_labels(self, number, labels):
        pass


def test_a_breakdown_has_at_least_one_task():
    with pytest.raises(ValidationError):
        Breakdown.model_validate({"tasks": []})
    with pytest.raises(ValidationError):
        Breakdown.model_validate({})


async def test_an_empty_answer_is_asked_once_more():
    claude = _Claude(_answer([]), _answer([{"title": "Add the PATCH route"}]))
    github = _GitHub()

    result = await techlead.breakdown_stories({"github": github, "claude": claude, "target_issue": 897})

    assert github.created == ["Add the PATCH route"]
    assert len(claude.prompts) == 2 and claude.prompts[1].endswith(techlead.EMPTY_BREAKDOWN_NOTE)
    assert result["cost_usd"] == pytest.approx(0.2)


async def test_twice_empty_creates_nothing_and_says_so():
    claude = _Claude(_answer([]), _answer([]))
    github = _GitHub()

    result = await techlead.breakdown_stories({"github": github, "claude": claude, "target_issue": 897})

    assert github.created == [] and len(claude.prompts) == 2
    assert result["result"] == "Broke down 1 stories into 0 tasks"
