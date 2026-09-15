"""Each PR counts once in a demo report, however often it was reviewed.

A PR opened in iteration 1 is reviewed again in iteration 2, and every
approval was counted: the project page read "3/2 stories" — three
approvals of two PRs.
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

    opened, merged = _pr_numbers(result)

    assert opened == (235, 236)
    assert merged == (235, 236)


def test_a_request_for_changes_is_not_a_merge():
    result = {
        "prs": [{"number": 1}],
        "reviews": [{"pr_number": 1, "decision": "REQUEST_CHANGES"}],
    }

    assert _pr_numbers(result) == ((1,), ())


def test_bare_numbers_and_dicts_both_count():
    result = {"prs": [7, {"number": 9}, None], "reviews": []}

    assert _pr_numbers(result)[0] == (7, 9)


def test_zero_and_missing_numbers_are_dropped():
    result = {"prs": [{"title": "no number"}], "reviews": [{"decision": "APPROVE"}]}

    assert _pr_numbers(result) == ((), ())


def test_empty_result():
    assert _pr_numbers({}) == ((), ())
