"""Nothing stays in review (owner, 2026-10-11: "les cartes restent bloquées
in review indéfiniment").

Three cards sat in review on prod. espace-client#499 and theswarm#321 were
approved while their CI still ran, left open, and nothing came back for
them: the owner's Play on each (2026-10-10) ended its dev loop at once and
never reached a review pass. concert-tour-app#307 was refused past the cap
and "left for a person" — the owner reviews demos, never code. And #321 was
13 commits behind main, one of them a migration of its own number: merged
as approved, its green CI said nothing about main.
"""

from __future__ import annotations

import asyncio

from theswarm import cycle, cycle_graph
from theswarm.agents import techlead
from theswarm.application.services.merge_watch import MergeWatch, Sweep

APPROVED = {"state": "success", "description": "Approved: looks right"}
REFUSED = {"state": "failure", "description": "Changes requested: no test code"}


class _GitHub:
    """A repository on GitHub, as much as the merge needs."""

    def __init__(self, prs=(), *, statuses=None, checks=None, behind=None, update_ok=True,
                 commits=None, issues=None):
        self.prs = [dict(p) for p in prs]
        self.statuses = dict(statuses or {})
        self.checks = dict(checks or {})
        self.behind = dict(behind or {})
        self.update_ok = update_ok
        self.commits = dict(commits or {})
        self.issues = {n: dict(i) for n, i in (issues or {}).items()}
        self.merged: list[int] = []
        self.updated: list[int] = []
        self.closed_prs: list[int] = []
        self.closed_issues: list[tuple[int, bool]] = []
        self.comments: dict[int, list[str]] = {}
        self.labels: dict[int, set[str]] = {}
        self.published: list[tuple[str, str, str]] = []

    async def get_open_prs(self):
        return [p for p in self.prs if p["number"] not in self.merged + self.closed_prs]

    async def get_review_status(self, sha):
        return self.statuses.get(sha)

    async def get_commit_brief(self, sha):
        return self.commits.get(sha, {"parents": ["x"], "committer": "jrechet", "message": "feat"})

    async def create_commit_status(self, sha, state, description, *, context=""):
        self.published.append((sha, state, description))
        self.statuses[sha] = {"state": state, "description": description}

    async def get_ci_checks(self, sha):
        return self.checks.get(sha, [{"name": "tests", "state": "success"}])

    async def behind_by(self, head, base="main"):
        return self.behind.get(head, 0)

    async def update_pr_branch(self, number, expected_head_sha):
        self.updated.append(number)
        return self.update_ok

    async def merge_pr(self, number, merge_method="squash"):
        self.merged.append(number)

    async def delete_branch(self, name):
        pass

    async def close_pr(self, number):
        self.closed_prs.append(number)

    async def create_pr_comment(self, number, body):
        self.comments.setdefault(number, []).append(body)

    async def add_comment(self, number, body):
        self.comments.setdefault(number, []).append(body)

    async def get_issue_comments(self, number):
        return [{"body": b} for b in self.comments.get(number, [])]

    async def add_labels(self, number, labels):
        self.labels.setdefault(number, set()).update(labels)

    async def remove_label(self, number, label):
        self.labels.setdefault(number, set()).discard(label)

    async def close_issue(self, number, comment=None, *, not_planned=False):
        self.closed_issues.append((number, not_planned))
        if comment:
            self.comments.setdefault(number, []).append(comment)

    async def get_issue(self, number):
        return self.issues.get(number)

    async def get_issues(self, labels=None, state="open"):
        return list(self.issues.values())


def _pr(number=499, task=496, head_sha="h1", branch=None):
    return {"number": number, "title": f"[#{task}] Fix remember-me", "body": f"Closes #{task}",
            "head": branch or f"feat/issue-{task}-fix", "head_sha": head_sha, "base": "main"}


# ── A loop with nothing to build still reaches the merge ─────────────


class TestTheLoopsEnd:
    def test_a_loop_that_ends_before_any_review_goes_through_one(self):
        state = {"dev_outcome": "end", "iteration": 1, "reviewed_prs": []}
        assert cycle_graph._after_dev_iter(state) == "techlead_review"
        assert cycle_graph._after_review(state) == "dev_loop_end"

    def test_a_loop_that_reviewed_already_ends_as_before(self):
        state = {"dev_outcome": "end", "iteration": 3, "reviewed_prs": ["499@h1"]}
        assert cycle_graph._after_dev_iter(state) == "dev_loop_end"

    def test_a_pr_opened_is_reviewed_and_the_loop_goes_on(self):
        state = {"dev_outcome": "review", "iteration": 1, "reviewed_prs": []}
        assert cycle_graph._after_dev_iter(state) == "techlead_review"
        assert cycle_graph._after_review(state) == "dev_iter"

    def test_a_skipped_iteration_tries_again(self):
        assert cycle_graph._after_dev_iter({"dev_outcome": "skip", "iteration": 1}) == "dev_iter"


