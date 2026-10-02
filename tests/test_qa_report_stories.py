"""The demo report says which stories the cycle delivered.

QA's report always carried `"user_stories": []`: the QA graph only sees the
base state, not the PRs the cycle opened. The PO's evening report reads it
first, found it empty on cycle b0251cf1141f ("The QA report's
`user_stories` field was empty, but the commit log shows one shipped
feature today") and spent turns reconstructing it from git.
"""

from __future__ import annotations

from types import SimpleNamespace

from theswarm import cycle_graph

PR_325 = {"number": 325, "title": "[#323] Implement GET /api/v1/stats/cities and /venues",
          "url": "https://github.com/jrechet/concert-tour-app/pull/325", "head": "feat/issue-323"}
PR_326 = {"number": 326, "title": "[#324] Write the stats tests", "url": "https://x/326"}


def test_the_stories_are_the_cycle_s_prs_and_what_was_already_there():
    stories = cycle_graph._stories_of({
        "prs": [PR_325, PR_326, {"not": "a pr"}],
        "merged_prs": [325],
        "already_satisfied": [322],
    })

    assert stories == [
        {"task": 323, "title": "[#323] Implement GET /api/v1/stats/cities and /venues",
         "pr": 325, "url": "https://github.com/jrechet/concert-tour-app/pull/325", "status": "merged"},
        {"task": 324, "title": "[#324] Write the stats tests", "pr": 326,
         "url": "https://x/326", "status": "open"},
        {"task": 322, "title": "", "pr": None, "url": "", "status": "already on main"},
    ]


def test_a_pr_counted_twice_is_one_story():
    stories = cycle_graph._stories_of({"prs": [PR_325, PR_325], "merged_prs": [325, 325]})

    assert [s["pr"] for s in stories] == [325]


def test_nothing_delivered_is_an_empty_list():
    assert cycle_graph._stories_of({}) == []


async def test_the_qa_node_puts_them_in_the_report(monkeypatch):
    async def fake_phase(rt, key, role, coro):
        coro.cancel() if hasattr(coro, "cancel") else None
        return {"demo_report": {"quality_gates": {}, "user_stories": []}, "tokens_used": 3, "cost_usd": 0.1}

    monkeypatch.setattr(cycle_graph, "_run_phase", fake_phase)
    monkeypatch.setattr(cycle_graph, "_invoke_agent", lambda graph, state: SimpleNamespace(cancel=lambda: None))

    async def noop(*_a, **_kw):
        return None

    rt = SimpleNamespace(
        base_state={}, enter=noop, progress=noop, phase_checkpoint=noop,
        config=SimpleNamespace(token_budget={}),
    )
    out = await cycle_graph.qa(
        {"prs": [PR_325], "merged_prs": [325]}, SimpleNamespace(context=rt),
    )

    assert out["demo_report"]["user_stories"][0]["pr"] == 325
    assert out["demo_report"]["quality_gates"] == {}


async def test_a_qa_phase_without_a_report_stays_without_one(monkeypatch):
    async def fake_phase(rt, key, role, coro):
        return {}

    monkeypatch.setattr(cycle_graph, "_run_phase", fake_phase)
    monkeypatch.setattr(cycle_graph, "_invoke_agent", lambda graph, state: None)

    async def noop(*_a, **_kw):
        return None

    rt = SimpleNamespace(base_state={}, enter=noop, progress=noop, phase_checkpoint=noop,
                         config=SimpleNamespace(token_budget={}))

    out = await cycle_graph.qa({"prs": [PR_325]}, SimpleNamespace(context=rt))

    assert out["demo_report"] is None


# ── What a cycle merged that an earlier one opened ─────────────────────
# Cycle 4eaa5b767051 (2026-09-29) resumed story #481: the Dev answered the
# review of PR #486 (opened the day before), the TechLead merged it — and
# the demo showed the dashboard and the homepage, every behaviour gate "not
# run", one story ("#484 — already on main"): QA and the stories read only
# the PRs the cycle *opened*. The delivered PRs are those it opened and
# those it merged; an already-satisfied task says its title.

PR_486 = {"number": 486, "title": "[#483] Implement GET /api/v1/stats/prices endpoint",
          "url": "https://github.com/jrechet/concert-tour-app/pull/486", "head": "feat/issue-483-x",
          "head_sha": "abc", "body": "Closes #483"}


def test_an_already_satisfied_task_says_its_title():
    stories = cycle_graph._stories_of({"already_satisfied": [484]},
                                      titles={484: "Write tests for GET /api/v1/stats/prices"})

    assert stories == [{"task": 484, "title": "Write tests for GET /api/v1/stats/prices", "pr": None,
                        "url": "", "status": "already on main"}]


async def test_qa_sees_what_the_cycle_merged_not_only_what_it_opened(monkeypatch):
    seen: dict = {}

    async def fake_phase(rt, key, role, coro):
        return {"demo_report": {"quality_gates": {}, "user_stories": []}, "tokens_used": 1, "cost_usd": 0.0}

    def invoke(graph, state):
        seen.update(state)
        return None

    monkeypatch.setattr(cycle_graph, "_run_phase", fake_phase)
    monkeypatch.setattr(cycle_graph, "_invoke_agent", invoke)
    monkeypatch.setattr(cycle_graph._cycle(), "build_qa_graph", lambda: object())

    async def noop(*_a, **_kw):
        return None

    github = SimpleNamespace(
        get_pr=lambda n: _async({486: PR_486}.get(n)),
        get_issue=lambda n: _async({"number": n, "title": "Write tests for GET /api/v1/stats/prices"}),
    )
    rt = SimpleNamespace(base_state={"github": github}, enter=noop, progress=noop, phase_checkpoint=noop,
                         config=SimpleNamespace(token_budget={}))

    out = await cycle_graph.qa({"prs": [], "merged_prs": [486], "already_satisfied": [484]},
                               SimpleNamespace(context=rt))

    assert [p["number"] for p in seen["prs"]] == [486]
    stories = out["demo_report"]["user_stories"]
    assert [(s["pr"], s["status"]) for s in stories] == [(486, "merged"), (None, "already on main")]
    assert stories[0]["task"] == 483
    assert stories[1]["title"] == "Write tests for GET /api/v1/stats/prices"


async def _async(value):
    return value
