"""Two features on one project (A1 bis).

Two cycles ran side by side on concert-tour-app (2026-11-13): the cycle of
#841 merged a PR of #840's, both merged Renovate's #839, and the code audit
listed what else two cycles on one repository share — the review and the
merge read every open PR (C1), the gate compared pinned issues only (C2), an
approved PR merged without main merged in (C3), the PO's dated plan, report
and the memory were written over each other (C4), QA's captures had no
common bound and a cancelled phase left its demo server running (C5), and
the morning plan moved backlog stories to ready in every Play (C6).
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from theswarm import api, cycle, cycle_gate, main_writes
from theswarm.agents import ci_gate, po, qa, techlead
from theswarm.cycle_gate import CycleGate

APPROVED = {"state": "success", "description": "Approved: looks right"}


def _pr(number, task, *, head_sha="h1", branch=None, title=None):
    return {"number": number, "title": title if title is not None else f"[#{task}] something",
            "body": f"Closes #{task}" if task else "", "head": branch or f"feat/issue-{task}-x",
            "head_sha": head_sha, "base": "main"}


class _GitHub:
    def __init__(self, prs=(), *, issues=None, behind=None, heads=None, commits=None, statuses=None,
                 checks=None):
        self.prs = [dict(p) for p in prs]
        self.issues = dict(issues or {})
        self.behind = dict(behind or {})
        self.heads = dict(heads or {})  # PR number -> its head after "Update branch"
        self.commits = dict(commits or {})
        self.statuses = dict(statuses or {})
        self.checks = dict(checks or {})
        self.updated: list[int] = []
        self.merged: list[int] = []
        self.read_issues: list[int] = []

    async def get_open_prs(self):
        return [p for p in self.prs if p["number"] not in self.merged]

    async def get_issue(self, number):
        self.read_issues.append(number)
        issue = self.issues.get(number)
        if isinstance(issue, Exception):
            raise issue
        return issue

    async def get_pr(self, number):
        pr = next(p for p in self.prs if p["number"] == number)
        if number in self.updated and number in self.heads:
            return {**pr, "head_sha": self.heads[number]}
        return pr

    async def behind_by(self, head, base="main"):
        return self.behind.get(head, 0)

    async def update_pr_branch(self, number, expected_head_sha):
        self.updated.append(number)
        return True

    async def get_commit_brief(self, sha):
        return self.commits.get(sha, {"parents": ["x"], "committer": "jrechet", "message": "feat"})

    async def get_review_status(self, sha):
        return self.statuses.get(sha)

    async def create_commit_status(self, sha, state, description, *, context=""):
        self.statuses[sha] = {"state": state, "description": description}

    async def get_ci_checks(self, sha):
        return self.checks.get(sha, [{"name": "tests", "state": "success"}])

    async def merge_pr(self, number, merge_method="squash"):
        self.merged.append(number)

    async def delete_branch(self, name):
        pass

    async def get_issues(self, labels=None, state="open"):
        return []


# ── C2: a story and its sub-tasks are one feature at the gate ──────────


class TestTheGate:
    async def _running(self, gate, cycle_id, repo, issue, feature=None):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def run():
            async with gate.hold(cycle_id, repo, issue, feature):
                entered.set()
                await release.wait()

        task = asyncio.create_task(run())
        await asyncio.wait_for(entered.wait(), 1)
        return task, release

    async def test_a_sub_task_waits_while_its_story_is_built(self, monkeypatch):
        monkeypatch.setattr(cycle_gate, "repo_max_cycles", lambda repo: 2)
        monkeypatch.setattr(cycle_gate, "max_concurrent_cycles", lambda: 4)
        gate = CycleGate()
        story, release = await self._running(gate, "a", "o/r", 10)

        assert not gate.fits_now("o/r", 11, 10)  # #11 is a sub-task of #10
        assert gate.fits_now("o/r", 20)  # another feature runs beside it

        waiting = asyncio.create_task(self._running(gate, "b", "o/r", 11, 10))
        while not gate.why_waiting("b"):
            await asyncio.sleep(0.001)
        assert gate.why_waiting("b") == "feature" and gate.building_now("b") == 10
        release.set()
        _, second = await asyncio.wait_for(waiting, 1)
        second.set()
        await story

    async def test_a_story_waits_while_one_of_its_sub_tasks_is_built(self, monkeypatch):
        monkeypatch.setattr(cycle_gate, "repo_max_cycles", lambda repo: 2)
        monkeypatch.setattr(cycle_gate, "max_concurrent_cycles", lambda: 4)
        gate = CycleGate()
        _, release = await self._running(gate, "a", "o/r", 11, 10)
        assert not gate.fits_now("o/r", 10)
        release.set()

    async def test_the_story_is_read_once_and_a_failure_is_the_issue_itself(self):
        async def reader(repo, issue):
            return {11: 10, 12: None}.get(issue)

        api.set_feature_reader(reader)
        try:
            assert await api.feature_of("o/r", 11) == 10
            assert await api.feature_of("o/r", 12) == 12
            assert await api.feature_of("o/r", None) is None

            async def broken(repo, issue):
                raise RuntimeError("GitHub 502")

            api.set_feature_reader(broken)
            assert await api.feature_of("o/r", 11) == 11
        finally:
            api.set_feature_reader(None)

    async def test_without_a_reader_the_pinned_issues_are_compared(self):
        assert await api.feature_of("o/r", 11) == 11

    def test_the_waiting_words_name_the_story_being_built(self, monkeypatch):
        from theswarm.presentation.web import shell

        record = SimpleNamespace(id="b", repo="o/r", issue_number=11, waiting="",
                                 status=SimpleNamespace(value="queued"))
        monkeypatch.setattr(shell, "_gate_reason", lambda cid: "feature")
        monkeypatch.setattr(shell, "_feature_holder", lambda cid: 10)
        assert shell.waiting_words(record, live=[record]) == "starts once the cycle building #10 ends"


# ── C1: a pinned cycle reviews and merges its feature's PRs ───────────


class TestTheScope:
    async def test_a_pinned_cycle_keeps_to_its_feature_and_to_nobodys_prs(self):
        github = _GitHub(issues={
            11: {"number": 11, "body": "Parent: #10"},
            21: {"number": 21, "body": "Parent: #20"},
            30: {"number": 30, "body": "a story of its own"},
        })
        prs = [
            _pr(1, 11),  # a sub-task of the feature
            _pr(2, 10),  # the feature itself
            _pr(3, 21),  # another feature's sub-task
            _pr(4, 30),  # another feature
            _pr(5, None, branch="renovate/all-minor-patch", title="Update dependency x"),  # nobody's
            _pr(6, None, branch="feat/issue-11-second-try", title="Second try"),  # read off its branch
        ]

        scoped, others = await techlead.feature_scope(github, prs, 10)

        assert [p["number"] for p in scoped] == [1, 2, 5, 6]
        assert others == [(3, 20), (4, 30)]
        assert github.read_issues.count(11) == 1  # one read per task

    async def test_unpinned_reads_every_pr(self):
        prs = [_pr(1, 11), _pr(3, 21)]
        scoped, others = await techlead.feature_scope(_GitHub(), prs, None)
        assert scoped == prs and others == []

    async def test_a_task_that_cannot_be_read_is_reviewed_as_before(self):
        github = _GitHub(issues={21: RuntimeError("GitHub 502")})
        scoped, _ = await techlead.feature_scope(github, [_pr(3, 21)], 10)
        assert [p["number"] for p in scoped] == [3]

    async def test_the_review_pass_reads_only_the_scope(self, monkeypatch):
        github = _GitHub([_pr(1, 11), _pr(3, 21)], issues={
            11: {"number": 11, "body": "Parent: #10"}, 21: {"number": 21, "body": "Parent: #20"}})
        reviewed: list[int] = []

        async def review(github, claude, pr, context, *, workdir=None):
            reviewed.append(pr["number"])
            return {"pr_number": pr["number"], "decision": "APPROVE", "summary": "ok", "issues": []}

        monkeypatch.setattr(techlead, "_review_single_pr", review)
        result = await techlead.poll_and_review_prs(
            {"github": github, "claude": object(), "target_issue": 10, "reviewed_prs": []})

        assert reviewed == [1] and [r["pr_number"] for r in result["reviews"]] == [1]


# ── C3: every approved PR holds main before it merges ──────────────────


class TestUpdatedBeforeTheMerge:
    def _behind(self, *, new_head="h2"):
        return _GitHub(
            [_pr(7, 11, head_sha="h1")], behind={"feat/issue-11-x": 1}, heads={7: new_head},
            statuses={"h1": APPROVED},
            commits={"h2": {"parents": ["h1", "m9"], "committer": "web-flow",
                            "message": "Merge branch 'main' into feat/issue-11-x"}},
        )

    async def test_this_cycles_approval_gets_main_merged_in_then_merges_on_green(self, monkeypatch):
        monkeypatch.setattr(techlead, "UPDATED_HEAD_POLL_SECONDS", 0)
        github = self._behind()

        result = await techlead.merge_approved_prs(
            {"github": github, "github_repo": "o/r", "reviews": [{"pr_number": 7, "decision": "APPROVE"}]},
            ci_wait_seconds=0)

        assert github.updated == [7] and github.merged == [7] and result["updating_prs"] == []
        assert github.statuses["h2"]["description"].startswith("Approved")  # carried to the new head

    async def test_a_new_head_not_there_yet_waits_for_a_later_pass(self, monkeypatch):
        monkeypatch.setattr(techlead, "UPDATED_HEAD_SECONDS", 0)
        github = self._behind(new_head="h1")  # GitHub has not made it yet

        result = await techlead.merge_approved_prs(
            {"github": github, "github_repo": "o/r", "reviews": [{"pr_number": 7, "decision": "APPROVE"}]})

        assert github.merged == [] and result["updating_prs"] == [7]

    async def test_the_end_of_cycle_merge_on_its_own_repository_does_it_too(self, monkeypatch):
        monkeypatch.setattr(techlead, "UPDATED_HEAD_POLL_SECONDS", 0)
        github = self._behind()

        merged = await cycle._merge_held_prs(github, [7], None, ci_wait_seconds=0)

        assert github.updated == [7] and merged == [7]


class TestCiOnANewHead:
    async def test_no_check_yet_is_waited_for(self):
        reads = iter([[], [], [{"name": "tests", "state": "success"}]])

        class _Ci:
            async def get_ci_checks(self, sha):
                return next(reads)

        async def no_sleep(_):
            return None

        verdict = await ci_gate.wait_for_ci(_Ci(), "h2", wait_seconds=300, sleep=no_sleep, new_head=True)
        assert verdict.state == "green"

    async def test_out_of_time_before_any_check_is_pending_never_merged_unread(self):
        class _Ci:
            async def get_ci_checks(self, sha):
                return []

        assert (await ci_gate.wait_for_ci(_Ci(), "h2", wait_seconds=0, new_head=True)).state == "pending"
        assert (await ci_gate.wait_for_ci(_Ci(), "h2", wait_seconds=0)).state == "none"  # an old head: no CI


# ── C4, C6: a pinned cycle leaves the backlog and main's dated files alone ──


class TestThePinnedPO:
    async def test_the_morning_touches_no_backlog_and_asks_nobody(self):
        class _Untouched:
            def __getattr__(self, name):
                raise AssertionError(f"the backlog was read: {name}")

        result = await po.select_daily_issues(
            {"github": _Untouched(), "claude": _Untouched(), "target_issue": 841})

        assert result["daily_plan"] == "" and result["tokens_used"] == 0

    async def test_the_report_is_not_written_on_main(self):
        class _NoWrite:
            async def update_file(self, **kw):
                raise AssertionError("a dated report was written on main")

        result = await po.write_daily_report(
            {"github": _NoWrite(), "daily_report": "All green.", "target_issue": 841})

        assert result["result"] == "Report kept with the cycle"


class _File:
    """One file on main through the contents API, slow between read and write."""

    def __init__(self, text=""):
        self.text = text
        self.repo_name = "o/r"

    async def get_file_content(self, path):
        content = self.text
        await asyncio.sleep(0.01)  # the other cycle reads meanwhile
        return content

    async def update_file(self, path, content, branch, commit_message):
        self.text = content


class TestOneWriterAtATime:
    async def test_two_memory_appends_side_by_side_both_land(self, monkeypatch):
        from theswarm import memory_store

        file = _File()

        async def load(github):
            return [] if not file.text else [{"line": line} for line in file.text.splitlines()]

        async def save(github, entries, *, branch="main", message=""):
            await asyncio.sleep(0.01)
            file.text = "\n".join(e.get("line") or e["content"] for e in entries)
            return True

        monkeypatch.setattr(memory_store, "load_entries", load)
        monkeypatch.setattr(memory_store, "save_entries", save)
        entry = lambda c: {"agent": "QA", "category": "learnings", "content": c}  # noqa: E731

        await asyncio.gather(memory_store.append_entries(file, [entry("a")]),
                             memory_store.append_entries(file, [entry("b")]))

        assert sorted(file.text.splitlines()) == ["a", "b"]

    async def test_two_cycle_log_lines_side_by_side_both_land(self, monkeypatch):
        from theswarm import cycle_log

        file = _File()
        monkeypatch.setitem(sys.modules, "theswarm.tools.github",
                            SimpleNamespace(GitHubClient=lambda repo: file))
        config = SimpleNamespace(is_real_mode=True, github_repo="o/r")

        await asyncio.gather(cycle_log.append_cycle_log(config, {"date": "2026-11-15"}),
                             cycle_log.append_cycle_log(config, {"date": "2026-11-15"}))

        assert len(file.text.splitlines()) == 2

    async def test_the_lock_is_one_per_repository_and_file(self):
        assert main_writes.file_lock("o/r", "a") is main_writes.file_lock("o/r", "a")
        assert main_writes.file_lock("o/r", "a") is not main_writes.file_lock("o/s", "a")


# ── C5: QA's captures share a bound; no demo server outlives its phase ──


class TestCaptures:
    async def test_two_cycles_never_run_more_lanes_than_the_bound(self, monkeypatch):
        monkeypatch.setenv("SWARM_QA_LANES_IN_ALL", "2")
        qa._LANE_SLOTS.clear()
        active, peak = 0, 0

        async def lane(state, *_, **__):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.02)
            active -= 1
            ready = state.get("demo_server_ready")
            if ready is not None:
                ready.set()
            return {"tokens_used": 0}

        for name in ("capture_demo_screenshots", "record_demo_video"):
            monkeypatch.setattr(qa, name, lane)

        async def nothing(state):
            return {}

        monkeypatch.setattr(qa, "capture_before_after_per_story", nothing)
        monkeypatch.setattr(qa, "record_story_video", nothing)
        state = {"feature_pages": [], "feature_calls": {"calls": []}}

        await asyncio.wait_for(asyncio.gather(
            qa.run_captures({**state, "workspace": "/w/a"}), qa.run_captures({**state, "workspace": "/w/b"}),
        ), 5)

        assert peak == 2  # four lanes asked, two at a time

    async def test_a_cancelled_capture_leaves_no_demo_server_running(self, monkeypatch, tmp_path):
        launched: list = []

        async def screenshots(state):
            launched.append(await qa._launch_demo_server(
                [sys.executable, "-c", "import time; time.sleep(60)"], str(tmp_path), None))
            await asyncio.sleep(60)  # the readiness wait, cancelled by a phase timeout

        monkeypatch.setattr(qa, "capture_demo_screenshots", screenshots)
        task = asyncio.create_task(qa.run_captures(
            {"workspace": str(tmp_path), "feature_pages": [], "feature_calls": {"calls": []}}))
        while not launched:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert launched[0].returncode is not None