# ── An approval from an earlier cycle holds main before it merges ─────


class TestUpToDate:
    async def test_a_pr_that_holds_main_is_fresh(self):
        assert await techlead.bring_up_to_date(_GitHub(), _pr()) == "fresh"

    async def test_a_pr_behind_main_gets_main_merged_in(self):
        github = _GitHub(behind={"feat/issue-496-fix": 13})
        assert await techlead.bring_up_to_date(github, _pr()) == "updating"
        assert github.updated == [499]

    async def test_a_pr_that_conflicts_with_main_says_so(self):
        github = _GitHub(behind={"feat/issue-496-fix": 2}, update_ok=False)
        assert await techlead.bring_up_to_date(github, _pr()) == "conflict"

    async def test_unreadable_never_blocks(self):
        class _Broken(_GitHub):
            async def behind_by(self, head, base="main"):
                raise RuntimeError("502")
        assert await techlead.bring_up_to_date(_Broken(), _pr()) == "unknown"


class TestTheApprovalCarriesOver:
    """GitHub's "Update branch" makes a new head: the PR's diff is the same."""

    def _merged_in(self, committer="web-flow"):
        return {"h2": {"parents": ["h1", "m9"], "committer": committer,
                       "message": "Merge branch 'main' into feat/issue-496-fix"}}

    async def test_over_githubs_merge_of_main(self):
        github = _GitHub(statuses={"h1": APPROVED}, commits=self._merged_in())

        verdict = await techlead._earlier_verdict(github, _pr(head_sha="h2"))

        assert verdict["decision"] == "APPROVE"
        assert github.published and github.published[0][0] == "h2"  # written on the new head

    async def test_not_over_a_merge_someone_made_by_hand(self):
        github = _GitHub(statuses={"h1": APPROVED}, commits=self._merged_in(committer="jrechet"))
        assert await techlead._earlier_verdict(github, _pr(head_sha="h2")) is None

    async def test_not_a_refusal(self):
        github = _GitHub(statuses={"h1": REFUSED}, commits=self._merged_in())
        assert await techlead._earlier_verdict(github, _pr(head_sha="h2")) is None


class TestTheMergePass:
    async def test_an_earlier_approval_behind_main_is_updated_not_merged(self):
        github = _GitHub([_pr()], behind={"feat/issue-496-fix": 13})
        review = {"pr_number": 499, "decision": "APPROVE", "earlier": True}

        result = await techlead.merge_approved_prs(
            {"github": github, "github_repo": "jrechet/espace-client", "reviews": [review]})

        assert github.merged == [] and result["updating_prs"] == [499]

    async def test_an_approval_of_this_cycle_merges_as_before(self):
        github = _GitHub([_pr()], behind={"feat/issue-496-fix": 1})
        review = {"pr_number": 499, "decision": "APPROVE"}

        await techlead.merge_approved_prs(
            {"github": github, "github_repo": "jrechet/espace-client", "reviews": [review]})

        assert github.merged == [499] and github.updated == []

    async def test_an_earlier_approval_that_conflicts_goes_back_to_the_dev(self):
        github = _GitHub([_pr()], behind={"feat/issue-496-fix": 2}, update_ok=False)
        review = {"pr_number": 499, "decision": "APPROVE", "earlier": True}

        result = await techlead.merge_approved_prs(
            {"github": github, "github_repo": "jrechet/espace-client", "reviews": [review]})

        assert result["conflicted_prs"] == [499] and "status:ready" in github.labels[496]


# ── Refused past the cap: given up, not parked for a person ───────────


class TestTheCap:
    async def test_the_pr_and_the_task_are_closed_with_why(self):
        github = _GitHub([_pr(307, 306)])
        github.comments[306] = [techlead.CHANGES_MARKER + " round"] * techlead.CHANGES_REQUESTED_CAP

        sent = await techlead._send_back_to_dev(github, _pr(307, 306), "No test code at all", [])

        assert sent is False
        assert github.closed_prs == [307]
        assert (306, True) in github.closed_issues  # not planned
        assert "No test code at all" in github.comments[307][-1]
        assert not github.labels.get(306)


# ── The watch, between cycles ────────────────────────────────────────


class _Projects:
    def __init__(self, *repos):
        self._repos = repos

    async def list_all(self):
        from types import SimpleNamespace
        return [SimpleNamespace(repo=r) for r in self._repos]


def _watch(github, *repos):
    return MergeWatch(_Projects(*repos), client_for=lambda repo: github, interval=0)


