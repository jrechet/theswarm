"""Listing issues must not cost one API call per issue.

The board fragment timed out behind Traefik's 30s cap: `get_issues()` took
27.8s for 50 issues in prod. GitHub's issues endpoint includes pull
requests, flagged by a `pull_request` key; reading PyGithub's
`.pull_request` property fires a *completion request per issue* when that
key is absent. `html_url` is already in the list payload and discriminates
for free — the same listing then measured 1.2s.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from theswarm.tools.github import _is_pull_request


class _ExplodingPullRequestProperty:
    """An issue whose `.pull_request` access would hit the network."""

    def __init__(self, html_url: str) -> None:
        self.html_url = html_url
        self.number = 1
        self.title = "t"
        self.body = ""
        self.labels: list = []
        self.state = "open"
        self.assignees: list = []

    @property
    def pull_request(self):  # pragma: no cover - must never be reached
        raise AssertionError("touching .pull_request triggers an API call per issue")


def test_issue_and_pr_are_told_apart_from_the_list_payload():
    issue = SimpleNamespace(html_url="https://github.com/o/r/issues/42")
    pull = SimpleNamespace(html_url="https://github.com/o/r/pull/42")

    assert _is_pull_request(issue) is False
    assert _is_pull_request(pull) is True


def test_missing_html_url_is_treated_as_an_issue():
    assert _is_pull_request(SimpleNamespace(html_url=None)) is False
    assert _is_pull_request(SimpleNamespace(html_url="")) is False


def test_filtering_never_touches_the_lazy_property():
    """The whole point: no per-issue completion request."""
    items = [
        _ExplodingPullRequestProperty("https://github.com/o/r/issues/1"),
        _ExplodingPullRequestProperty("https://github.com/o/r/pull/2"),
    ]

    kept = [i for i in items if not _is_pull_request(i)]

    assert [i.html_url for i in kept] == ["https://github.com/o/r/issues/1"]


async def test_get_issues_filters_pull_requests_without_completion(monkeypatch):
    """End-to-end through the client, with a repo that only serves a list."""
    from theswarm.tools import github as gh_mod

    listed = [
        _ExplodingPullRequestProperty("https://github.com/o/r/issues/10"),
        _ExplodingPullRequestProperty("https://github.com/o/r/pull/11"),
        _ExplodingPullRequestProperty("https://github.com/o/r/issues/12"),
    ]

    class _FakeRepo:
        def get_issues(self, **kwargs):
            return listed

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setattr(
        gh_mod.Github, "get_repo", lambda self, name: _FakeRepo(), raising=True,
    )
    client = gh_mod.GitHubClient("o/r")

    issues = await client.get_issues()

    # The PR is dropped, and no .pull_request access blew up on the way
    assert len(issues) == 2
    assert {i["url"] for i in issues} == {
        "https://github.com/o/r/issues/10",
        "https://github.com/o/r/issues/12",
    }
