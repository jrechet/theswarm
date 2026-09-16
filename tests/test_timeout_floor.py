"""A budget that already expired must never be tried again.

TheSwarm asked to work on its own source (cycle be8e68aaef9d, issue #85)
timed out at 420s, retried at 546s, timed out again — and then the *next*
dev iteration started back at 420s and repeated the whole thing. Five
iterations, sixteen minutes each, no progress and nothing learned. The
growth in `_retry_timeout` lived only inside one `run()` call.
"""

from __future__ import annotations

import pytest

from theswarm.tools.claude import ClaudeCLI


def _timeout(seconds: int) -> Exception:
    """An error shaped like the one `_run_cli` raises on expiry."""
    return RuntimeError(f"CLI timed out after {seconds}s")


class TestFloorIsLearned:
    def test_first_timeout_grows_the_budget(self):
        claude = ClaudeCLI()

        grown = claude._retry_timeout(420, _timeout(420))

        assert grown == 546  # 420 × 1.3

    def test_the_grown_budget_becomes_the_floor(self):
        claude = ClaudeCLI()

        claude._retry_timeout(420, _timeout(420))

        assert claude._timeout_floor == 546

    def test_a_later_call_starts_at_the_floor_not_the_constant(self):
        """The bug: iteration 2 asked for 420s again and died identically."""
        claude = ClaudeCLI()
        claude._retry_timeout(420, _timeout(420))

        assert claude._effective_timeout(420) == 546

    def test_escalation_continues_across_calls(self):
        claude = ClaudeCLI()

        claude._retry_timeout(420, _timeout(420))      # → 546
        second = claude._retry_timeout(420, _timeout(546))

        # Grows from the floor (546), not from the caller's stale 420.
        assert second == 709
        assert claude._timeout_floor == 709

    def test_a_caller_asking_for_more_than_the_floor_keeps_its_own_budget(self):
        claude = ClaudeCLI()
        claude._retry_timeout(420, _timeout(420))      # floor 546

        assert claude._effective_timeout(900) == 900


class TestFloorIsBounded:
    def test_growth_stops_at_the_ceiling(self):
        claude = ClaudeCLI(timeout_ceiling=600)

        grown = claude._retry_timeout(500, _timeout(500))

        assert grown == 600  # not 650

    def test_the_floor_never_exceeds_the_ceiling(self):
        claude = ClaudeCLI(timeout_ceiling=600)

        for _ in range(10):
            claude._retry_timeout(500, _timeout(500))

        assert claude._timeout_floor == 600

    def test_the_ceiling_leaves_room_inside_a_dev_iteration(self):
        """One call plus its retry must fit the phase budget, or the phase
        timeout fires first and hides why the call actually failed."""
        from theswarm.cycle import PHASE_TIMEOUTS

        claude = ClaudeCLI()
        worst_case = 2 * claude.timeout_ceiling

        assert worst_case < PHASE_TIMEOUTS["dev_iter"]


class TestOnlyTimeoutsMove:
    def test_a_crash_does_not_move_the_floor(self):
        claude = ClaudeCLI()

        claude._retry_timeout(420, RuntimeError("segfault"))

        assert claude._timeout_floor == 0

    def test_an_auth_failure_does_not_move_the_floor(self):
        claude = ClaudeCLI()

        claude._retry_timeout(420, RuntimeError("401 not logged in"))

        assert claude._timeout_floor == 0

    def test_a_crash_keeps_the_budget_it_had(self):
        claude = ClaudeCLI()

        assert claude._retry_timeout(420, RuntimeError("boom")) == 420


class TestFloorSurvivesTaskRouting:
    def test_for_task_carries_the_floor(self):
        """`for_task` builds a fresh instance per task category. The floor
        describes the repo being worked on, not the model, so it must travel."""
        claude = ClaudeCLI()
        claude._retry_timeout(420, _timeout(420))

        routed = claude.for_task("implementation")

        assert routed._timeout_floor == 546

    def test_for_task_with_routing_carries_the_floor(self):
        claude = ClaudeCLI()
        claude._retry_timeout(420, _timeout(420))

        routed = claude.for_task("implementation", {"implementation": "opus"})

        assert routed.model == "opus"
        assert routed._timeout_floor == 546

    def test_for_task_carries_the_ceiling(self):
        claude = ClaudeCLI(timeout_ceiling=600)

        assert claude.for_task("anything").timeout_ceiling == 600


class TestDefaultsUnchangedWhenNothingTimesOut:
    def test_a_fresh_client_uses_the_callers_budget(self):
        assert ClaudeCLI()._effective_timeout(420) == 420

    def test_a_fresh_client_falls_back_to_its_own_default(self):
        assert ClaudeCLI(timeout=180)._effective_timeout(None) == 180

    @pytest.mark.parametrize("asked", [30, 180, 420, 780])
    def test_no_floor_means_no_change(self, asked):
        assert ClaudeCLI()._effective_timeout(asked) == asked


# ── The floor outlives the instance, per workspace ─────────────────────
#
# A cycle's instance learned 420 → 546 → 709 on TheSwarm's own repo and took
# it to the grave; the next cycle paid the same sixteen minutes to learn it
# again (#99).


@pytest.fixture(autouse=True)
def _clean_repo_floors():
    from theswarm.tools import claude as claude_mod

    claude_mod._REPO_FLOORS.clear()
    yield
    claude_mod._REPO_FLOORS.clear()


class TestRepoFloorSurvivesTheInstance:
    def test_a_fresh_instance_starts_where_the_last_one_stopped(self):
        first = ClaudeCLI()
        first._retry_timeout(420, _timeout(420), workdir="/ws/theswarm")

        second = ClaudeCLI()

        assert second._effective_timeout(420, "/ws/theswarm") == 546

    def test_workspaces_do_not_share_a_floor(self):
        ClaudeCLI()._retry_timeout(420, _timeout(420), workdir="/ws/theswarm")

        assert ClaudeCLI()._effective_timeout(420, "/ws/concert-tour-app") == 420

    def test_the_repo_floor_only_moves_up(self):
        claude = ClaudeCLI()
        claude._retry_timeout(420, _timeout(420), workdir="/ws/x")   # 546
        claude._retry_timeout(420, _timeout(546), workdir="/ws/x")   # 709

        from theswarm.tools import claude as claude_mod
        assert claude_mod._REPO_FLOORS["/ws/x"] == 709

    def test_escalation_continues_across_instances(self):
        ClaudeCLI()._retry_timeout(420, _timeout(420), workdir="/ws/x")   # 546

        grown = ClaudeCLI()._retry_timeout(420, _timeout(546), workdir="/ws/x")

        assert grown == 709

    def test_no_workdir_no_repo_floor(self):
        claude = ClaudeCLI()
        claude._retry_timeout(420, _timeout(420))

        from theswarm.tools import claude as claude_mod
        assert claude_mod._REPO_FLOORS == {}
        assert claude._timeout_floor == 546  # the instance still learns

    def test_the_ceiling_bounds_the_repo_floor_too(self):
        claude = ClaudeCLI(timeout_ceiling=600)
        for _ in range(6):
            claude._retry_timeout(500, _timeout(500), workdir="/ws/x")

        from theswarm.tools import claude as claude_mod
        assert claude_mod._REPO_FLOORS["/ws/x"] == 600
