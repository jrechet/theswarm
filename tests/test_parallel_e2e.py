"""The parallel harness judges a batch of cycles started at once.

The owner, 2026-11-11: "si j'envoie deux features en parallèle, j'ai
l'impression qu'elles se marchent dessus". The single harness proves one
feature gets built; nothing proved that two cycles at once each stay on
their own work. `scripts/parallel_e2e.py` starts N features together and
judges the batch — these are its pure parts.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def batch():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("parallel_e2e_under_test", ROOT / "scripts/parallel_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(story: int, cycle: str, **over) -> dict:
    return {"repo": "o/app", "story": story, "cycle": cycle, "state": "completed", "ran": True, "error": "",
            "opened": [], "pr_tasks": {}, "children": [], "open_children": [], "already_satisfied": [], **over}


class TestTheAsk:
    def test_a_repository_then_the_feature_as_the_composer_takes_it(self, batch):
        assert batch.parse_ask("jrechet/app: Delete a todo\nDELETE /todos/{id}: 204") == ("jrechet/app", "Delete a todo\nDELETE /todos/{id}: 204")

    @pytest.mark.parametrize("bad", ["no colon here", "app: no owner", "o/a/b: three parts", "o/app:   "])
    def test_anything_else_is_refused(self, batch, bad):
        with pytest.raises(ValueError):
            batch.parse_ask(bad)


class TestReading:
    def test_the_sub_task_a_pull_request_builds(self, batch):
        assert batch.task_of({"title": "[#317] Add the model", "headRefName": "feat/issue-99-x"}) == 317
        assert batch.task_of({"title": "Add the model", "headRefName": "feat/issue-317-add-the-model"}) == 317
        assert batch.task_of({"title": "chore(deps): fastapi", "headRefName": "renovate/fastapi"}) is None

    def test_the_phase_is_the_one_still_running(self, batch):
        row = {"phases": [{"phase": "po_morning", "status": "completed"}, {"phase": "dev_iter", "status": "running"}]}
        assert batch.phase_of(row) == "dev_iter"
        assert batch.phase_of({"phases": [{"phase": "qa", "status": "completed"}]}) == "qa"
        assert batch.phase_of({}) == ""

    def test_the_most_cycles_running_in_one_sample(self, batch):
        samples = [{"a": "queued", "b": "running"}, {"a": "running", "b": "running", "c": "queued"}, {"c": "running"}]
        assert batch.most_at_once(samples) == 2 and batch.most_at_once([]) == 0

    def test_waited_then_ran(self, batch):
        assert batch.spans([(0, "queued", ""), (600, "running", "po_morning"), (1800, "completed", "")]) == (600, 1200)
        assert batch.spans([(0, "queued", ""), (90, "failed", "")]) == (90, 0)


class TestTheJudgement:
    def test_two_cycles_each_on_their_own_feature_pass(self, batch):
        a = _run(10, "aaa", opened=[21, 22], pr_tasks={21: 11, 22: 12}, children=[11, 12])
        b = _run(13, "bbb", opened=[23], pr_tasks={23: 14}, children=[14])
        assert batch.judge([a, b], [{"aaa": "running", "bbb": "running"}], limit=2) == []

    def test_a_cycle_that_builds_its_sibling_s_sub_task_stepped_on_it(self, batch):
        a = _run(10, "aaa", opened=[21, 23], pr_tasks={21: 11, 23: 14}, children=[11])
        b = _run(13, "bbb", opened=[24], pr_tasks={24: 14}, children=[14])
        problems = batch.judge([a, b])
        assert any("opened PR #23 for #14, a sub-task of #13" in p for p in problems)
        assert any("o/app#14 was built by 2 cycles: aaa, bbb" in p for p in problems)

    def test_the_same_numbers_on_two_repositories_are_not_a_collision(self, batch):
        a = _run(10, "aaa", opened=[5], pr_tasks={5: 11}, children=[11])
        b = _run(10, "bbb", repo="o/other", opened=[5], pr_tasks={5: 11}, children=[11])
        assert batch.judge([a, b]) == []

    def test_a_cycle_that_failed_never_ran_or_left_work_open(self, batch):
        failed = _run(10, "aaa", state="failed", error="ClaudeFatalError: weekly limit")
        starved = _run(13, "bbb", state="timeout", ran=False)
        half = _run(15, "ccc", opened=[30], pr_tasks={30: 16}, children=[16, 17], open_children=[17])
        nothing = _run(18, "ddd")
        found = _run(19, "eee", already_satisfied=[20])
        problems = batch.judge([failed, starved, half, nothing, found])
        assert any("aaa" in p and "ended failed: ClaudeFatalError" in p for p in problems)
        assert any("bbb" in p and "never ran" in p for p in problems)
        assert any("ccc" in p and "left sub-tasks open: #17" in p for p in problems)
        assert any("ddd" in p and "built nothing" in p for p in problems)
        assert not any("eee" in p for p in problems)

    def test_more_running_than_the_instance_allows(self, batch):
        a = _run(10, "aaa", opened=[1], pr_tasks={1: 11}, children=[11])
        three = [{"aaa": "running", "bbb": "running", "ccc": "running"}]
        assert batch.judge([a], three, limit=2) == ["3 cycles ran at once, the limit is 2"]
        assert batch.judge([a], three) == []  # no limit given: not judged


class TestTheWatch:
    def test_every_cycle_is_followed_to_its_end_a_continuation_included(self, batch):
        now = {"t": 0.0}
        answers = {
            "aaa": [{"status": "queued"}, {"status": "running", "phases": [{"phase": "dev_iter", "status": "running"}]},
                    {"status": "failed", "resumed_as": "aa2"}],
            "aa2": [{"status": "running"}, {"status": "completed", "prs_opened": [7]}],
            "bbb": [{"status": "running"}, {"status": "running"}, {"status": "completed"}],
        }

        def api(path, payload=None):
            queue = answers[path.rsplit("/", 1)[-1]]
            return 200, (queue.pop(0) if len(queue) > 1 else queue[0])

        def sleep(seconds):
            now["t"] += seconds

        runs = [{"repo": "o/app", "story": 10, "cycle": "aaa"}, {"repo": "o/app", "story": 13, "cycle": "bbb"}]
        samples = batch.watch(runs, 600, api=api, sleep=sleep, clock=lambda: now["t"])
        assert [r["state"] for r in runs] == ["completed", "completed"] and all(r["ran"] for r in runs)
        assert runs[0]["cycle"] == "aa2" and runs[0]["record"]["prs_opened"] == [7]
        assert ("resumed", "aa2") in [step[1:] for step in runs[0]["timeline"]]
        assert batch.most_at_once(samples) == 2

    def test_a_batch_that_outlasts_its_budget_is_a_timeout(self, batch):
        now = {"t": 0.0}
        runs = [{"repo": "o/app", "story": 10, "cycle": "aaa"}]
        batch.watch(runs, 60, api=lambda path, payload=None: (200, {"status": "queued"}),
                    sleep=lambda s: now.__setitem__("t", now["t"] + s), clock=lambda: now["t"])
        assert runs[0]["state"] == "timeout" and not runs[0]["ran"]


class TestTheWeeklyBatch:
    """The weekly run takes its features from the eval manifests, as the daily
    harness does, and records each run so the rotation knows what was built
    (2026-11-14: the daily harness had begun asking for built features again)."""

    def _manifest(self):
        from theswarm import evals

        feature = lambda fid, built_by="": evals.Feature(id=fid, text=f"Do {fid}\nspec", built_by=built_by, max_cost_usd=8)  # noqa: E731
        return evals.Manifest(repo="o/app", features=(feature("a", "before"), feature("b"), feature("c"), feature("d")))

    def test_each_next_takes_a_feature_the_target_lacks_and_none_twice(self, batch):
        manifest = self._manifest()
        history = [{"feature": "b", "outcome": "built"}]
        taken: set[str] = set()
        first = batch.next_feature_of(manifest, history, taken)
        second = batch.next_feature_of(manifest, history, taken)
        assert {first.id, second.id} == {"c", "d"} and taken == {"c", "d"}
        assert batch.next_feature_of(manifest, history, taken) is None  # nothing left: the batch says so

    def test_a_run_is_scored_like_the_daily_harness_s(self, batch):
        from theswarm import evals

        feature = self._manifest().features[1]
        run = {"repo": "o/app", "story": 10, "cycle": "aaa", "first_cycle": "aa0", "state": "completed", "error": "",
               "opened": [21, 22], "merged": [21, 22], "open_children": [], "already_satisfied": [],
               "record": {"total_cost_usd": 3.5, "started_at": "2026-11-15T09:00:00+00:00",
                          "completed_at": "2026-11-15T09:30:00+00:00",
                          "result": {"cost_usd": 3.5, "backend": "sdk", "reviews": [{"decision": "APPROVE"}]}}}
        record = batch.scored(run, feature, batch_id="b-1")
        assert record["outcome"] == evals.OUTCOME_BUILT and record["passed"] and record["feature"] == "b"
        assert record["duration_s"] == 1800 and record["cost_usd"] == 3.5 and record["within_cost"] is True
        assert record["batch"] == "b-1" and record["cycle_id"] == "aaa" and record["issue"] == 10 and record["repo"] == "o/app"
        quota = {**run, "state": "failed", "opened": [], "merged": [],
                 "error": "ClaudeFatalError: Claude subscription exhausted"}
        assert batch.scored(quota, feature, batch_id="b-1")["outcome"] == evals.OUTCOME_INTERRUPTED


def test_a_batch_does_not_count_a_wait_for_the_claude_window(batch):
    now = {"t": 0.0}
    waiting = {"status": "running", "waiting": "Claude's subscription window is closed until 13:10 UTC"}
    answers = [waiting] * 20 + [{"status": "completed"}]

    def api(path, payload=None):
        return 200, (answers.pop(0) if len(answers) > 1 else answers[0])

    runs = [{"repo": "o/app", "story": 10, "cycle": "aaa"}]
    batch.watch(runs, 120, api=api, sleep=lambda s: now.__setitem__("t", now["t"] + s), clock=lambda: now["t"])
    assert runs[0]["state"] == "completed"
