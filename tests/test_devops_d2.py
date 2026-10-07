"""DevOps D2 — preflight and deploy watch (docs/plans/2026-10-v3-one-product.md).

Go or no-go with the reason before the API wrapper and the harness start a
cycle; every merge to main watched to the running box and alerted once
when it fails or does not land; a red CI triaged — the pipeline's red is
not the Dev's fault, the PR waits.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from theswarm import api as api_module
from theswarm.agents import ci_gate
from theswarm.agents import devops as d
from theswarm.application.services import ops_watch as w

NOW = datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)


def _report(*findings, when=NOW) -> d.OpsReport:
    return d.OpsReport(tuple(findings), read_at=when, stack="jrec.fr · github-actions")


class TestThePreflight:
    def test_a_bad_claude_disk_runner_or_slot_is_a_no_go(self):
        fine = _report(d.Finding("claude", "Claude", "ok", "fine"), d.Finding("load_here", "Load (here)", "warn", "high"))
        assert d.preflight_of(fine).go and d.preflight_of(fine).word == "go"
        for key, label in (("claude", "Claude"), ("disk_here", "Disk (here)"), ("runners", "Runners"), ("ci_slot", "CI slot")):
            answer = d.preflight_of(_report(d.Finding(key, label, "bad", "broken")))
            assert not answer.go and answer.reasons == (f"{label}: broken",) and answer.word.startswith("no-go")

    def test_a_warning_or_an_unknown_never_stops_a_cycle(self):
        answer = d.preflight_of(_report(d.Finding("claude", "Claude", "unknown", "not read"), d.Finding("ci_slot", "CI slot", "warn", "held")))
        assert answer.go
        # A bad finding outside the no-go set (the deploy, a host's disk) does not stop a cycle either.
        assert d.preflight_of(_report(d.Finding("deploy", "Last deploy", "bad", "failed"))).go
        assert d.preflight_of(_report(d.Finding("workflow_runs", "Workflow runs", "bad", "failed"))).go

    def test_the_answer_as_json(self):
        answer = d.preflight_of(_report(d.Finding("disk_here", "Disk (here)", "bad", "96% used")))
        body = answer.as_dict()
        assert body["go"] is False and body["reasons"] == ["Disk (here): 96% used"] and body["findings"][0]["key"] == "disk_here"


class TestTheDeployWatch:
    def test_nothing_while_the_build_is_main_or_within_the_grace(self):
        assert d.deploy_watch_finding("abc1234", "abc1234", None, NOW - timedelta(hours=1), NOW) is None
        assert d.deploy_watch_finding("abc1234", "", None, NOW, NOW) is None
        assert d.deploy_watch_finding("abc1234", "def5678", {"status": "in_progress"}, NOW - timedelta(minutes=10), NOW) is None

    def test_a_failed_deploy_or_one_that_did_not_land(self):
        failed = d.deploy_watch_finding("abc1234", "def5678", {"status": "completed", "conclusion": "failure", "html_url": "u"}, NOW, NOW)
        assert failed.status == "bad" and "failed (failure)" in failed.detail and failed.url == "u"
        late = d.deploy_watch_finding("abc1234", "def5678", None, NOW - timedelta(minutes=50), NOW)
        assert late.status == "bad" and "50 min ago" in late.detail and "did not land" in late.detail


class _Chat:
    def __init__(self):
        self.posts = []

    async def post_message(self, channel, text, *, root_id=""):
        self.posts.append((channel, text))
        return "p"


def _deploy_finding(detail: str, url: str = "") -> d.Finding:
    return d.Finding("deploy", "Last deploy", "warn", detail, url)


class TestTheWatch:
    async def test_the_preflight_reads_fresh(self):
        reports = [_report(d.Finding("claude", "Claude", "bad", "quota wall")), _report(d.Finding("claude", "Claude", "ok", "fine"))]

        async def gather():
            return reports.pop(0)

        watch = w.OpsWatch(gather, clock=lambda: NOW)
        assert not (await watch.preflight()).go
        assert (await watch.preflight()).go

    async def test_the_deploy_alert_once_per_main_sha(self):
        clock = {"now": NOW}
        detail = {"text": "main is at abc1234, this build is def5678; last deploy run success at 7 Oct 15:00 UTC"}

        async def gather():
            return _report(_deploy_finding(detail["text"], "https://run"))

        chat = _Chat()
        watch = w.OpsWatch(gather, chat=chat, channel="swarm-bots-logs", clock=lambda: clock["now"])
        await watch.refresh()
        assert not any(f.key == "deploy_watch" for f in watch.last().findings)  # just moved: within the grace
        assert not await watch.alert_deploy()
        clock["now"] = NOW + timedelta(minutes=50)
        await watch.refresh()
        late = next(f for f in watch.last().findings if f.key == "deploy_watch")
        assert late.status == "bad" and "did not land" in late.detail
        assert await watch.alert_deploy() and "deploy watch" in chat.posts[0][1] and "did not land" in chat.posts[0][1]
        await watch.refresh()
        assert not await watch.alert_deploy() and len(chat.posts) == 1  # once per main sha
        detail["text"] = "main is at 9999999, this build is def5678; last deploy run failure at 7 Oct 16:02 UTC"
        await watch.refresh()
        failed = next(f for f in watch.last().findings if f.key == "deploy_watch")
        assert "failed (failure)" in failed.detail and await watch.alert_deploy() and len(chat.posts) == 2
        detail["text"] = "this build is main's head 9999999; last deploy run success at 7 Oct 16:30 UTC"
        await watch.refresh()
        assert not any(f.key == "deploy_watch" for f in watch.last().findings)


class TestTheTriage:
    def test_the_pipeline_s_red_is_not_the_code_s(self):
        red = ci_gate.CiVerdict("red", ({"name": "deploy / deploy", "state": "failure", "summary": "Set up runner: lost communication"},))
        assert ci_gate.triage(red) == "infra"
        never_started = ci_gate.CiVerdict("red", ({"name": "tests", "state": "startup_failure", "summary": ""},))
        assert ci_gate.triage(never_started) == "infra"
        code = ci_gate.CiVerdict("red", ({"name": "tests", "state": "failure", "summary": "3 failed"},))
        assert ci_gate.triage(code) == "code"
        mixed = ci_gate.CiVerdict("red", ({"name": "deploy / deploy", "state": "failure", "summary": "runner"}, {"name": "tests", "state": "failure", "summary": "3 failed"}))
        assert ci_gate.triage(mixed) == "code"  # one failing test job makes it the code's
        assert ci_gate.triage(ci_gate.CiVerdict("green")) == "code"

    async def test_the_techlead_leaves_an_infra_red_pr_waiting(self):
        from theswarm.agents import techlead

        github = AsyncMock()
        github.get_ci_checks = AsyncMock(return_value=[{"name": "deploy / deploy", "state": "failure", "summary": "Set up runner"}])
        with patch.object(techlead, "_send_back_to_dev", new=AsyncMock()) as back:
            state = await techlead._ci_gate_before_merge(github, 42, "feat/x", {"head_sha": "abc"}, wait_seconds=0)
        assert state == "infra" and back.await_count == 0
        github.get_ci_checks = AsyncMock(return_value=[{"name": "tests", "state": "failure", "summary": "3 failed"}])
        with patch.object(techlead, "_send_back_to_dev", new=AsyncMock()) as back:
            state = await techlead._ci_gate_before_merge(github, 42, "feat/x", {"head_sha": "abc"}, wait_seconds=0)
        assert state == "red" and back.await_count == 1


class TestTheApiHook:
    @pytest.fixture(autouse=True)
    def _no_hook(self):
        api_module.set_preflight(None)
        yield
        api_module.set_preflight(None)

    async def test_a_no_go_marks_the_record_failed_and_blocks(self):
        from theswarm.api import CycleRequest, get_cycle_tracker

        tracker = get_cycle_tracker()
        record = tracker.create(CycleRequest(repo="o/r", description="Play"))

        async def no_go():
            return d.Preflight(go=False, reasons=("Disk (here): 96% used",), report=_report())

        api_module.set_preflight(no_go)
        bus = AsyncMock()
        await api_module._run_api_cycle(record.id, "o/r", "Play", "", [], event_bus=bus, project_id="o/r")
        got = tracker.get(record.id)
        assert got.status.value == "failed" and got.error == "preflight: Disk (here): 96% used"
        assert bus.publish.await_count == 1 and bus.publish.await_args.args[0].reason.startswith("preflight:")

    async def test_nobody_answering_or_a_failing_reader_never_blocks(self):
        assert await api_module._ask_preflight() is None

        async def broken():
            raise RuntimeError("ssh timed out")

        api_module.set_preflight(broken)
        assert await api_module._ask_preflight() is None
