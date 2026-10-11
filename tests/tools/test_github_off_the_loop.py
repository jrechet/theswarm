"""GitHub is read in the worker thread, never on the event loop.

PyGithub 2 returns lazy objects and fetches them on the first attribute
read; `GitHubClient.get_issue` read them on the event loop and stalled
every request the server was answering for a round trip — 0.35–0.55 s per
issue on a theater or a feature page (2026-10-11). `get_open_prs` did the
same once per PR (`mergeable` is never in the listing).
"""

from __future__ import annotations

import threading

from theswarm.tools import github as gh_mod
from theswarm.tools.github import GitHubClient


class _Lazy:
    """An object whose attributes say which thread read them."""

    def __init__(self, seen: list, **attrs):
        object.__setattr__(self, "_seen", seen)
        object.__setattr__(self, "_attrs", attrs)

    def __getattr__(self, name):
        self._seen.append(threading.get_ident())
        return self._attrs[name]


def _issue(seen):
    return _Lazy(seen, number=601, title="t", body="", labels=[], state="open", state_reason=None,
                 assignees=[], html_url="https://github.com/o/r/issues/601")


def _pr(seen):
    head = _Lazy(seen, ref="feat/x", sha="abc")
    base = _Lazy(seen, ref="main")
    return _Lazy(seen, number=7, title="t", body="", state="open", head=head, base=base,
                 mergeable=True, html_url="https://github.com/o/r/pull/7")


class _Repo:
    def __init__(self, seen):
        self.seen = seen

    def get_issue(self, number):
        return _issue(self.seen)

    def get_pulls(self, state="open"):
        return [_pr(self.seen)]

    def get_pull(self, number):
        return _pr(self.seen)


def _client(monkeypatch, seen):
    monkeypatch.setattr(gh_mod.Github, "get_repo", lambda self, name, **kw: _Repo(seen))
    return GitHubClient("o/r")


async def test_an_issue_is_read_off_the_loop(monkeypatch):
    seen: list[int] = []
    client = _client(monkeypatch, seen)

    issue = await client.get_issue(601)

    assert issue["number"] == 601
    assert seen and threading.get_ident() not in seen


async def test_open_prs_are_read_off_the_loop(monkeypatch):
    seen: list[int] = []
    client = _client(monkeypatch, seen)

    prs = await client.get_open_prs()
    pr = await client.get_pr(7)

    assert prs[0]["mergeable"] is True and pr["head"] == "feat/x"
    assert seen and threading.get_ident() not in seen
