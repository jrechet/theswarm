"""Each PR counts once in a demo report, however often it was reviewed.

A PR opened in iteration 1 is reviewed again in iteration 2, and every
approval was counted: the project page read "3/2 stories" — three
approvals of two PRs.

On SELF_REPO, TechLead approves but never merges (a merge would redeploy
the swarm mid-cycle) — those PRs are held for a human, not merged. Cycle
05b7dceeea99 reported "3 PRs merged" from exactly that confusion.
"""

from __future__ import annotations

from theswarm.api import _pr_numbers


def test_a_pr_approved_twice_is_one_merged_pr():
    result = {
        "prs": [{"number": 235}, {"number": 236}],
        "reviews": [
            {"pr_number": 235, "decision": "APPROVE"},
            {"pr_number": 235, "decision": "APPROVE"},   # reviewed again next iteration
            {"pr_number": 236, "decision": "APPROVE"},
        ],
    }

    opened, merged, held = _pr_numbers(result)

    assert opened == (235, 236)
    assert merged == (235, 236)
    assert held == ()


def test_a_request_for_changes_is_not_a_merge():
    result = {
        "prs": [{"number": 1}],
        "reviews": [{"pr_number": 1, "decision": "REQUEST_CHANGES"}],
    }

    assert _pr_numbers(result) == ((1,), (), ())


def test_bare_numbers_and_dicts_both_count():
    result = {"prs": [7, {"number": 9}, None], "reviews": []}

    assert _pr_numbers(result)[0] == (7, 9)


def test_zero_and_missing_numbers_are_dropped():
    result = {"prs": [{"title": "no number"}], "reviews": [{"decision": "APPROVE"}]}

    assert _pr_numbers(result) == ((), (), ())


def test_empty_result():
    assert _pr_numbers({}) == ((), (), ())


class TestExplicitMergedAndHeld:
    """When cycle.py supplies merged_prs/held_prs, those are authoritative —
    a review APPROVE no longer implies a merge."""

    def test_approved_and_held_is_not_counted_as_merged(self):
        result = {
            "prs": [{"number": 124}],
            "reviews": [{"pr_number": 124, "decision": "APPROVE"}],
            "merged_prs": [],
            "held_prs": [124],
        }

        opened, merged, held = _pr_numbers(result)

        assert merged == ()
        assert held == (124,)

    def test_actually_merged_prs_are_reported_merged(self):
        result = {
            "prs": [{"number": 10}, {"number": 11}],
            "reviews": [
                {"pr_number": 10, "decision": "APPROVE"},
                {"pr_number": 11, "decision": "APPROVE"},
            ],
            "merged_prs": [10, 11],
            "held_prs": [],
        }

        assert _pr_numbers(result) == ((10, 11), (10, 11), ())

    def test_mix_of_merged_and_held(self):
        result = {
            "prs": [{"number": 1}, {"number": 2}],
            "merged_prs": [1],
            "held_prs": [2],
        }

        assert _pr_numbers(result) == ((1, 2), (1,), (2,))

    def test_duplicates_across_iterations_count_once(self):
        result = {
            "prs": [{"number": 5}],
            "merged_prs": [5, 5],
            "held_prs": [],
        }

        assert _pr_numbers(result) == ((5,), (5,), ())
