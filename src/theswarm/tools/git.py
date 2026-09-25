"""Local git operations for the SWARM MVP Dev agent."""

from __future__ import annotations

import ast
import asyncio
import base64
import logging
import os

from theswarm.tools import github_app
import re
import shutil

log = logging.getLogger(__name__)

# Default committer identity for agent commits (matches the GIT_AUTHOR/
# COMMITTER values in docker-compose.yml). In containers there is no global
# git config, so `git commit` fails with rc=128 "Author identity unknown"
# unless the identity is supplied explicitly.
DEFAULT_GIT_USER_NAME = "TheSwarm Dev Agent"
DEFAULT_GIT_USER_EMAIL = "swarm-dev@jrec.fr"

# Hard cap on any single git command. Without it, a clone/push waiting on a
# credential prompt hangs forever — outside the cycle's phase timeouts.
GIT_COMMAND_TIMEOUT = 300


async def _run_git(
    *args: str,
    cwd: str | None = None,
    check: bool = True,
    timeout: float = GIT_COMMAND_TIMEOUT,
) -> str:
    """Run a git command and return stdout."""
    env = {
        **os.environ,
        # Never prompt for credentials or SSH host confirmation — fail instead.
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -oBatchMode=yes"),
    }
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        cwd=cwd,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(
            f"git {redact(' '.join(args))} timed out after {timeout:.0f}s"
        ) from None
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {redact(' '.join(args))} failed (rc={proc.returncode}): "
            f"{redact(stderr.decode())[:500]}"
        )
    return stdout.decode().strip()


_EXTRAHEADER_RE = re.compile(r"(extraheader=AUTHORIZATION: basic )\S+", re.IGNORECASE)


def redact(text: str) -> str:
    """Strip credentials from anything headed for a log or an exception."""
    cleaned = _EXTRAHEADER_RE.sub(r"\1***", text)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        cleaned = cleaned.replace(token, "***")
    return cleaned


def _identity_args() -> list[str]:
    """Explicit committer identity flags, overridable via env."""
    name = os.environ.get("SWARM_GIT_USER_NAME", DEFAULT_GIT_USER_NAME)
    email = os.environ.get("SWARM_GIT_USER_EMAIL", DEFAULT_GIT_USER_EMAIL)
    return ["-c", f"user.name={name}", "-c", f"user.email={email}"]


