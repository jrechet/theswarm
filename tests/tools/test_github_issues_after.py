"""A feature's sub-tasks are opened after it: `get_issues(created_after=N)` reads
the issues back from the newest and stops at N, instead of listing the whole
repository (concert-tour-app: 614 issues, 16 s, for the theater's panel)."""

from __future__ import annotations

from types import SimpleNamespace

from theswarm.tools import github as gh


def _issue(n, pr=False):
    return SimpleNamespace(number=n, title=f"#{n}", body="", labels=[], state="open", state_reason=None,
                           assignees=[], html_url=f"https://x/{'pull' if pr else 'issues'}/{n}")


class _Repo:
    def __init__(self, numbers):
        self.numbers, self.read, self.kwargs = numbers, [], None

    def get_issues(self, **kwargs):
        self.kwargs = kwargs

        def lazy():  # what a PaginatedList does: one issue at a time, newest first
            for n in sorted(self.numbers, reverse=True):
                self.read.append(n)
                yield _issue(n, pr=(n == 618))
        return lazy()


def _client(numbers):
    client = gh.GitHubClient.__new__(gh.GitHubClient)
    client._repo = _Repo(numbers)

    async def fresh():
        return None

    async def run(fn, *a, **kw):
        return fn(*a, **kw)

    client._fresh, client._run = fresh, run
    return client


async def test_newest_first_stopping_at_the_parent():
    client = _client(range(1, 621))
    issues = await client.get_issues(state="all", created_after=615)
    assert [i["number"] for i in issues] == [620, 619, 617, 616]  # the PR #618 left out
    assert client._repo.read == [620, 619, 618, 617, 616, 615]  # read down to the parent, not the 614 below it
    assert client._repo.kwargs == {"state": "all", "sort": "created", "direction": "desc"}


async def test_without_it_the_whole_list_as_before():
    client = _client(range(1, 6))
    issues = await client.get_issues(state="all")
    assert sorted(i["number"] for i in issues) == [1, 2, 3, 4, 5] and client._repo.kwargs == {"state": "all"}
