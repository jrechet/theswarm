"""The demo walks the feature's pages, and the report has a story per PR.

The screenshot pass and the video walked only the declared pages; the
per-story before/after machinery (F2/F3) waited for preview URLs nothing
ever set, and the stored report never carried a story. Now the pages read
off the cycle's PRs join both walks, the walk's own screenshot of a
feature page is that PR's story capture, and the report lists the stories
with them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from theswarm.agents import qa
from theswarm.application.services.report_generator import ReportGenerator
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.reporting.value_objects import ArtifactType

PAGES = [("/api/v1/tours/1/summary", "feature_pr_362_tours_1_summary")]
PRS = [{"number": 362, "head_sha": "abc", "title": "[#359] Summary", "url": "https://x/362"}]


def test_feature_pages_join_the_walk_after_the_declared_ones(tmp_path):
    pages = qa._pages_to_capture(str(tmp_path), extra=PAGES + [("", "homepage_again")])

    assert pages[0] == ("", "homepage")
    assert pages[-1] == PAGES[0]
    assert [p for p, _ in pages].count("") == 1


async def test_both_lanes_walk_the_feature_pages_and_the_result_keeps_them(monkeypatch):
    seen: dict[str, list] = {}

    async def shots(state):
        seen["shots"] = state.get("feature_pages")
        return {"demo_artifacts": [], "tokens_used": 0}

    async def video(state):
        seen["video"] = state.get("feature_pages")
        return {"video_artifacts": [], "tokens_used": 0}

    async def nothing(state):
        return {"tokens_used": 0}

    monkeypatch.setattr(qa, "capture_demo_screenshots", shots)
    monkeypatch.setattr(qa, "record_demo_video", video)
    monkeypatch.setattr(qa, "capture_before_after_per_story", nothing)
    monkeypatch.setattr(qa, "record_story_video", nothing)
    monkeypatch.setattr(qa, "_capture_concurrency", lambda: 1)
    with patch("theswarm.agents.qa_feature_pages.feature_pages", AsyncMock(return_value=PAGES)) as pages:
        out = await qa.run_captures({"workspace": "/ws", "github": object(), "prs": PRS})

    pages.assert_awaited_once()
    assert seen == {"shots": PAGES, "video": PAGES}
    assert out["feature_pages"] == PAGES


async def test_no_prs_means_no_lookup_and_the_old_walk(monkeypatch):
    async def shots(state):
        return {"demo_artifacts": [], "tokens_used": 0, "seen": state.get("feature_pages")}

    async def nothing(state):
        return {"tokens_used": 0}

    monkeypatch.setattr(qa, "capture_demo_screenshots", shots)
    monkeypatch.setattr(qa, "record_demo_video", nothing)
    monkeypatch.setattr(qa, "capture_before_after_per_story", nothing)
    monkeypatch.setattr(qa, "record_story_video", nothing)
    monkeypatch.setattr(qa, "_capture_concurrency", lambda: 1)
    with patch("theswarm.agents.qa_feature_pages.feature_pages", AsyncMock()) as pages:
        out = await qa.run_captures({"workspace": "/ws", "github": object()})

    pages.assert_not_awaited()
    assert out.get("feature_pages", []) == [] and out["seen"] == []


async def test_the_report_turns_feature_screenshots_into_story_captures():
    state = {
        "workspace": "/ws",
        "feature_pages": PAGES,
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "tests_passed": True,
        "e2e_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "e2e_passed": True,
    }
    saved = [
        {"type": "screenshot", "label": "homepage", "path": "d/screenshot/homepage.png", "size_bytes": 1},
        {"type": "screenshot", "label": "feature_pr_362_tours_1_summary", "path": "d/screenshot/feature.png", "size_bytes": 2},
    ]

    with patch.object(qa, "_saved_artifacts", AsyncMock(return_value=saved)):
        out = await qa.generate_demo_report(state)

    report = out["demo_report"]
    assert report["feature_pages"] == PAGES
    assert report["story_screenshots"] == {362: {"before": [], "after": [saved[1]]}}


def _cycle() -> Cycle:
    return Cycle(id=CycleId("d7a0e052f1ad"), project_id="jrechet/concert-tour-app",
                 status=CycleStatus.COMPLETED, triggered_by="web",
                 started_at=datetime(2026, 9, 25, 14, 27, tzinfo=timezone.utc))


DEMO = {
    "user_stories": [
        {"task": 359, "title": "[#359] Summary", "pr": 362, "url": "https://x/362", "status": "merged"},
        {"task": 360, "title": "", "pr": None, "url": "", "status": "already on main"},
    ],
    "story_screenshots": {362: {"before": [], "after": [
        {"type": "screenshot", "label": "feature_pr_362_tours_1_summary", "path": "d/screenshot/feature.png", "size_bytes": 2},
    ]}},
    "story_videos": {362: {"type": "video", "label": "pr_362_walkthrough", "path": "d/video/pr_362.webm", "size_bytes": 3}},
}


def test_the_stored_report_lists_a_story_per_delivered_task():
    report = ReportGenerator().generate(_cycle(), stories=ReportGenerator.stories_of(DEMO))

    assert [s.ticket_id for s in report.stories] == ["359", "360"]
    summary, already = report.stories
    assert summary.pr_number == 362 and summary.pr_url == "https://x/362" and summary.status == "completed"
    assert [a.path for a in summary.screenshots_after] == ["d/screenshot/feature.png"]
    assert summary.screenshots_after[0].type == ArtifactType.SCREENSHOT
    assert summary.video is not None and summary.video.path == "d/video/pr_362.webm"
    assert already.status == "completed" and already.pr_number is None and already.screenshots_after == ()


def test_a_report_without_stories_is_the_old_report():
    assert ReportGenerator.stories_of({}) == ()
    assert ReportGenerator().generate(_cycle()).stories == ()


async def test_the_cycle_s_report_carries_the_stories():
    from theswarm import api

    saved = []

    class Repo:
        async def save(self, report):
            saved.append(report)

    class Bus:
        async def publish(self, event):
            pass

    await api._emit_demo_ready(event_bus=Bus(), report_repo=Repo(), base_path="", cycle_id="d7a0e052f1ad",
                               repo="jrechet/concert-tour-app", result={"prs": [], "demo_report": DEMO})

    (report,) = saved
    assert [s.pr_number for s in report.stories] == [362, None]


async def test_the_qa_node_hands_the_cycle_s_prs_to_qa(monkeypatch):
    from types import SimpleNamespace

    from theswarm import cycle_graph

    given: dict = {}

    async def fake_phase(rt, key, role, coro):
        return {}

    monkeypatch.setattr(cycle_graph, "_run_phase", fake_phase)
    monkeypatch.setattr(cycle_graph, "_invoke_agent", lambda graph, state: given.update(state))

    async def noop(*_a, **_kw):
        return None

    rt = SimpleNamespace(base_state={}, enter=noop, progress=noop, phase_checkpoint=noop,
                         config=SimpleNamespace(token_budget={}))
    await cycle_graph.qa({"prs": PRS, "merged_prs": [362]}, SimpleNamespace(context=rt))

    assert given["prs"] == PRS and given["merged_prs"] == [362]


def test_the_state_declares_the_new_keys():
    from theswarm.config import AgentState

    assert {"prs", "feature_pages"} <= set(AgentState.__annotations__)


def test_a_story_already_on_main_has_a_title_on_the_player():
    """rpt-04a4c643 (2026-09-28): the slide for #383, found already built,
    had an empty heading — the cycle knows the task's number, not its title."""
    (story,) = ReportGenerator.stories_of({"user_stories": [
        {"task": 383, "title": "", "pr": None, "url": "", "status": "already on main"},
    ]})

    assert story.title == "#383 — already on main"
    assert story.status == "completed"


def test_a_story_with_a_title_keeps_it():
    (story,) = ReportGenerator.stories_of({"user_stories": [
        {"task": 382, "title": "[#382] Add status filtering", "pr": 385, "url": "", "status": "merged"},
    ]})

    assert story.title == "[#382] Add status filtering"
