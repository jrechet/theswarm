"""Approved PRs land by themselves — at the end of the cycle, not during it.

On `SELF_REPO` the review phase holds its approvals instead of merging: a
merge to main redeploys this service, and the redeploy ends the cycle that
just merged, halfway through its own review phase. That rule stays.

What changes (owner's call, 2026-09-21) is that the holding is no longer
permanent. The cycle merges what it approved once QA, the report and the
demo are done, so nothing is left for a person to do and nothing is killed
mid-flight.

The second reason the timing matters showed up in cycle 6: #165 and #164
rewrote the same file, and merging one made the other unmergeable. A merge
that fails now is reported and left open, never silently dropped.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from theswarm.cycle import _merge_held_prs


def _github(*, open_prs=None, merge_error: dict | None = None) -> AsyncMock:
    gh = AsyncMock()
    gh.get_open_prs = AsyncMock(return_value=open_prs or [])
    gh.delete_branch = AsyncMock()

    async def merge(pr_number, merge_method="squash"):
        if merge_error and pr_number in merge_error:
            raise RuntimeError(merge_error[pr_number])

    gh.merge_pr = AsyncMock(side_effect=merge)
    return gh


async def test_each_held_pr_is_merged_and_its_branch_removed():
    gh = _github(open_prs=[
        {"number": 169, "head": "feat/a"},
        {"number": 172, "head": "feat/b"},
    ])

    merged = await _merge_held_prs(gh, [169, 172], None)

    assert merged == [169, 172]
    assert [c.args[0] for c in gh.merge_pr.call_args_list] == [169, 172]
    assert sorted(c.args[0] for c in gh.delete_branch.call_args_list) == [
        "feat/a", "feat/b",
    ]


async def test_a_pr_that_cannot_merge_is_left_open():
    """#164 became unmergeable the moment its companion landed."""
    gh = _github(
        open_prs=[{"number": 169, "head": "feat/a"}, {"number": 164, "head": "feat/b"}],
        merge_error={164: "Pull Request has merge conflicts"},
    )

    merged = await _merge_held_prs(gh, [164, 169], None)

    assert merged == [169], "a failed merge must not be reported as merged"
    assert [c.args[0] for c in gh.delete_branch.call_args_list] == ["feat/a"], (
        "the branch of a PR that did not merge must survive"
    )


async def test_nothing_held_means_nothing_done():
    gh = _github()

    assert await _merge_held_prs(gh, [], None) == []
    gh.merge_pr.assert_not_awaited()


async def test_a_missing_github_client_is_not_an_error():
    """Stub mode reaches the same end-of-cycle path."""
    assert await _merge_held_prs(None, [169], None) == []