class TestTheWatch:
    async def test_an_approved_pr_merges_once_its_ci_is_green(self):
        github = _GitHub([_pr()], statuses={"h1": APPROVED},
                         issues={496: {"number": 496, "state": "open", "labels": ["status:review"], "body": ""}})

        [sweep] = await _watch(github, "jrechet/espace-client").sweep()

        assert sweep.merged == (499,) and github.merged == [499]

    async def test_one_whose_ci_still_runs_waits_for_the_next_turn(self):
        github = _GitHub([_pr()], statuses={"h1": APPROVED},
                         checks={"h1": [{"name": "integration-tests", "state": "in_progress"}]})

        [sweep] = await _watch(github, "jrechet/espace-client").sweep()

        assert sweep.waiting == (499,) and github.merged == []

    async def test_one_main_moved_past_gets_main_merged_in(self):
        github = _GitHub([_pr()], statuses={"h1": APPROVED}, behind={"feat/issue-496-fix": 2})

        [sweep] = await _watch(github, "jrechet/espace-client").sweep()

        assert sweep.updating == (499,) and github.updated == [499] and github.merged == []

    async def test_a_task_the_cap_parked_is_given_up(self):
        github = _GitHub([_pr(307, 306, head_sha="r1")], statuses={"r1": REFUSED},
                         issues={306: {"number": 306, "state": "open", "labels": ["status:review"], "body": ""}})

        [sweep] = await _watch(github, "jrechet/concert-tour-app").sweep()

        assert sweep.given_up == (307,) and github.closed_prs == [307]

    async def test_a_refusal_whose_task_went_back_to_the_dev_is_left_alone(self):
        github = _GitHub([_pr(307, 306, head_sha="r1")], statuses={"r1": REFUSED},
                         issues={306: {"number": 306, "state": "open", "labels": ["status:ready"], "body": ""}})

        [sweep] = await _watch(github, "jrechet/concert-tour-app").sweep()

        assert sweep.given_up == () and github.closed_prs == []

    async def test_a_pr_never_reviewed_waits_for_a_cycle(self):
        github = _GitHub([_pr()])

        [sweep] = await _watch(github, "jrechet/espace-client").sweep()

        assert sweep == Sweep("jrechet/espace-client") and github.merged == []

    async def test_a_repository_a_cycle_runs_on_is_left_alone(self):
        github = _GitHub([_pr()], statuses={"h1": APPROVED})
        lock = cycle.repo_lock("jrechet/espace-client")

        async with lock:
            [sweep] = await _watch(github, "jrechet/espace-client").sweep()

        assert sweep.skipped and github.merged == []

    async def test_its_own_repository_merges_only_its_own_branches(self):
        own = _pr(321, 317, head_sha="s1")
        foreign = {**_pr(330, 0, head_sha="s2", branch="renovate/x"), "title": "chore(deps): bump"}
        github = _GitHub([own, foreign], statuses={"s1": APPROVED, "s2": APPROVED})

        [sweep] = await _watch(github, "jrechet/theswarm").sweep()

        assert github.merged == [321] and sweep.merged == (321,)

    async def test_its_own_conflict_goes_back_to_the_dev_and_is_said(self):
        github = _GitHub([_pr(321, 317, head_sha="s1")], statuses={"s1": APPROVED},
                         behind={"feat/issue-317-fix": 13}, update_ok=False)

        [sweep] = await _watch(github, "jrechet/theswarm").sweep()

        assert sweep.sent_back == (321,) and "status:ready" in github.labels[317]

    async def test_its_own_repository_waits_while_any_cycle_runs(self):
        github = _GitHub([_pr(321, 317, head_sha="s1")], statuses={"s1": APPROVED})

        async with cycle.repo_lock("jrechet/concert-tour-app"):
            [sweep] = await _watch(github, "jrechet/theswarm").sweep()

        assert sweep.skipped and github.merged == []

    async def test_one_repository_failing_does_not_stop_the_others(self):
        good = _GitHub([_pr()], statuses={"h1": APPROVED})

        def client_for(repo):
            if repo == "jrechet/broken":
                raise RuntimeError("404")
            return good

        watch = MergeWatch(_Projects("jrechet/broken", "jrechet/espace-client"), client_for=client_for)
        sweeps = await watch.sweep()

        assert [s.repo for s in sweeps] == ["jrechet/espace-client"] and good.merged == [499]


class TestHeldOnItsOwnRepository:
    async def test_a_red_ci_goes_back_to_the_dev(self):
        github = _GitHub([_pr(321, 317, head_sha="s1")],
                         checks={"s1": [{"name": "tests", "state": "failure", "summary": "2 failed"}]})

        merged = await cycle._merge_held_prs(github, [321], None, ci_wait_seconds=0)

        assert merged == [] and "status:ready" in github.labels[317]
        assert any("ci-red" in c for c in github.comments[317])


def test_the_watch_is_off_in_the_suite():
    from theswarm.application.services.merge_watch import sweep_seconds
    assert sweep_seconds() == 0
    assert asyncio.iscoroutinefunction(MergeWatch.run_loop)
