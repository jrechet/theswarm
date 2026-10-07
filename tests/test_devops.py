"""DevOps D1 — the stack declared, the pipeline read, nothing touched
(docs/plans/2026-10-v3-one-product.md, "The DevOps persona").

The checks are pure and read what jrec.fr and GitHub really answer: the
CI slot's owner file as acquire.sh writes it (runner, repo, ISO time,
container, kind), the runners, the workflow runs, `df -P`. `gather` never
raises: a reader that fails is an `unknown` finding with the reason.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from theswarm.agents import devops as d
from theswarm.application.services import ops_watch as w

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
OWNER = "runner-areza-vmKpHEsQ8AY7R\njrechet/areza\n2026-10-07T13:48:25Z\nccf7464e6af6\ncontainer\n"
STALE_OWNER = "runner-areza-vmKpHEsQ8AY7R\njrechet/areza\n2026-10-05T10:33:00Z\nabc\ncontainer\n"
SLOT = "/srv/gh-runner-work/ci-slots/slot1/owner"


class TestTheStack:
    def test_the_repository_s_stack_is_declared(self):
        stack = d.load_stack(Path(__file__).resolve().parents[1] / "theswarm.yaml")
        assert stack["hosts"][0]["name"] == "jrec.fr" and stack["hosts"][0]["ci_slot_dir"].endswith("ci-slots")
        assert d.self_repo(stack) == "jrechet/theswarm"
        assert d.stack_summary(stack) == "jrec.fr · github-actions · forgejo · ghcr.io · docker-swarm"

    def test_no_file_or_no_section_is_an_empty_stack(self, tmp_path):
        assert d.load_stack(tmp_path / "nope.yaml") == {}
        (tmp_path / "t.yaml").write_text("demo:\n  command: x\n")
        assert d.load_stack(tmp_path / "t.yaml") == {}
        assert d.stack_summary({}) == ""


class TestTheCiSlot:
    def test_the_owner_file_as_acquire_sh_writes_it(self):
        owner = d.parse_owner(OWNER)
        assert owner["runner"] == "runner-areza-vmKpHEsQ8AY7R" and owner["repo"] == "jrechet/areza"
        assert owner["since"] == datetime(2026, 10, 7, 13, 48, 25, tzinfo=timezone.utc)
        assert owner["container"] == "ccf7464e6af6" and owner["kind"] == "container"
        assert d.parse_owner("")["since"] is None and d.parse_owner("x\ny\nnot a date")["since"] is None

    def test_free_held_and_stale(self):
        assert d.slot_finding([], NOW, host="jrec.fr").status == "ok"
        held = d.slot_finding([(SLOT, OWNER)], NOW, host="jrec.fr")
        assert held.status == "ok" and "slot1 held by runner-areza-vmKpHEsQ8AY7R (jrechet/areza) for 11 min" in held.detail
        stale = d.slot_finding([(SLOT, STALE_OWNER)], NOW)  # the 2026-10-05 incident: 2.5 h of queued jobs
        assert stale.status == "bad" and "stale" in stale.detail and "180 min rule" in stale.detail

    def test_the_host_script_s_output_is_parsed(self):
        text = f"SLOT {SLOT}\n{OWNER}ENDSLOT\nDISK\nFilesystem 1024-blocks Used Available Capacity Mounted on\n/dev/md3 3800000000 380000000 3300000000 11% /\n/dev/md3 3800000000 380000000 3300000000 11% /\n"
        text += "LOAD 18.42 16.10 12.03 8\n"
        read = d.parse_host_output(text)
        assert read["slots"] == [(SLOT, OWNER.rstrip("\n"))]
        assert read["load"] == {"one": 18.42, "five": 16.10, "fifteen": 12.03, "cores": 8}
        assert read["disks"] == [{"path": "/", "percent": 11, "free": "3.1T"}]
        assert d.parse_host_output("") == {"slots": [], "disks": [], "load": None}

    def test_the_ssh_command_names_the_host_and_port(self):
        cmd = d.ssh_command({"ssh": "debian@jrec.fr", "port": 5422})
        assert cmd[0] == "ssh" and "-p" in cmd and "5422" in cmd and cmd[-1] == "debian@jrec.fr" and "BatchMode=yes" in cmd


class TestTheDeploy:
    def test_landed_pending_failed_and_unknown(self):
        run_ok = {"status": "completed", "conclusion": "success", "updated_at": "2026-10-07T12:23:00Z", "html_url": "u"}
        assert d.deploy_finding("c345216abc", "c345216abc", run_ok).status == "ok"
        running = {"status": "in_progress", "conclusion": None, "updated_at": "2026-10-07T13:40:00Z"}
        pending = d.deploy_finding("753dbf9abc", "c345216abc", running)
        assert pending.status == "warn" and "deploy run in_progress" in pending.detail
        failed = d.deploy_finding("753dbf9abc", "c345216abc", {"status": "completed", "conclusion": "failure"})
        assert failed.status == "bad"
        assert d.deploy_finding("753dbf9abc", "c345216abc", None).status == "warn"
        assert d.deploy_finding("", "x", None).status == "unknown"
        assert "SWARM_BUILD_SHA" in d.deploy_finding("753dbf9abc", "", None).detail

    def test_the_deploy_run_is_found_by_its_workflow_path(self):
        runs = [{"path": ".github/workflows/ci.yml", "id": 1, "head_branch": "feat/x"},
                {"path": ".github/workflows/ci.yml", "id": 2, "head_branch": "main"},
                {"path": ".github/workflows/cd.yml", "id": 3, "head_branch": "main"}]
        assert d.deploy_run_of(runs)["id"] == 2  # ci.yml on main: the deploy is one of its jobs
        assert d.deploy_run_of(runs, "cd.yml")["id"] == 3 and d.deploy_run_of(runs[:1]) is None


class TestRunnersAndRuns:
    def test_runners(self):
        online = [{"name": "runner-theswarm", "status": "online", "busy": True}]
        assert d.runners_finding(online).status == "ok" and "1 online, 1 busy" in d.runners_finding(online).detail
        off = d.runners_finding(online + [{"name": "runner-two", "status": "offline", "busy": False}])
        assert off.status == "bad" and "runner-two" in off.detail
        assert d.runners_finding([]).status == "bad"

    def test_failed_runs_in_the_last_day(self):
        old = {"name": "CI", "head_branch": "feat/x", "conclusion": "failure", "updated_at": "2026-10-05T16:04:00Z"}
        assert d.failed_runs_finding([old], NOW).status == "ok"
        recent = {"name": "CI", "head_branch": "feat/y", "conclusion": "failure", "updated_at": "2026-10-07T10:00:00Z", "html_url": "u"}
        f = d.failed_runs_finding([recent, old], NOW)
        assert f.status == "warn" and "CI on feat/y (failure)" in f.detail and f.url == "u"
        on_main = {"name": "CD", "head_branch": "main", "conclusion": "failure", "updated_at": "2026-10-07T13:00:00Z"}
        assert d.failed_runs_finding([on_main], NOW).status == "bad"
        superseded = {"name": "CI", "head_branch": "feat/z", "conclusion": "cancelled", "updated_at": "2026-10-07T13:30:00Z"}
        assert d.failed_runs_finding([superseded], NOW).status == "ok"  # a newer push cancelled it: routine
        # On main too, when a newer run of the same workflow was created before this one was cancelled
        # (the concurrency group keeps one pending run): 3c6be90 and 6428250 on 2026-10-07.
        older = {"name": "CI", "path": ".github/workflows/ci.yml", "head_branch": "main", "conclusion": "cancelled",
                 "created_at": "2026-10-07T13:48:00Z", "updated_at": "2026-10-07T13:57:00Z"}
        newer = {"name": "CI", "path": ".github/workflows/ci.yml", "head_branch": "main", "conclusion": None, "status": "in_progress",
                 "created_at": "2026-10-07T13:57:00Z", "updated_at": "2026-10-07T13:58:00Z"}
        assert d.failed_runs_finding([newer, older], NOW).status == "ok"
        capped = {"name": "CI", "path": ".github/workflows/ci.yml", "head_branch": "main", "conclusion": "cancelled",
                 "created_at": "2026-10-07T13:00:00Z", "updated_at": "2026-10-07T13:31:00Z"}
        f = d.failed_runs_finding([newer, capped], NOW)  # the newer run came after the cap: a tests job that ran out
        assert f.status == "warn" and "CI on main (cancelled)" in f.detail
        capped = {**superseded, "head_branch": "main"}
        assert d.failed_runs_finding([capped], NOW).status == "warn"  # on main, never routine


class TestTheRest:
    def test_disk(self):
        assert d.disk_finding("jrec.fr", [{"path": "/", "percent": 11, "free": "3.1T"}]).status == "ok"
        assert d.disk_finding("jrec.fr", [{"path": "/", "percent": 90}]).status == "warn"
        assert d.disk_finding("jrec.fr", [{"path": "/", "percent": 97}]).status == "bad"
        assert d.disk_finding("jrec.fr", []).status == "unknown"
        assert d.local_disk([str(Path.home())])[0]["percent"] >= 0
        not_yet = str(Path.home() / "no-such-workspaces-dir" / "deeper")  # a workspace directory not made yet
        assert d.local_disk([not_yet])[0]["path"] == str(Path.home()) and d._existing("/") == "/"

    def test_load(self):
        assert d.load_finding("jrec.fr", {"one": 2.0, "five": 1.5, "cores": 8}).status == "ok"
        warm = d.load_finding("jrec.fr", {"one": 9.0, "five": 8.0, "cores": 8})
        assert warm.status == "warn" and "1.1 per core" in warm.detail and "may not make it in time" in warm.detail
        assert d.load_finding("jrec.fr", {"one": 18.4, "cores": 8}).status == "bad"  # 2026-10-07: the box under another repo's CI
        assert d.load_finding("jrec.fr", None).status == "unknown" and d.load_finding("x", {"one": 1, "cores": 0}).status == "unknown"
        here = d.local_load()
        assert here is None or here["cores"] >= 1

    def test_claude(self):
        assert d.claude_finding({"status": "ok"}).status == "ok"
        assert d.claude_finding({"status": "quota_wall", "detail": "until 16:00 UTC"}).status == "bad"
        assert d.claude_finding({"status": "auth_expired"}).status == "bad"
        assert d.claude_finding(None).status == "unknown"

    def test_the_harness(self):
        # The record as /api/evals/runs carries it: `timestamp`, outcome `built`.
        today = {"feature": "venue-create", "outcome": "built", "behaviour": "verified", "cost_usd": 2.969, "timestamp": "2026-10-07T07:40:00Z"}
        f = d.harness_finding([today], NOW.date())
        assert f.status == "ok" and "venue-create" in f.detail and "$2.97" in f.detail
        broken = {**today, "behaviour": "broken"}
        assert d.harness_finding([broken], NOW.date()).status == "bad"
        yesterday = {**today, "feature": "venue-detail", "timestamp": "2026-10-06T07:40:00Z"}
        warn = d.harness_finding([yesterday], NOW.date())
        assert warn.status == "warn" and "6 Oct 07:40 UTC" in warn.detail and "venue-detail" in warn.detail
        # The store answers oldest first: today's run still wins (prod read the oldest, 2026-10-07).
        assert d.harness_finding([yesterday, today], NOW.date()).status == "ok"
        assert d.harness_finding([{**yesterday, "recorded_at": "2026-10-06T07:40:00Z", "timestamp": None}], NOW.date()).status == "warn"
        assert d.harness_finding([{**today, "outcome": "interrupted"}], NOW.date()).status == "warn"
        assert d.harness_finding([], NOW.date()).status == "unknown"

    def test_build_sha_prefers_the_deploy_s_tag(self, monkeypatch):
        monkeypatch.setenv("SWARM_BUILD_SHA", "abc1234")
        assert d.build_sha() == "abc1234"


STACK = {
    "hosts": [{"name": "jrec.fr", "ssh": "debian@jrec.fr", "port": 5422, "ci_slot_dir": "/srv/gh-runner-work/ci-slots",
               "ci_slot_stale_minutes": 180, "disk_paths": ["/"]}],
    "ci": [{"provider": "github-actions", "repo": "jrechet/theswarm", "deploy_workflow": "ci.yml"}],
    "registry": "ghcr.io/jrechet/theswarm", "deploy": {"method": "docker-swarm"}, "harness": {"repo": "jrechet/concert-tour-app"},
}


HERE = lambda: [{"path": "/", "percent": 40, "free": "200G"}]  # noqa: E731 — this process's disk, injected


async def _github(repo):
    assert repo == "jrechet/theswarm"
    return {"main_sha": "753dbf9000", "runners": [{"name": "r", "status": "online", "busy": False}],
            "runs": [{"path": ".github/workflows/ci.yml", "status": "completed", "conclusion": "success",
                      "updated_at": "2026-10-07T13:50:00Z", "name": "CI", "head_branch": "main"}]}


async def _host(host):
    return {"slots": [(SLOT, STALE_OWNER)], "disks": [{"path": "/", "percent": 11, "free": "3.1T"}]}


QUIET = lambda: {"one": 0.4, "five": 0.4, "fifteen": 0.4, "cores": 8}  # noqa: E731 — the suite's own box must not colour a report


class TestGather:
    async def test_every_check_with_fakes(self):
        report = await d.gather(STACK, github=_github, host_reader=_host, claude=lambda: {"status": "ok"},
                                harness=lambda repo: _harness(repo), build=lambda: "753dbf9000", here=HERE, load=QUIET, now=NOW)
        keys = [f.key for f in report.findings]
        assert keys == ["deploy", "runners", "failed_runs", "ci_slot", "disk_jrec.fr", "load_jrec.fr", "load_here", "disk_here", "claude", "harness"]
        by = {f.key: f for f in report.findings}
        assert by["deploy"].status == "ok" and by["ci_slot"].status == "bad" and by["harness"].status == "ok"
        assert report.status == "bad" and report.counts["bad"] == 1
        assert report.stack == "jrec.fr · github-actions · ghcr.io · docker-swarm"
        assert report.as_dict()["findings"][3]["key"] == "ci_slot" and by["load_jrec.fr"].status == "unknown"

    async def test_a_reader_that_fails_is_a_finding_not_an_exception(self):
        async def broken(_):
            raise RuntimeError("ssh: connect to host jrec.fr port 5422: Operation timed out")

        async def no_github(_):
            raise ValueError("GITHUB_TOKEN is not set")

        report = await d.gather(STACK, github=no_github, host_reader=broken, claude=lambda: {"status": "ok"}, here=HERE, load=QUIET, now=NOW)
        by = {f.key: f for f in report.findings}
        assert by["deploy"].status == "unknown" and "GITHUB_TOKEN" in by["deploy"].detail
        assert by["ci_slot"].status == "unknown" and "not reachable from here" in by["ci_slot"].detail
        assert by["claude"].status == "ok" and report.status == "ok"

    async def test_an_empty_stack_still_reads_this_process(self):
        async def no_github(_):
            raise ValueError("no repository declared in stack.ci")

        report = await d.gather({}, github=no_github, claude=lambda: {"status": "ok"}, here=HERE, now=NOW)
        assert [f.key for f in report.findings] == ["deploy", "runners", "failed_runs", "load_here", "disk_here", "claude"]

    def test_the_report_in_words(self):
        report = d.OpsReport((d.Finding("ci_slot", "CI slot", "bad", "stale: slot1 held for 150 min", "https://x"),
                              d.Finding("claude", "Claude", "ok", "fine")), read_at=NOW, stack="jrec.fr · github-actions")
        text = d.format_report(report)
        assert text.startswith("### DevOps — daily report") and "🔴 **something is wrong**" in text
        assert "- 🔴 **CI slot** — stale: slot1 held for 150 min [↗](https://x)" in text and "- ✅ **Claude** — fine" in text


async def _harness(repo):
    assert repo == "jrechet/concert-tour-app"
    return [{"feature": "venues-list", "outcome": "passed", "behaviour": "verified", "recorded_at": "2026-10-07T07:40:00Z"}]


class _Chat:
    def __init__(self):
        self.posts = []

    async def post_message(self, channel, text, *, root_id=""):
        self.posts.append((channel, text))
        return "post-1"


class TestTheWatch:
    def test_due_once_a_day_after_the_hour(self):
        assert not w.due_daily(datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc), None)
        assert w.due_daily(datetime(2026, 10, 7, 7, 30, tzinfo=timezone.utc), None)
        assert w.due_daily(datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc), datetime(2026, 10, 6).date())
        assert not w.due_daily(datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc), datetime(2026, 10, 7).date())

    async def test_refresh_keeps_the_last_report_when_a_read_fails(self):
        calls = {"n": 0}

        async def gather():
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("GitHub down")
            return d.OpsReport((d.Finding("claude", "Claude", "ok", "fine"),), read_at=NOW)

        watch = w.OpsWatch(gather, clock=lambda: NOW)
        assert watch.last() is None
        first = await watch.latest()
        assert first.status == "ok" and calls["n"] == 1
        second = await watch.refresh()
        assert second is first and watch.error == "GitHub down"
        assert (await watch.latest()) is first and calls["n"] == 2

    async def test_a_first_failure_is_a_report_that_says_so(self):
        async def gather():
            raise RuntimeError("no stack")

        watch = w.OpsWatch(gather, clock=lambda: NOW)
        report = await watch.refresh()
        assert report.status == "unknown" and "no stack" in report.findings[0].detail

    async def test_the_daily_post_once_after_the_hour(self):
        async def gather():
            return d.OpsReport((d.Finding("claude", "Claude", "ok", "fine"),), read_at=NOW, stack="jrec.fr")

        chat = _Chat()
        clock = {"now": datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc)}
        watch = w.OpsWatch(gather, chat=chat, channel="swarm-bots-logs", clock=lambda: clock["now"])
        assert not await watch.post_daily()  # before 07:30
        clock["now"] = datetime(2026, 10, 7, 7, 45, tzinfo=timezone.utc)
        assert await watch.post_daily() and chat.posts[0][0] == "swarm-bots-logs" and "DevOps — daily report" in chat.posts[0][1]
        assert not await watch.post_daily() and len(chat.posts) == 1  # not twice the same day
        clock["now"] = datetime(2026, 10, 8, 8, 0, tzinfo=timezone.utc)
        assert await watch.post_daily() and len(chat.posts) == 2

    async def test_no_chat_means_no_post(self):
        async def gather():
            return d.OpsReport((), read_at=NOW)

        watch = w.OpsWatch(gather, clock=lambda: datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc))
        assert not await watch.post_daily()
