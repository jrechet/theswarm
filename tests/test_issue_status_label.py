"""The status label an issue carries (from V1's board tests, M6): the V3
board's word, read by `tools.github.issue_status`."""

from __future__ import annotations

from theswarm.tools.github import issue_status


def test_issue_status_reads_the_status_label():
    assert issue_status({"labels": ["status:ready"]}) == "ready"
    assert issue_status({"labels": ["status:review"]}) == "review"
    # dict-shaped labels (PyGithub) and unknown/absent statuses
    assert issue_status({"labels": [{"name": "status:in-progress"}]}) == "in-progress"
    assert issue_status({"labels": ["role:dev"]}) == "backlog"
    assert issue_status({}) == "backlog"
