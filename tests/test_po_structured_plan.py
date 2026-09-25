"""The PO's morning pick is a structured answer, not prose (V2 M3, extended).

2026-09-25, twice in Seq: "PO: could not parse planning JSON, using raw
text". `selected` stayed empty, no story was made ready, and a non-targeted
cycle's Dev had nothing to pick.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from theswarm.agents import po
from theswarm.agents.schemas import DailyPlan

PLAN = {"selected": [{"number": 7, "title": "Venue filter", "reason": "unblocks search"}],
        "daily_plan": "Today: the venue filter."}


def _result(text: str = "", structured=None):
    return SimpleNamespace(text=text, structured=structured, total_tokens=10, cost_usd=0.01, backend="sdk")


def test_a_structured_answer_is_taken_as_is():
    selected, plan = po._plan_of(_result(structured=PLAN))

    assert [s["number"] for s in selected] == [7]
    assert plan == "Today: the venue filter."


def test_json_wrapped_in_prose_or_fences_is_still_read():
    text = "Here is the plan:\n```json\n" + __import__("json").dumps(PLAN) + "\n```\nGood luck!"

    selected, plan = po._plan_of(_result(text=text))

    assert [s["number"] for s in selected] == [7] and plan.startswith("Today")


def test_an_invalid_structure_falls_back_to_the_text():
    text = __import__("json").dumps(PLAN)

    selected, _ = po._plan_of(_result(text=text, structured={"selected": "not a list"}))

    assert [s["number"] for s in selected] == [7]


def test_prose_without_a_plan_object_is_the_plan_and_selects_nothing(caplog):
    caplog.set_level(logging.WARNING, logger="theswarm.agents.po")

    selected, plan = po._plan_of(_result(text="I think we should do the venue filter."))

    assert selected == [] and plan == "I think we should do the venue filter."
    assert "could not parse planning JSON" in caplog.text


async def test_the_planning_call_asks_for_the_schema_and_readies_the_pick():
    github = SimpleNamespace(
        get_issues=AsyncMock(return_value=[{"number": 7, "title": "Venue filter", "labels": [{"name": "status:backlog"}]}]),
        remove_label=AsyncMock(), add_labels=AsyncMock(),
    )
    claude = SimpleNamespace(run=AsyncMock(return_value=_result(structured=PLAN)))

    out = await po.select_daily_issues({"github": github, "claude": claude, "workspace": "/ws"})

    assert claude.run.await_args.kwargs["output_schema"] == DailyPlan.model_json_schema()
    github.add_labels.assert_awaited_with(7, ["status:ready"])
    assert out["daily_plan"] == "Today: the venue filter."


@pytest.mark.parametrize("field", ["selected", "daily_plan"])
def test_the_schema_names_what_the_code_reads(field):
    assert field in DailyPlan.model_json_schema()["properties"]
