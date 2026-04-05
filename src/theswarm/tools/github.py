"""Async-friendly GitHub client wrapping PyGitHub for the SWARM MVP.

All methods run PyGitHub calls in a thread executor to avoid blocking the
async event loop.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from functools import partial
from typing import Any

from github import Github, GithubException
from github.Issue import Issue
from github.PullRequest import PullRequest
from github.Repository import Repository


@dataclass
class GitHubClient:
    """Thin async wrapper around PyGitHub for a single repo."""
    repo_name: str
    _gh: Github = field(init=False, repr=False)
    _repo: Repository = field(init=False, repr=False)

    def __post_init__(self) -> None:
        token = os.environ.get("GITHUB_TOKEN", "")
        self._gh = Github(token)
        self._repo = self._gh.get_repo(self.repo_name)

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))

    # ── Issues ──────────────────────────────────────────────────────────

    async def get_issues(
        self,
        labels: list[str] | None = None,
        state: str = "open",
    ) -> list[dict]:
        """Return issues matching labels, as plain dicts."""
        kwargs: dict[str, Any] = {"state": state}
        if labels:
            kwargs["labels"] = labels
        issues: list[Issue] = await self._run(
            lambda: list(self._repo.get_issues(**kwargs))
        )
        return [_issue_to_dict(i) for i in issues if not i.pull_request]

    async def create_issue(
        self,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict:
        issue = await self._run(
            self._repo.create_issue,
            title=title,
            body=body,
            labels=labels or [],
            assignees=assignees or [],
        )
        return _issue_to_dict(issue)

    async def add_comment(self, issue_number: int, body: str) -> None:
        issue = await self._run(self._repo.get_issue, issue_number)
        await self._run(issue.create_comment, body)

    async def add_labels(self, issue_number: int, labels: list[str]) -> None:
        issue = await self._run(self._repo.get_issue, issue_number)
        for label in labels:
            await self._run(issue.add_to_labels, label)

    async def remove_label(self, issue_number: int, label: str) -> None:
        issue = await self._run(self._repo.get_issue, issue_number)
        try:
            await self._run(issue.remove_from_labels, label)
        except GithubException:
            pass  # label not present

    # ── Branches ────────────────────────────────────────────────────────

    async def create_branch(self, branch_name: str, from_branch: str = "main") -> None:
        ref = await self._run(self._repo.get_git_ref, f"heads/{from_branch}")
        await self._run(
            self._repo.create_git_ref,
            ref=f"refs/heads/{branch_name}",
            sha=ref.object.sha,
        )

    # ── Pull Requests ───────────────────────────────────────────────────

    async def create_pr(
        self,
        branch: str,
        base: str,
        title: str,
        body: str = "",
    ) -> dict:
        pr = await self._run(
            self._repo.create_pull,
            title=title,
            body=body,
            head=branch,
            base=base,
        )
        return _pr_to_dict(pr)

    async def get_open_prs(self) -> list[dict]:
        prs: list[PullRequest] = await self._run(
            lambda: list(self._repo.get_pulls(state="open"))
        )
        return [_pr_to_dict(p) for p in prs]

    async def get_pr_files(self, pr_number: int) -> list[dict]:
        """Return the list of changed files in a PR with patch diffs."""
        pr = await self._run(self._repo.get_pull, pr_number)
        files = await self._run(lambda: list(pr.get_files()))
        return [
            {
                "filename": f.filename,
                "status": f.status,  # added, modified, removed
                "additions": f.additions,
                "deletions": f.deletions,
                "patch": f.patch or "",
            }
            for f in files
        ]

    async def create_pr_review(
        self,
        pr_number: int,
        body: str,
        event: str = "COMMENT",  # APPROVE | REQUEST_CHANGES | COMMENT
    ) -> None:
        """Submit a review on a PR."""
        pr = await self._run(self._repo.get_pull, pr_number)
        await self._run(pr.create_review, body=body, event=event)

    async def merge_pr(self, pr_number: int, merge_method: str = "squash") -> None:
        pr = await self._run(self._repo.get_pull, pr_number)
        await self._run(pr.merge, merge_method=merge_method)

    # ── Files ───────────────────────────────────────────────────────────

    async def get_file_content(self, path: str, ref: str = "main") -> str:
        content_file = await self._run(self._repo.get_contents, path, ref=ref)
        return content_file.decoded_content.decode()

    async def update_file(
        self,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
    ) -> None:
        try:
            existing = await self._run(self._repo.get_contents, path, ref=branch)
            await self._run(
                self._repo.update_file,
                path,
                commit_message,
                content,
                existing.sha,
                branch=branch,
            )
        except GithubException:
            await self._run(
                self._repo.create_file,
                path,
                commit_message,
                content,
                branch=branch,
            )


# ── Helpers ─────────────────────────────────────────────────────────


def _issue_to_dict(issue: Issue) -> dict:
    return {
        "number": issue.number,
        "title": issue.title,
        "body": issue.body or "",
        "labels": [l.name for l in issue.labels],
        "state": issue.state,
        "assignees": [a.login for a in issue.assignees],
        "url": issue.html_url,
    }


def _pr_to_dict(pr: PullRequest) -> dict:
    return {
        "number": pr.number,
        "title": pr.title,
        "body": pr.body or "",
        "state": pr.state,
        "head": pr.head.ref,
        "base": pr.base.ref,
        "mergeable": pr.mergeable,
        "url": pr.html_url,
    }