def _auth_args() -> list[str]:
    """GitHub credentials for network operations over HTTPS.

    Passed per command with ``-c`` rather than baked into the remote URL, so
    the token never lands in the workspace's ``.git/config`` where later
    commands (and anything else in the container) could read it back.

    Without this, ``git push`` has no credentials at all: it used to block on
    git's username prompt until the phase timeout killed it, which is why
    every April cycle opened zero PRs. With prompts disabled it now fails
    fast instead — this supplies the credentials it was always missing.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]


# What a cycle leaves in a workspace and must never commit: the target's
# venv (V2 M5), worktrees, test databases, coverage output. `commit_all`
# runs `git add -A` and `create_branch` runs `git clean -fd`; both honour
# .git/info/exclude, which is local to the clone and never pushed — the
# target's own .gitignore is not ours to edit. Closes the "runtime
# artifacts committed by git add -A" gap.
RUNTIME_EXCLUDES: tuple[str, ...] = (
    ".venv-swarm/",
    ".worktrees/",
    "test.db",
    "test.db-*",
    ".coverage",
    "coverage.json",
    "coverage.xml",
    "htmlcov/",
    ".pytest_cache/",
)
_EXCLUDE_MARKER = "# theswarm runtime artifacts"


def exclude_locally(workdir: str, patterns: tuple[str, ...] = RUNTIME_EXCLUDES) -> bool:
    """Add ``patterns`` to the clone's .git/info/exclude once.

    False without a .git, or when the file cannot be written — best effort:
    an exclusion that fails is a warning, never a clone that fails.
    """
    info_dir = os.path.join(workdir, ".git", "info")
    if not os.path.isdir(os.path.join(workdir, ".git")):
        return False
    try:
        os.makedirs(info_dir, exist_ok=True)
        path = os.path.join(info_dir, "exclude")
        existing = ""
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                existing = handle.read()
        present = {line.strip() for line in existing.splitlines()}
        missing = [pattern for pattern in patterns if pattern not in present]
        if not missing:
            return True
        with open(path, "a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(_EXCLUDE_MARKER + "\n" + "\n".join(missing) + "\n")
        return True
    except OSError as exc:
        log.warning("Could not write %s/.git/info/exclude: %s", workdir, exc)
        return False


async def clone_repo(repo_url: str, dest: str) -> str:
    """Clone a repo to dest. If dest already exists, pull instead."""
    await github_app.ensure_github_token()
    if os.path.isdir(os.path.join(dest, ".git")):
        log.info("Repo already cloned at %s — pulling latest", dest)
        await _run_git("checkout", "main", cwd=dest, check=False)
        await _run_git(*_auth_args(), "pull", "--ff-only", cwd=dest, check=False)
        exclude_locally(dest)
        return dest

    log.info("Cloning %s → %s", repo_url, dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    await _run_git(*_auth_args(), "clone", repo_url, dest)
    exclude_locally(dest)
    return dest


# ── One worktree per Dev task (V2 runtime, M5b) ─────────────────────────
#
# The clone's own checkout stays on main; each task gets
# `<clone>/.worktrees/<branch>` on its own branch, where Claude edits, the
# gate tests, and the commit and push happen. Two tasks in one clone used to
# reset and check out over each other (16f3b8af2cca vs 2878898cc504: two
# commits, no PR). `.worktrees/` is in the clone's .git/info/exclude, which
# every worktree shares, so no `git add -A` ever stages another task's tree.

WORKTREES_DIR = ".worktrees"

# Worktree bookkeeping (add, remove, prune) touches the clone's shared
# admin files: one at a time per clone, per event loop.
_worktree_locks: dict[tuple[int, str], asyncio.Lock] = {}


def dev_parallelism() -> int:
    """How many Dev tasks one iteration runs at once (M5b); 1 = one at a time.

    `SWARM_DEV_PARALLELISM`. Above 1 each task worktree gets its own venv:
    an editable install into a shared one would make one task test the
    other's code.
    """
    try:
        return max(1, int(os.environ.get("SWARM_DEV_PARALLELISM", "1")))
    except ValueError:
        return 1


def workspace_root(path: str) -> str:
    """The clone a task worktree belongs to; any other path is its own root."""
    marker = os.sep + WORKTREES_DIR + os.sep
    return path.split(marker, 1)[0] if marker in path else path


def worktree_path(workspace: str, branch_name: str) -> str:
    """Where the worktree of `branch_name` lives under its clone."""
    return os.path.join(workspace_root(workspace), WORKTREES_DIR, branch_name.replace("/", "--"))


def _worktree_lock(root: str) -> asyncio.Lock:
    key = (id(asyncio.get_running_loop()), root)
    lock = _worktree_locks.get(key)
    if lock is None:
        lock = _worktree_locks[key] = asyncio.Lock()
    return lock


async def _drop_worktrees_of(root: str, branch_name: str, path: str) -> None:
    """Remove whatever worktree holds `branch_name` or sits at `path`.

    A crash, a timeout or a resumed cycle can leave one behind, and git
    refuses a second checkout of a branch ("already checked out at ...").
    """
    listing = await _run_git("worktree", "list", "--porcelain", cwd=root, check=False)
    held: list[str] = []
    current = ""
    for line in listing.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree "):].strip()
        elif line.strip() == f"branch refs/heads/{branch_name}" and current != root:
            held.append(current)
    for stale in {*held, path}:
        await _run_git("worktree", "remove", "--force", stale, cwd=root, check=False)
        if os.path.isdir(stale) and stale != root and workspace_root(stale) == root:
            shutil.rmtree(stale, ignore_errors=True)
    await _run_git("worktree", "prune", cwd=root, check=False)


async def add_worktree(workspace: str, branch_name: str, *, resume: bool = False) -> str:
    """Give one task its own worktree on `branch_name`; return its path.

    Fresh: the branch starts at main as just pulled, like `create_branch`.
    Resume: at the remote branch a review sent back (#121), like
    `resume_branch` -- and fresh when that branch is gone from origin.
    """
    root = workspace_root(workspace)
    path = worktree_path(root, branch_name)
    await github_app.ensure_github_token()
    async with _worktree_lock(root):
        await _drop_worktrees_of(root, branch_name, path)
        start = "main"
        if resume:
            remote = await _run_git(
                *_auth_args(), "ls-remote", "--heads", "origin", branch_name,
                cwd=root, check=False,
            )
            if remote.strip():
                await _run_git(*_auth_args(), "fetch", "origin", branch_name, cwd=root)
                start = "FETCH_HEAD"
            else:
                log.warning("Branch %s is gone from origin -- starting fresh", branch_name)
        if start == "main":
            # The clone's own checkout is only ever main in this mode; a
            # clone left on a task branch by the older in-place flow is put
            # back first, or the pull would advance that branch instead.
            await _run_git("reset", "--hard", cwd=root, check=False)
            await _run_git("checkout", "main", cwd=root, check=False)
            await _run_git(*_auth_args(), "pull", "--ff-only", cwd=root, check=False)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        await _run_git("worktree", "add", "-B", branch_name, path, start, cwd=root)
    log.info("Worktree for %s at %s (from %s)", branch_name, path, start)
    return path


async def merge_main(workdir: str) -> list[str]:
    """Merge the latest origin/main into the checked-out branch.

    Returns the files left in conflict ([] when the merge went through, a
    merge commit made). A sibling PR merged first leaves this one
    unmergeable (#325 in cycle 9d3174f41829, two tasks side by side on the
    same files): the Dev merges main into its branch here, then resolves
    what git could not. A later `commit_all` concludes the merge.
    """
    await github_app.ensure_github_token()
    await _run_git(*_auth_args(), "fetch", "origin", "main", cwd=workdir, check=False)
    try:
        await _run_git(*_identity_args(), "merge", "--no-edit", "origin/main", cwd=workdir)
        log.info("Merged origin/main into %s cleanly", workdir)
        return []
    except RuntimeError:
        conflicted = await _run_git(
            "diff", "--name-only", "--diff-filter=U", cwd=workdir, check=False,
        )
        files = [line.strip() for line in conflicted.splitlines() if line.strip()]
        if not files:
            raise  # not a conflict: an ordinary failure, surfaced as such
        log.info("Merging origin/main left %d file(s) in conflict: %s", len(files), files)
        return files


async def remove_worktree(path: str) -> None:
    """Retire a task worktree; its branch stays. A clone root is left alone."""
    root = workspace_root(path)
    if root == path:
        return
    async with _worktree_lock(root):
        await _run_git("worktree", "remove", "--force", path, cwd=root, check=False)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        await _run_git("worktree", "prune", cwd=root, check=False)
    log.info("Removed worktree %s", path)


async def prune_worktrees(workspace: str) -> int:
    """Retire every task worktree of a clone -- the end of a dev loop.

    Returns how many were removed. Branches stay; only the checkouts go.
    """
    root = workspace_root(workspace)
    base = os.path.join(root, WORKTREES_DIR)
    if not os.path.isdir(base):
        return 0
    names = sorted(os.listdir(base))
    for name in names:
        await remove_worktree(os.path.join(base, name))
    return len(names)


async def create_branch(workdir: str, branch_name: str, base: str = "main") -> None:
    """Create (or reset) a branch at the tip of base and check it out.

    ``-B`` rather than ``-b``: the workspace is reused across dev iterations,
    so a retried task derives the same branch name and ``-b`` fails with
    rc=128 'a branch named X already exists'. Pinning a cycle to one issue
    made that permanent — every retry rebuilt the same name and burned the
    iteration (prod cycle 89c42c25875a). Each attempt wants a clean branch
    off base anyway, which is exactly what resetting gives.
    """
    await github_app.ensure_github_token()
    # The workspace is reused across iterations, so a half-finished attempt
    # leaves modified files behind and `git checkout main` then refuses with
    # "Your local changes would be overwritten". That is not recoverable on
    # its own: every later iteration hits the same wall, so one bad attempt
    # burned the whole Dev phase and the cycle opened no PR at all (prod
    # cycle 6ecb297eae40 — five iterations, five identical failures).
    # Discarding is safe precisely because the next line resets the branch to
    # `base`: anything uncommitted here is either already pushed or is debris.
    # `clean -fd` honours .gitignore, so the venv and caches survive.
    await _run_git("reset", "--hard", cwd=workdir, check=False)
    await _run_git("clean", "-fd", cwd=workdir, check=False)
    await _run_git("checkout", base, cwd=workdir)
    await _run_git(*_auth_args(), "pull", "--ff-only", cwd=workdir, check=False)
    await _run_git("checkout", "-B", branch_name, cwd=workdir)
    log.info("Created branch %s from %s", branch_name, base)


async def resume_branch(workdir: str, branch_name: str) -> None:
    """Check out the remote branch of a previous attempt, as it stands.

    A task sent back by a REQUEST_CHANGES review must build on the commits
    the review is about (#121). `create_branch` resets from main, which
    would throw them away and hand the reviewer the same diff minus its
    history. If the remote branch is gone — someone deleted it, the PR was
    closed and pruned — fall back to a fresh branch off main.
    """
    await github_app.ensure_github_token()
    await _run_git("reset", "--hard", cwd=workdir, check=False)
    await _run_git("clean", "-fd", cwd=workdir, check=False)
    remote = await _run_git(
        *_auth_args(), "ls-remote", "--heads", "origin", branch_name,
        cwd=workdir, check=False,
    )
    if not remote.strip():
        log.warning("Branch %s is gone from origin — starting fresh", branch_name)
        await create_branch(workdir, branch_name)
        return
    await _run_git(*_auth_args(), "fetch", "origin", branch_name, cwd=workdir)
    await _run_git("checkout", "-B", branch_name, "FETCH_HEAD", cwd=workdir)
    log.info("Resumed branch %s from origin", branch_name)


class BrokenSyntax(RuntimeError):
    """A staged file does not parse. Committing it would ship a broken tree."""


def _python_syntax_errors(workdir: str, rel_paths: list[str]) -> list[str]:
    """Parse every staged Python file; return one message per broken file."""
    errors: list[str] = []
    for rel in rel_paths:
        if not rel.endswith(".py"):
            continue
        full = os.path.join(workdir, rel)
        if not os.path.isfile(full):
            continue  # deleted or renamed away
        try:
            source = open(full, encoding="utf-8", errors="replace").read()
            ast.parse(source, filename=rel)
        except SyntaxError as exc:
            errors.append(f"{rel}:{exc.lineno or '?'}: {exc.msg}")
    return errors


async def commit_all(workdir: str, message: str) -> bool:
    """Stage all changes and commit. Returns True if there was something to commit."""
    await _run_git("add", "-A", cwd=workdir)

    # Check if there's anything to commit
    status = await _run_git("status", "--porcelain", cwd=workdir)
    if not status:
        log.info("Nothing to commit")
        return False

    # Refuse to commit a tree that does not parse. The Dev agent writes whole
    # files, and a truncated write is silent: asked only to add a test, it
    # rewrote agents/dev.py as +1 -381 with an unterminated string literal
    # (theswarm PR #74). Thirteen test modules stopped collecting and only CI
    # caught it — and when the agent is editing its own source, the file it
    # breaks is the one doing the writing. Raising here requeues the task, so
    # the next attempt starts from a clean checkout instead of building on
    # top of the damage.
    staged = await _run_git("diff", "--cached", "--name-only", cwd=workdir)
    broken = _python_syntax_errors(workdir, staged.splitlines())
    if broken:
        raise BrokenSyntax(
            "refusing to commit: "
            + "; ".join(broken[:5])
            + (f" (+{len(broken) - 5} more)" if len(broken) > 5 else "")
        )

    try:
        await _run_git(*_identity_args(), "commit", "-m", message, cwd=workdir)
    except RuntimeError as exc:
        if "Author identity unknown" not in str(exc) and "user.email" not in str(exc):
            raise
        # The -c flags should make this unreachable; if git still refuses,
        # persist a repo-local identity and retry once.
        log.warning("No git identity in environment — setting repo-local fallback")
        name = os.environ.get("SWARM_GIT_USER_NAME", DEFAULT_GIT_USER_NAME)
        email = os.environ.get("SWARM_GIT_USER_EMAIL", DEFAULT_GIT_USER_EMAIL)
        await _run_git("config", "user.name", name, cwd=workdir)
        await _run_git("config", "user.email", email, cwd=workdir)
        await _run_git("commit", "-m", message, cwd=workdir)
    log.info("Committed: %s", message)
    return True


async def push_branch(workdir: str, branch_name: str) -> None:
    """Push the branch to origin, replacing a superseded attempt if one is there.

    The branch name is derived from the task, so a retried task pushes the
    same name as its previous attempt — whose PR was closed, but closing a
    PR does not delete its branch. `create_branch` rebuilt ours from main,
    the two share no history, and the push was refused: non-fast-forward,
    on both retried tasks of cycle 5f8f0f63f58c, with the good work sitting
    in a local commit nobody could see (#123).

    Fetch first so the lease knows what the remote holds, then force with
    the lease: a branch someone else moved since is still protected. A
    branch that does not exist remotely fetches nothing and pushes as before.
    """
    await github_app.ensure_github_token()
    await _run_git(*_auth_args(), "fetch", "origin", branch_name, cwd=workdir, check=False)
    await _run_git(
        *_auth_args(), "push", "-u", "--force-with-lease", "origin", branch_name,
        cwd=workdir,
    )
    log.info("Pushed branch %s", branch_name)


async def get_diff_stat(workdir: str) -> str:
    """Get a compact diff stat of current changes vs main."""
    return await _run_git("diff", "--stat", "main", cwd=workdir, check=False)


async def changed_files(workdir: str, base: str = "main") -> list[str]:
    """Repo-relative paths this branch changed against `base`.

    Committed or not, the same view `get_diff_stat` reports — so it sees
    work whoever committed it, including edits Claude made and committed
    itself.
    """
    out = await _run_git("diff", "--name-only", base, cwd=workdir, check=False)
    return [line.strip() for line in out.splitlines() if line.strip()]


async def cleanup_workspace(workdir: str) -> None:
    """Remove the workspace directory."""
    if os.path.isdir(workdir):
        shutil.rmtree(workdir)
        log.info("Cleaned up workspace: %s", workdir)
