"""A truncated breakdown still yields the tasks that arrived whole.

Prod cycle 8f7b4d6ec17f was asked to add artist search. The TechLead
produced a sound three-task breakdown, the response was cut mid-object by
the token budget, and `json.loads` rejected the array entire: 0 tasks
created, the Dev found nothing, and the cycle reported itself completed
five minutes later having done nothing at all.
"""

from __future__ import annotations

import json

import pytest

from theswarm.agents.techlead import _parse_tasks_json, _salvage_objects


# ── The production shape ───────────────────────────────────────────────


def test_a_breakdown_cut_mid_object_keeps_the_whole_ones():
    truncated = """[
      {"title": "Add artist filter param", "body": "Extend the endpoint"},
      {"title": "Filter the list in the UI", "body": "Search box above"},
      {"title": "Add test coverage", "body": "Case-insensitive, partial ma"""

    tasks = _parse_tasks_json(truncated)

    assert [t["title"] for t in tasks] == [
        "Add artist filter param", "Filter the list in the UI",
    ]


def test_nothing_complete_still_yields_nothing():
    assert _parse_tasks_json('[\n  {"title": "cut right aw') == []


# ── Sound input is untouched ───────────────────────────────────────────


def test_a_complete_array_parses_normally():
    payload = [{"title": "a", "body": "one"}, {"title": "b", "body": "two"}]
    assert _parse_tasks_json(json.dumps(payload)) == payload


def test_markdown_fences_are_still_stripped():
    payload = [{"title": "a", "body": "one"}]
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    assert _parse_tasks_json(fenced) == payload


def test_prose_around_a_complete_array_is_ignored():
    payload = [{"title": "a", "body": "one"}]
    assert _parse_tasks_json(
        f"Here is the breakdown:\n{json.dumps(payload)}\nHope that helps.",
    ) == payload


# ── The scanner's edge cases ───────────────────────────────────────────


def test_braces_inside_strings_do_not_confuse_the_scanner():
    text = '[{"title": "use {placeholder} here", "body": "a } in prose"}]'
    [task] = _salvage_objects(text)
    assert task["title"] == "use {placeholder} here"


def test_escaped_quotes_do_not_end_a_string_early():
    text = r'[{"title": "say \"hi\"", "body": "fine"}]'
    [task] = _salvage_objects(text)
    assert task["title"] == 'say "hi"'


def test_nested_objects_are_returned_once_at_top_level():
    text = '[{"title": "a", "meta": {"depth": 2}}]'
    salvaged = _salvage_objects(text)
    assert len(salvaged) == 1
    assert salvaged[0]["meta"] == {"depth": 2}


def test_a_malformed_object_is_dropped_not_fatal():
    text = '[{"title": "good"}, {bad json here}, {"title": "also good"}]'
    assert [t["title"] for t in _salvage_objects(text)] == ["good", "also good"]


def test_text_without_objects_yields_nothing():
    assert _salvage_objects("I could not break this down.") == []
