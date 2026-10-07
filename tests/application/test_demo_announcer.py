"""The demo is announced on the issue that asked for it (#79: "show the demo
to the user").

A feature asked for on GitHub — the `swarm:go` label, or an issue the
owner pressed Play on and walked away from — got its PRs, its merges and
its demo, and the issue said nothing: the demo was on a page nobody was
told about. When the demo is ready the swarm comments on the pinned issue
with the player's link and what was built, once per cycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from theswarm.application.services.demo_announcer import announce_demo, demo_comment
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.domain.reporting.events import DemoReady
from theswarm.domain.reporting.value_objects import QualityGate, QualityStatus

EXTERNAL = "https://bots.jrec.fr/swarm"


def _report() -> DemoReport:
    return DemoReport(
        id="rpt-7f4f", cycle_id=CycleId("7f4f2188cd90"), project_id="jrechet/concert-tour-app",
        created_at=datetime(2026, 9, 28, 18, 25, tzinfo=timezone.utc),
        summary=ReportSummary(stories_completed=3, stories_total=3, prs_merged=3,
                              tests_passing=386, tests_total=386, coverage_percent=96.1),
        quality_gates=(QualityGate(name="feature_pages", status=QualityStatus.PASS,
                                   detail="1 of 1 feature page(s) answered 2xx"),
                       QualityGate(name="e2e_tests", status=QualityStatus.PASS, detail="29 passed")),
    )


def _event(issue: int | None = 404) -> DemoReady:
    return DemoReady(cycle_id=CycleId("7f4f2188cd90"), project_id="jrechet/concert-tour-app",
                     report_id="rpt-7f4f", play_url="/swarm/demos/rpt-7f4f", issue_number=issue)


def _github(comments=()):
    client = AsyncMock()
    client.get_issue_comments = AsyncMock(return_value=list(comments))
    client.add_comment = AsyncMock()
    return client


def test_the_comment_links_the_player_and_says_what_was_built():
    body = demo_comment(_report(), f"{EXTERNAL}/demos/rpt-7f4f")

    assert "The demo is ready" in body
    assert "(https://bots.jrec.fr/swarm/demos/rpt-7f4f)" in body
    assert "3 PRs merged" in body and "3/3 stories" in body
    assert "386/386 tests" in body and "96.1% coverage" in body
    assert "feature pages: pass" in body
    assert "<!-- swarm:demo 7f4f2188cd90 -->" in body


async def test_the_issue_gets_the_comment(monkeypatch):
    github = _github()
    reports = AsyncMock()
    reports.get = AsyncMock(return_value=_report())

    posted = await announce_demo(_event(), external_url=EXTERNAL, report_repo=reports,
                                 github_for=lambda repo: github)

    assert posted is True
    github.add_comment.assert_awaited_once()
    number, body = github.add_comment.await_args.args
    assert number == 404 and "/demos/rpt-7f4f" in body


async def test_a_cycle_is_announced_once():
    """A resumed cycle, a re-sent event: the marker is already there."""
    github = _github([{"body": "🎬 … <!-- swarm:demo 7f4f2188cd90 -->"}])
    reports = AsyncMock()
    reports.get = AsyncMock(return_value=_report())

    assert await announce_demo(_event(), external_url=EXTERNAL, report_repo=reports,
                               github_for=lambda repo: github) is False
    github.add_comment.assert_not_awaited()


async def test_an_untargeted_cycle_has_no_issue_to_answer():
    github = _github()

    assert await announce_demo(_event(issue=None), external_url=EXTERNAL, report_repo=AsyncMock(),
                               github_for=lambda repo: github) is False
    github.add_comment.assert_not_awaited()


async def test_without_a_public_url_there_is_no_link_to_give():
    """A laptop server: a relative link is useless on GitHub."""
    github = _github()

    assert await announce_demo(_event(), external_url="", report_repo=AsyncMock(),
                               github_for=lambda repo: github) is False
    github.add_comment.assert_not_awaited()


async def test_github_failing_is_logged_not_raised(caplog):
    github = _github()
    github.add_comment = AsyncMock(side_effect=RuntimeError("502"))
    reports = AsyncMock()
    reports.get = AsyncMock(return_value=_report())

    assert await announce_demo(_event(), external_url=EXTERNAL, report_repo=reports,
                               github_for=lambda repo: github) is False
    assert "announcing the demo" in caplog.text


def test_the_event_carries_the_issue():
    assert _event(404).issue_number == 404


async def test_the_cycle_s_demo_event_names_its_issue():
    from theswarm import api

    published = []

    class Bus:
        async def publish(self, event):
            published.append(event)

    await api._emit_demo_ready(event_bus=Bus(), report_repo=None, base_path="/swarm",
                               cycle_id="7f4f2188cd90", repo="jrechet/concert-tour-app",
                               result={"prs": [], "cost_usd": 1.06}, issue_number=404)

    (event,) = published
    assert event.issue_number == 404 and event.play_url.startswith("/swarm/demos/")
