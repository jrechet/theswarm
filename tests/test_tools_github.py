"""Tests for theswarm.tools.github — async GitHub client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from github import GithubException

from theswarm.tools.github import GitHubClient, _issue_to_dict, _pr_to_dict


# ── Helper function tests ─────────────────────────────────────────────


def _make_mock_issue(
    number: int = 1,
    title: str = "Bug fix",
    body: str = "Fix the thing",
    labels: list[str] | None = None,
    state: str = "open",
    assignees: list[str] | None = None,
    html_url: str = "https://github.com/o/r/issues/1",
    pull_request: object | None = None,
) -> MagicMock:
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.body = body
    label_mocks = []
    for name in (labels or []):
        lm = MagicMock()
        lm.name = name
        label_mocks.append(lm)
    issue.labels = label_mocks
    issue.state = state
    assignee_mocks = []
    for login in (assignees or []):
        am = MagicMock()
        am.login = login
        assignee_mocks.append(am)
    issue.assignees = assignee_mocks
    issue.html_url = html_url
    issue.pull_request = pull_request
    return issue


def _make_mock_pr(
    number: int = 10,
    title: str = "Add feature",
    body: str = "PR body",
    state: str = "open",
    head_ref: str = "feat/new",
    base_ref: str = "main",
    mergeable: bool = True,
    html_url: str = "https://github.com/o/r/pull/10",
) -> MagicMock:
    pr = MagicMock()
    pr.number = number
    pr.title = title
    pr.body = body
    pr.state = state
    pr.head.ref = head_ref
    pr.base.ref = base_ref
    pr.mergeable = mergeable
    pr.html_url = html_url
    return pr


def test_issue_to_dict():
    issue = _make_mock_issue(
        number=5,
        title="Test issue",
        body="Description",
        labels=["bug", "status:ready"],
        assignees=["alice"],
    )
    result = _issue_to_dict(issue)
    assert result["number"] == 5
    assert result["title"] == "Test issue"
    assert result["body"] == "Description"
    assert result["labels"] == ["bug", "status:ready"]
    assert result["assignees"] == ["alice"]
    assert result["state"] == "open"
    assert "url" in result


def test_issue_to_dict_no_body():
    issue = _make_mock_issue(body=None)
    result = _issue_to_dict(issue)
    assert result["body"] == ""


def test_pr_to_dict():
    pr = _make_mock_pr(number=42, head_ref="feat/x", base_ref="main")
    result = _pr_to_dict(pr)
    assert result["number"] == 42
    assert result["head"] == "feat/x"
    assert result["base"] == "main"
    assert result["mergeable"] is True
    assert "url" in result


def test_pr_to_dict_no_body():
    pr = _make_mock_pr(body=None)
    result = _pr_to_dict(pr)
    assert result["body"] == ""


# ── GitHubClient tests ────────────────────────────────────────────────


@pytest.fixture()
def github_client():
    """Create a GitHubClient without hitting real GitHub."""
    from theswarm.infrastructure.resilience import CircuitBreaker

    with patch.object(GitHubClient, "__post_init__"):
        client = GitHubClient.__new__(GitHubClient)
        client.repo_name = "owner/repo"
        client._repo = MagicMock()
        client._gh = MagicMock()
        client._breaker = CircuitBreaker(name="test", failure_threshold=999)
    return client


async def test_get_issues(github_client):
    issue1 = _make_mock_issue(number=1, pull_request=None)
    issue2 = _make_mock_issue(number=2, pull_request=MagicMock())  # is a PR
    github_client._repo.get_issues.return_value = [issue1, issue2]

    result = await github_client.get_issues(labels=["status:ready"])
    # Only issue1 should be returned (issue2 is a PR)
    assert len(result) == 1
    assert result[0]["number"] == 1


async def test_create_issue(github_client):
    mock_issue = _make_mock_issue(number=99, title="New issue")
    github_client._repo.create_issue.return_value = mock_issue

    result = await github_client.create_issue(title="New issue", body="Body")
    assert result["number"] == 99
    assert result["title"] == "New issue"


async def test_add_labels(github_client):
    mock_issue = MagicMock()
    github_client._repo.get_issue.return_value = mock_issue

    await github_client.add_labels(1, ["bug", "urgent"])
    assert mock_issue.add_to_labels.call_count == 2


async def test_remove_label(github_client):
    mock_issue = MagicMock()
    github_client._repo.get_issue.return_value = mock_issue

    await github_client.remove_label(1, "old-label")
    mock_issue.remove_from_labels.assert_called_once_with("old-label")


async def test_remove_label_not_present(github_client):
    mock_issue = MagicMock()
    mock_issue.remove_from_labels.side_effect = GithubException(
        404, {"message": "Label does not exist"}, None
    )
    github_client._repo.get_issue.return_value = mock_issue

    # Should not raise
    await github_client.remove_label(1, "nonexistent")


async def test_get_open_prs(github_client):
    pr1 = _make_mock_pr(number=10)
    pr2 = _make_mock_pr(number=11)
    github_client._repo.get_pulls.return_value = [pr1, pr2]

    result = await github_client.get_open_prs()
    assert len(result) == 2
    assert result[0]["number"] == 10


async def test_get_pr_files(github_client):
    mock_pr = MagicMock()
    mock_file = MagicMock()
    mock_file.filename = "src/main.py"
    mock_file.status = "modified"
    mock_file.additions = 10
    mock_file.deletions = 3
    mock_file.patch = "@@ -1 +1 @@\n-old\n+new"
    mock_pr.get_files.return_value = [mock_file]
    github_client._repo.get_pull.return_value = mock_pr

    result = await github_client.get_pr_files(10)
    assert len(result) == 1
    assert result[0]["filename"] == "src/main.py"
    assert result[0]["additions"] == 10


async def test_merge_pr(github_client):
    mock_pr = MagicMock()
    github_client._repo.get_pull.return_value = mock_pr

    await github_client.merge_pr(10)
    mock_pr.merge.assert_called_once_with(merge_method="squash")


async def test_delete_branch(github_client):
    mock_ref = MagicMock()
    github_client._repo.get_git_ref.return_value = mock_ref

    await github_client.delete_branch("feat/old")
    github_client._repo.get_git_ref.assert_called_once_with("heads/feat/old")
    mock_ref.delete.assert_called_once()


async def test_delete_branch_already_gone(github_client):
    github_client._repo.get_git_ref.side_effect = GithubException(
        404, {"message": "Not Found"}, None
    )
    # Should not raise
    await github_client.delete_branch("feat/gone")


async def test_get_file_content(github_client):
    mock_content = MagicMock()
    mock_content.decoded_content = b"# README\nHello"
    github_client._repo.get_contents.return_value = mock_content

    result = await github_client.get_file_content("README.md")
    assert result == "# README\nHello"


async def test_ensure_branch_protection_already_protected(github_client):
    mock_branch = MagicMock()
    mock_branch.protected = True
    github_client._repo.get_branch.return_value = mock_branch

    await github_client.ensure_branch_protection("main")
    mock_branch.edit_protection.assert_not_called()


async def test_ensure_branch_protection_not_protected(github_client):
    mock_branch = MagicMock()
    mock_branch.protected = False
    github_client._repo.get_branch.return_value = mock_branch

    await github_client.ensure_branch_protection("main", required_reviews=2)
    mock_branch.edit_protection.assert_called_once_with(
        required_approving_review_count=2,
        enforce_admins=False,
        dismiss_stale_reviews=True,
        require_code_owner_reviews=False,
    )
