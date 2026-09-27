"""The harness closes a story whose cycle never reached the breakdown.

Three stories sat open on concert-tour-app after the subscription window
ran out (#351, #352 on 2026-09-25, #378 on the 27th): the harness had
created each one and its cycle died in under a minute, before any
sub-task existed. Nothing was built; the feature is asked for again on a
fresh issue; the dead story is closed with the cycle named.

The harness also read "Parent: #N" as a substring, like the server did
before #229: on a repository with #37 and #378 the one is inside the other.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _harness():
    spec = importlib.util.spec_from_file_location("cycle_e2e_dead", ROOT / "scripts/cycle_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(monkeypatch, tmp_path, *, state: str, children, closed=(), error: str = "", prs=()):
    harness = _harness()
    calls: list[tuple] = []

    def gh(*args):
        calls.append(args)
        return ""

    async def quiet(text):
        return False

    monkeypatch.setattr(harness, "_gh", gh)
    monkeypatch.setattr(harness, "wait_for_health", lambda *a, **k: True)
    monkeypatch.setattr(harness, "prs_before", lambda repo: set())
    monkeypatch.setattr(harness, "create_issue", lambda repo, text: 378)
    monkeypatch.setattr(harness, "start_cycle", lambda repo, issue: "62f353165e62")
    monkeypatch.setattr(harness, "wait_for", lambda cid, budget: (state, "po_morning", cid))
    monkeypatch.setattr(harness, "unfinished_children", lambda repo, parent: list(children))
    monkeypatch.setattr(harness, "closed_children", lambda repo, parent: list(closed))
    monkeypatch.setattr(harness, "cycle_record", lambda cid: {"error": error, "result": {}})
    monkeypatch.setattr(harness, "post_run", lambda record: None)
    monkeypatch.setattr(harness, "alert_mattermost", quiet)
    if prs:
        monkeypatch.setattr(harness, "prs_before", lambda repo, _seen=[set(), set(prs)]: _seen.pop(0))
    harness.run_one("jrechet/concert-tour-app", "Hide past concerts", None, 60, tmp_path / "runs.jsonl")
    return [c for c in calls if c[:2] == ("issue", "close")]


def test_a_story_the_cycle_never_broke_down_is_closed(monkeypatch, tmp_path):
    closes = _run(monkeypatch, tmp_path, state="failed", children=[],
                  error="RuntimeError: Claude SDK failed: You've hit your weekly limit · resets Sep 29, 4am (UTC)")

    (call,) = closes
    assert call[2] == "378" and "--repo" in call
    comment = call[call.index("--comment") + 1]
    assert "62f353165e62" in comment and "weekly limit" in comment and "fresh issue" in comment


def test_a_story_with_sub_tasks_stays_open_whatever_the_cycle_did(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, state="failed", children=[379, 380]) == []
    assert _run(monkeypatch, tmp_path, state="failed", children=[], closed=[379]) == []


def test_a_completed_cycle_never_closes_its_story_here(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, state="completed", children=[]) == []


def test_children_are_matched_on_the_exact_parent_number(monkeypatch):
    harness = _harness()
    issues = [
        {"number": 379, "body": "Do it.\n\nParent: #378", "labels": []},
        {"number": 40, "body": "Parent: #37", "labels": []},
        {"number": 41, "body": "Depends on: #37\n\nParent: #371", "labels": []},
    ]
    monkeypatch.setattr(harness, "_gh", lambda *a: json.dumps(issues))

    assert harness.unfinished_children("o/r", 37) == [40]
    assert harness.closed_children("o/r", 37) == [40]
    assert harness.unfinished_children("o/r", 378) == [379]
