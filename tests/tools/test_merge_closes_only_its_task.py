"""A merge closes the PR's own task, never the story above it.

swarm-todo-app, 2026-11-14 (cycle a666c82e775a, the weekly parallel run):
the breakdown wrote "PR references `Closes #31`" — the story — into each
sub-task's acceptance criteria; the Dev put `Closes #31` in its commit
message; the squash merge of PR #36 kept it, and GitHub closed the story
while its last sub-task, the endpoint itself (#34), had not been built. The
cycle ended on a closed story and the feature was half there.

The swarm now writes the squash message itself: the PR's commits, with any
closing keyword aimed at an issue the PR does not close turned into a plain
reference.
"""

from __future__ import annotations

from types import SimpleNamespace

from theswarm.tools import github as gh_mod
from theswarm.tools.github import GitHubClient, closing_refs, squash_message


def test_what_a_pr_closes():
    assert closing_refs("Implements #32\n\nCloses #32\nFixes #40, resolves #41") == {32, 40, 41}
    assert closing_refs("Parent: #31 — see #31") == set()
    assert closing_refs(None) == set()


def test_a_closing_keyword_for_another_issue_becomes_a_reference():
    message = squash_message(
        ["feat: add owner-scoped todo count aggregation\n\nAdd the query.\n\nCloses #31",
         "test: cover it\n\nFixes #32"],
        keep={32},
    )
    assert "Closes #31" not in message and "Refs #31" in message
    assert "Fixes #32" in message  # the PR's own task still closes
    assert message.startswith("* feat: add owner-scoped todo count aggregation")


def test_the_case_and_the_forms_github_reads_are_all_caught():
    message = squash_message(["close #5\nCLOSED #6\nresolved: #7\nfixes #8"], keep=set())
    assert all(f"Refs #{n}" in message for n in (5, 6, 7, 8))


class _Pull:
    def __init__(self):
        self.number, self.title = 36, "[#33] Add an owner-scoped todo count aggregation"
        self.body = "Implements #33\n\nCloses #33\n\nParent: #31"
        self.merged_with: dict = {}

    def get_commits(self):
        return [SimpleNamespace(commit=SimpleNamespace(message="feat: aggregation\n\nCloses #31")),
                SimpleNamespace(commit=SimpleNamespace(message="fix: zero case"))]

    def merge(self, **kwargs):
        self.merged_with = kwargs


async def test_the_swarm_s_squash_closes_the_task_and_never_the_story(monkeypatch):
    pull = _Pull()
    monkeypatch.setattr(gh_mod.Github, "get_repo", lambda self, name, **kw: SimpleNamespace(get_pull=lambda n: pull))
    client = GitHubClient("o/r")

    await client.merge_pr(36, merge_method="squash")

    sent = pull.merged_with
    assert sent["merge_method"] == "squash" and sent["commit_title"] == "[#33] Add an owner-scoped todo count aggregation (#36)"
    assert "Closes #31" not in sent["commit_message"] and "Refs #31" in sent["commit_message"]
    assert "Closes #33" in sent["commit_message"]  # what the PR closes is said once more, in the message itself


async def test_a_merge_that_is_not_a_squash_is_left_as_github_writes_it(monkeypatch):
    pull = _Pull()
    monkeypatch.setattr(gh_mod.Github, "get_repo", lambda self, name, **kw: SimpleNamespace(get_pull=lambda n: pull))
    await GitHubClient("o/r").merge_pr(36, merge_method="merge")
    assert pull.merged_with == {"merge_method": "merge"}
