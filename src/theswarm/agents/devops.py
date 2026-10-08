"""DevOps — the fifth persona (docs/plans/2026-10-v3-one-product.md, D1).

It owns the pipeline, not the code, and in D1 it only *reads*: the stack
the owner declared in `theswarm.yaml` (`stack:`), GitHub Actions (main's
head, the runners, the workflow runs, the last deploy), the hosts it can
reach over ssh (the CI slot, the disks), this process (its build, its
disk, Claude's walls) and the day's harness run. Every reader that fails
is a finding that says so — `unknown`, with the reason — never an
exception out of `gather`. Nothing here changes a machine: proposals
with the owner's approval are D3.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml

log = logging.getLogger(__name__)

OK, WARN, BAD, UNKNOWN = "ok", "warn", "bad", "unknown"
DEFAULT_STALE_MINUTES = 180
SSH_TIMEOUT_SECONDS = 20
GITHUB_TIMEOUT_SECONDS = 30
DISK_WARN_PERCENT = 85
DISK_BAD_PERCENT = 95
LOAD_WARN_PER_CORE = 1.0  # the 1-minute average over the cores
LOAD_BAD_PER_CORE = 2.0
FAILED_RUNS_HOURS = 24
RUN_LIMIT = 30


# ── What a check answers ─────────────────────────────────────────────


@dataclass(frozen=True)
class Finding:
    key: str
    label: str
    status: str
    detail: str = ""
    url: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OpsReport:
    findings: tuple[Finding, ...]
    read_at: datetime
    stack: str = ""
    took_s: float = 0.0
    facts: dict = field(default_factory=dict)  # what the words are made of: main_sha, build_sha (full)

    @property
    def status(self) -> str:
        """The worst finding's word: bad, then warn, then ok; unknown when nothing is known."""
        statuses = {f.status for f in self.findings}
        if BAD in statuses:
            return BAD
        if WARN in statuses:
            return WARN
        if OK in statuses:
            return OK
        return UNKNOWN

    @property
    def counts(self) -> dict[str, int]:
        return {s: sum(1 for f in self.findings if f.status == s) for s in (BAD, WARN, OK, UNKNOWN)}

    def as_dict(self) -> dict:
        return {
            "status": self.status, "stack": self.stack, "read_at": self.read_at.isoformat(),
            "took_s": round(self.took_s, 2), "counts": self.counts,
            "findings": [f.as_dict() for f in self.findings],
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── The stack, declared ──────────────────────────────────────────────


def load_stack(path: str | Path = "theswarm.yaml") -> dict:
    """The `stack:` section of theswarm.yaml, or {} — declared, never guessed."""
    try:
        data = yaml.safe_load(Path(path).read_text()) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        log.warning("DevOps: %s unreadable (%s)", path, exc)
        return {}
    stack = data.get("stack") if isinstance(data, dict) else None
    return stack if isinstance(stack, dict) else {}


def stack_summary(stack: dict) -> str:
    """One line naming the stack: the hosts, the CI, the registry, the deploy."""
    parts: list[str] = [h.get("name", "") for h in stack.get("hosts", []) or [] if h.get("name")]
    parts += [c.get("provider", "") for c in stack.get("ci", []) or [] if c.get("provider")]
    if stack.get("registry"):
        parts.append(str(stack["registry"]).split("/")[0])
    deploy = stack.get("deploy") or {}
    if deploy.get("method"):
        parts.append(str(deploy["method"]))
    return " · ".join(p for p in parts if p)


def self_repo(stack: dict) -> str:
    for ci in stack.get("ci", []) or []:
        if ci.get("repo"):
            return str(ci["repo"])
    return os.environ.get("SWARM_SELF_REPO", "")


# ── Pure checks ──────────────────────────────────────────────────────


def parse_owner(text: str) -> dict:
    """A CI slot's owner file (acquire.sh on jrec.fr): runner, repo, ISO time, container, kind."""
    lines = [line.strip() for line in (text or "").splitlines()]
    lines += [""] * (5 - len(lines))
    since = None
    if lines[2]:
        try:
            since = datetime.fromisoformat(lines[2].replace("Z", "+00:00"))
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
        except ValueError:
            since = None
    return {"runner": lines[0], "repo": lines[1], "since": since, "container": lines[3], "kind": lines[4]}


def _minutes(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() // 60))


def slot_finding(slots: list[tuple[str, str]], now: datetime | None = None,
                 stale_minutes: int = DEFAULT_STALE_MINUTES, host: str = "") -> Finding:
    """The CI slot (one server-wide slot since 2026-10-02): free, held, or stale.

    A slot held longer than the stale rule is what queued nine jobs for
    2.5 h on 2026-10-05 — it is `bad`, with who holds it and for how long.
    """
    now = now or _now()
    where = f" on {host}" if host else ""
    if not slots:
        return Finding("ci_slot", "CI slot", OK, f"free{where}")
    held = []
    stale = []
    for path, text in slots:
        owner = parse_owner(text)
        name = Path(path).parent.name or "slot"
        age = _minutes(now - owner["since"]) if owner["since"] else None
        who = owner["runner"] or "?"
        repo = f" ({owner['repo']})" if owner["repo"] else ""
        line = f"{name} held by {who}{repo}" + (f" for {age} min" if age is not None else "")
        held.append(line)
        if age is not None and age > stale_minutes:
            stale.append(line)
    if stale:
        return Finding("ci_slot", "CI slot", BAD,
                       f"stale: {'; '.join(stale)} — past the {stale_minutes} min rule, every job waits behind it{where}")
    return Finding("ci_slot", "CI slot", OK, "; ".join(held) + where)


def deploy_finding(main_sha: str, build_sha: str, run: dict | None, repo: str = "") -> Finding:
    """The last deploy: this build is main's head, or main moved and the deploy is pending or failed."""
    short_main = (main_sha or "")[:7]
    short_build = (build_sha or "")[:7]
    run_state = ""
    url = ""
    if run:
        url = run.get("html_url", "") or ""
        if run.get("status") != "completed":
            run_state = f"deploy run {run.get('status', '?')}"
        else:
            run_state = f"last deploy run {run.get('conclusion') or '?'}"
        if run.get("updated_at"):
            run_state += f" at {_clock(run['updated_at'])}"
    if not short_main:
        return Finding("deploy", "Last deploy", UNKNOWN, "main's head not read" + (f" ({run_state})" if run_state else ""), url)
    if not short_build:
        return Finding("deploy", "Last deploy", UNKNOWN,
                       f"this build does not know its commit (SWARM_BUILD_SHA unset); main is at {short_main}"
                       + (f"; {run_state}" if run_state else ""), url)
    if short_main == short_build:
        return Finding("deploy", "Last deploy", OK, f"this build is main's head {short_main}"
                       + (f"; {run_state}" if run_state else ""), url)
    # Main may be ahead of the build on commits the deploy ignores (the
    # harness's daily line, a demo film, a page of docs — `paths-ignore`):
    # no run exists for them, and the last run's head is this build.
    if run and run.get("status") == "completed" and str(run.get("head_sha") or "")[:7] == short_build:
        return Finding("deploy", "Last deploy", OK,
                       f"this build is the last deployed head {short_build}; main is at {short_main} on paths the deploy ignores"
                       + (f"; {run_state}" if run_state else ""), url)
    if run and run.get("status") != "completed":
        return Finding("deploy", "Last deploy", WARN, f"main is at {short_main}, this build is {short_build} — {run_state}", url)
    if run and run.get("conclusion") not in (None, "success"):
        return Finding("deploy", "Last deploy", BAD, f"main is at {short_main}, this build is {short_build} — {run_state}", url)
    return Finding("deploy", "Last deploy", WARN, f"main is at {short_main}, this build is {short_build}"
                   + (f"; {run_state}" if run_state else " — no deploy run seen"), url)


def runners_finding(runners: list[dict], wanted: list[str] | None = None) -> Finding:
    """The self-hosted runners GitHub knows for the repository."""
    if not runners:
        return Finding("runners", "Runners", BAD, "no self-hosted runner registered")
    offline = [r.get("name", "?") for r in runners if r.get("status") != "online"]
    busy = sum(1 for r in runners if r.get("busy"))
    if offline:
        return Finding("runners", "Runners", BAD,
                       f"{len(offline)} of {len(runners)} offline: {', '.join(offline)} — CI queues until it is back")
    return Finding("runners", "Runners", OK, f"{len(runners)} online, {busy} busy")


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _clock(value: Any) -> str:
    moment = _parse_time(value)
    return moment.astimezone(timezone.utc).strftime("%d %b %H:%M UTC").lstrip("0") if moment else str(value)


def failed_runs_finding(runs: list[dict], now: datetime | None = None, hours: int = FAILED_RUNS_HOURS) -> Finding:
    """Workflow runs that failed in the last day, by name and branch."""
    now = now or _now()
    since = now - timedelta(hours=hours)
    # A cancelled run on a branch is routine (a newer push superseded it);
    # on main it is a `tests` job past its cap (GitHub says "cancelled") —
    # unless a newer run of the same workflow on main replaced it: the
    # concurrency group keeps one pending run and cancels the one before.
    recent = [r for r in runs if (r.get("conclusion") in ("failure", "timed_out")
                                  or (r.get("conclusion") == "cancelled" and r.get("head_branch") == "main"
                                      and not _superseded(r, runs)))
              and (_parse_time(r.get("updated_at")) or since) >= since]
    if not recent:
        return Finding("failed_runs", "Workflow runs", OK, f"none failed in the last {hours} h")
    names = [f"{r.get('name', '?')} on {r.get('head_branch', '?')} ({r.get('conclusion')})" for r in recent[:4]]
    more = f" +{len(recent) - 4} more" if len(recent) > 4 else ""
    status = BAD if any(r.get("head_branch") == "main" and r.get("conclusion") == "failure" for r in recent) else WARN
    return Finding("failed_runs", "Workflow runs", status, f"{len(recent)} failed in the last {hours} h: {'; '.join(names)}{more}",
                   recent[0].get("html_url", "") or "")


def _superseded(run: dict, runs: list[dict]) -> bool:
    """A newer run of the same workflow on the same branch, created before this one was cancelled."""
    born = _parse_time(run.get("created_at"))
    ended = _parse_time(run.get("updated_at"))
    if born is None or ended is None:
        return False
    for other in runs:
        if other is run or other.get("head_branch") != run.get("head_branch") or other.get("path") != run.get("path"):
            continue
        other_born = _parse_time(other.get("created_at"))
        if other_born is not None and born < other_born <= ended:
            return True
    return False


def disk_finding(name: str, usages: list[dict], key: str = "disk") -> Finding:
    """Disks by fullness: warn past 85 %, bad past 95 %."""
    if not usages:
        return Finding(key, f"Disk ({name})", UNKNOWN, "not read")
    worst = max(usages, key=lambda u: u.get("percent", 0))
    parts = [f"{u.get('path', '?')} {u.get('percent', 0)}% used" + (f", {u['free']} free" if u.get("free") else "") for u in usages]
    percent = worst.get("percent", 0)
    status = BAD if percent >= DISK_BAD_PERCENT else WARN if percent >= DISK_WARN_PERCENT else OK
    return Finding(key, f"Disk ({name})", status, "; ".join(parts))


def load_finding(name: str, load: dict | None, key: str = "load") -> Finding:
    """The 1-minute load average against the cores: a box past 2× cannot even boot a container in time."""
    if not load or load.get("cores") in (None, 0) or load.get("one") is None:
        return Finding(key, f"Load ({name})", UNKNOWN, "not read")
    one, cores = float(load["one"]), int(load["cores"])
    per_core = one / cores
    detail = f"{one:.1f} over {cores} cores ({per_core:.1f} per core)"
    if load.get("five") is not None:
        detail += f", {float(load['five']):.1f} over 5 min"
    status = BAD if per_core >= LOAD_BAD_PER_CORE else WARN if per_core >= LOAD_WARN_PER_CORE else OK
    if status != OK:
        detail += " — a boot or a health probe may not make it in time"
    return Finding(key, f"Load ({name})", status, detail)


def claude_finding(status: dict | None) -> Finding:
    """Claude's walls, as /health and the rail read them."""
    if not status:
        return Finding("claude", "Claude", UNKNOWN, "not read")
    word = status.get("status", "unknown")
    detail = status.get("detail", "") or ""
    if word == "ok":
        return Finding("claude", "Claude", OK, "credentials and window fine")
    if word == "quota_wall":
        return Finding("claude", "Claude", BAD, f"subscription window closed{(' ' + detail) if detail else ''} — every cycle refuses until then")
    if word == "auth_expired":
        return Finding("claude", "Claude", BAD, "credentials expired — a person must renew them (claude setup-token, then redeploy)")
    return Finding("claude", "Claude", UNKNOWN, word)


HARNESS_GOOD = ("built", "passed", "already_delivered")


def _run_time(run: dict) -> datetime | None:
    """When an eval run was recorded: `timestamp` is what /api/evals/runs carries."""
    for key in ("timestamp", "recorded_at", "created_at", "started_at"):
        moment = _parse_time(run.get(key))
        if moment is not None:
            return moment
    return None


def harness_finding(runs: list[dict], today: date | None = None) -> Finding:
    """The day's harness run on the test bed, from the eval history (newest first,
    whatever order the store answers in)."""
    today = today or _now().date()
    floor = datetime.min.replace(tzinfo=timezone.utc)
    ordered = sorted(runs, key=lambda r: _run_time(r) or floor, reverse=True)
    todays = [r for r in ordered if (_run_time(r) or floor).date() == today]
    if not todays:
        latest = ordered[0] if ordered else None
        if latest is None:
            return Finding("harness", "Harness", UNKNOWN, "no eval run recorded")
        when = _clock(_run_time(latest) or "")
        return Finding("harness", "Harness", WARN, f"no run today (07:00 UTC); the last one {when}: {latest.get('feature', '?')} — {latest.get('outcome') or ('passed' if latest.get('passed') else 'failed')}")
    run = todays[0]
    outcome = run.get("outcome") or ("passed" if run.get("passed") else "failed")
    behaviour = run.get("behaviour") or ""
    status = OK if outcome in HARNESS_GOOD and behaviour != "broken" else BAD if outcome == "failed" or behaviour == "broken" else WARN
    cost = f", ${float(run['cost_usd']):.2f}" if run.get("cost_usd") not in (None, "") else ""
    return Finding("harness", "Harness", status, f"today: {run.get('feature', '?')} — {outcome}" + (f", {behaviour}" if behaviour else "") + cost)


# ── Readers (the I/O) ────────────────────────────────────────────────


def build_sha() -> str:
    """This build's commit: the deploy's tag in prod (SWARM_BUILD_SHA), a checkout's HEAD on a laptop."""
    sha = os.environ.get("SWARM_BUILD_SHA", "").strip()
    if sha:
        return sha
    root = Path(__file__).resolve().parents[3]
    if not (root / ".git").exists():
        return ""
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _existing(path: str) -> str:
    """The path, or its nearest ancestor that exists (a workspace directory not made yet)."""
    current = Path(path).expanduser()
    while not current.exists() and current != current.parent:
        current = current.parent
    return str(current)


def local_disk(paths: list[str] | None = None) -> list[dict]:
    """This process's disk: the workspaces' volume (or the home), one row per mount."""
    rows = []
    for path in paths or [os.environ.get("SWARM_WORKSPACE_DIR") or os.path.expanduser("~")]:
        probe = _existing(path)
        try:
            usage = shutil.disk_usage(probe)
        except OSError:
            continue
        rows.append({"path": probe, "percent": int(round(100 * usage.used / usage.total)) if usage.total else 0,
                     "free": _human(usage.free)})
    return rows


def local_load() -> dict | None:
    """This box's load average and cores (None where the OS has no such thing)."""
    try:
        one, five, fifteen = os.getloadavg()
    except (AttributeError, OSError):
        return None
    return {"one": one, "five": five, "fifteen": fifteen, "cores": os.cpu_count() or 1}


def _human(n: float) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K", "M") else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}T"


def _run_dict(run) -> dict:
    return {
        "id": getattr(run, "id", None), "name": getattr(run, "name", ""), "status": getattr(run, "status", ""),
        "conclusion": getattr(run, "conclusion", None), "head_sha": getattr(run, "head_sha", ""),
        "head_branch": getattr(run, "head_branch", ""), "event": getattr(run, "event", ""),
        "updated_at": getattr(run, "updated_at", None), "created_at": getattr(run, "created_at", None),
        "html_url": getattr(run, "html_url", ""),
        "path": getattr(run, "path", ""),
    }


def _runner_labels(runner) -> list[str]:
    """PyGithub answers the labels as a list of dicts (a method in older releases)."""
    labels = getattr(runner, "labels", None)
    if callable(labels):
        labels = labels()
    return [l.get("name", "") if isinstance(l, dict) else str(getattr(l, "name", l)) for l in (labels or [])]


DEVOPS_BRANCH_PREFIX = "devops/"  # the branches DevOps's improvement PRs (D4) are on


def _read_github_sync(repo_name: str, token: str, deploy_workflow: str = "ci.yml") -> dict:
    from github import Github

    repo = Github(token, timeout=GITHUB_TIMEOUT_SECONDS).get_repo(repo_name)
    out: dict[str, Any] = {"main_sha": repo.get_branch(repo.default_branch).commit.sha}
    try:
        out["runners"] = [{"name": r.name, "status": r.status, "busy": r.busy, "labels": _runner_labels(r)}
                          for r in repo.get_self_hosted_runners()]
    except Exception as exc:  # noqa: BLE001 — the token may not administer the repo
        out["runners_error"] = str(exc)[:200]
    runs = []
    objects = []
    for run in repo.get_workflow_runs():
        runs.append(_run_dict(run))
        objects.append(run)
        if len(runs) >= RUN_LIMIT:
            break
    out["runs"] = runs
    try:
        out["jobs"] = _jobs_of(objects, runs, repo.default_branch, deploy_workflow)
    except Exception as exc:  # noqa: BLE001 — the measures are not worth losing the rest
        out["jobs_error"] = str(exc)[:200]
    try:
        out["devops_prs"] = [{"number": pr.number, "title": pr.title, "html_url": pr.html_url, "head": pr.head.ref}
                             for pr in repo.get_pulls(state="open") if str(pr.head.ref).startswith(DEVOPS_BRANCH_PREFIX)]
    except Exception as exc:  # noqa: BLE001
        out["devops_prs_error"] = str(exc)[:200]
    return out


def _jobs_of(objects: list, runs: list[dict], default_branch: str, workflow: str) -> list[dict]:
    """The jobs of the last completed runs of the deploy workflow on the default branch (D4's measures)."""
    from theswarm.agents.devops_measures import JOB_RUN_LIMIT, job_dict

    jobs: list[dict] = []
    read = 0
    for run, row in zip(objects, runs):
        path = str(row.get("path", ""))
        if row.get("head_branch") != default_branch or row.get("status") != "completed" or not (path.endswith("/" + workflow) or path == workflow):
            continue
        jobs.extend(job_dict(job, row.get("id")) for job in run.jobs())
        read += 1
        if read >= JOB_RUN_LIMIT:
            break
    return jobs


async def read_github(repo_name: str, token: str = "", deploy_workflow: str = "ci.yml") -> dict:
    """main's head, the runners and the last workflow runs, off the API in a thread."""
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not repo_name:
        raise ValueError("no repository declared in stack.ci")
    if not token:
        raise ValueError("GITHUB_TOKEN is not set")
    return await asyncio.wait_for(asyncio.to_thread(_read_github_sync, repo_name, token, deploy_workflow), GITHUB_TIMEOUT_SECONDS + 5)


def deploy_run_of(runs: list[dict], workflow: str = "ci.yml", branch: str = "main") -> dict | None:
    """The latest run of the deploy workflow on the deployed branch, by its path.

    On this repository the deploy is a job of the CI run on main (`cd.yml`
    is `workflow_call`ed from `ci.yml`): the run to read is ci.yml's.
    """
    for run in runs:
        path = str(run.get("path", ""))
        if (path.endswith("/" + workflow) or path == workflow) and (not branch or run.get("head_branch") == branch):
            return run
    return None


def ssh_command(host: dict) -> list[str]:
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={SSH_TIMEOUT_SECONDS}", "-o", "StrictHostKeyChecking=accept-new"]
    if host.get("port"):
        cmd += ["-p", str(host["port"])]
    return cmd + [str(host.get("ssh", ""))]


HOST_SCRIPT = (
    'for f in {slot_dir}/slot*/owner; do [ -f "$f" ] && echo "SLOT $f" && cat "$f" && echo "ENDSLOT"; done; '
    'echo "DISK"; df -P {disk_paths} 2>/dev/null; '
    'echo "LOAD $(cat /proc/loadavg 2>/dev/null | cut -d" " -f1-3) $(nproc 2>/dev/null)"'
)


async def run_ssh(host: dict, script: str) -> str:
    """One read-only script over ssh, with the ambient keys; the output or an error."""
    proc = await asyncio.create_subprocess_exec(
        *ssh_command(host), script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), SSH_TIMEOUT_SECONDS + 10)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"ssh to {host.get('name') or host.get('ssh')} timed out")
    if proc.returncode != 0:
        raise RuntimeError((err.decode(errors="replace").strip() or f"ssh exited {proc.returncode}")[:200])
    return out.decode(errors="replace")


def parse_host_output(text: str) -> dict:
    """SLOT/ENDSLOT blocks and the df -P table out of the host script's output."""
    slots: list[tuple[str, str]] = []
    disks: list[dict] = []
    load: dict | None = None
    current: str | None = None
    buffer: list[str] = []
    in_disk = False
    for line in text.splitlines():
        if line.startswith("SLOT "):
            current, buffer = line[5:].strip(), []
        elif line == "ENDSLOT" and current is not None:
            slots.append((current, "\n".join(buffer)))
            current = None
        elif current is not None:
            buffer.append(line)
        elif line.startswith("LOAD "):
            in_disk = False
            parts = line.split()[1:]
            if len(parts) >= 4:
                try:
                    load = {"one": float(parts[0]), "five": float(parts[1]), "fifteen": float(parts[2]), "cores": int(parts[3])}
                except ValueError:
                    load = None
        elif line == "DISK":
            in_disk = True
        elif in_disk:
            parts = line.split()
            if len(parts) >= 6 and parts[4].endswith("%") and parts[5] not in {d["path"] for d in disks}:
                try:  # one line per mount: df repeats a filesystem for every path asked on it
                    disks.append({"path": parts[5], "percent": int(parts[4].rstrip("%")), "free": _human(int(parts[3]) * 1024)})
                except ValueError:
                    continue
    return {"slots": slots, "disks": disks, "load": load}


async def run_local(host: dict, script: str) -> str:
    """The same read-only script on this box (a host declared `local: true`)."""
    proc = await asyncio.create_subprocess_shell(script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), SSH_TIMEOUT_SECONDS + 10)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("the local script timed out")
    if proc.returncode != 0:
        raise RuntimeError((err.decode(errors="replace").strip() or f"exited {proc.returncode}")[:200])
    return out.decode(errors="replace")


async def run_host(host: dict, script: str) -> str:
    """A script on a host: over ssh, or in a local shell when the host is this box."""
    return await (run_local if host.get("local") else run_ssh)(host, script)


async def read_host(host: dict, run: Callable[[dict, str], Awaitable[str]] | None = None) -> dict:
    slot_dir = host.get("ci_slot_dir", "")
    paths = " ".join(host.get("disk_paths") or ["/"])
    script = HOST_SCRIPT.format(slot_dir=slot_dir or "/nonexistent", disk_paths=paths)
    return parse_host_output(await (run or run_host)(host, script))


# ── Gather ───────────────────────────────────────────────────────────


def _unknown(key: str, label: str, exc: BaseException) -> Finding:
    return Finding(key, label, UNKNOWN, f"not read: {str(exc)[:160] or exc.__class__.__name__}")


async def gather(stack: dict, *, github: Callable[[str], Awaitable[dict]] | None = None,
                 host_reader: Callable[[dict], Awaitable[dict]] | None = None,
                 claude: Callable[[], dict] | None = None,
                 harness: Callable[[str], Awaitable[list[dict]]] | None = None,
                 build: Callable[[], str] | None = None, here: Callable[[], list[dict]] | None = None,
                 load: Callable[[], dict | None] | None = None,
                 now: datetime | None = None) -> OpsReport:
    """Every check, each on its own; a reader that fails is an unknown finding."""
    started = _now()
    now = now or started
    findings: list[Finding] = []
    facts: dict = {}
    repo = self_repo(stack)
    deploy_cfg = stack.get("deploy") or {}
    workflow = next((c.get("deploy_workflow") for c in stack.get("ci", []) or [] if c.get("deploy_workflow")), "ci.yml")

    # GitHub: main's head, the deploy run, the runners, the failed runs.
    gh: dict = {}
    try:
        gh = await (github or read_github)(repo) if github is not None else await read_github(repo, deploy_workflow=workflow)
    except Exception as exc:  # noqa: BLE001
        findings += [_unknown("deploy", "Last deploy", exc), _unknown("runners", "Runners", exc), _unknown("failed_runs", "Workflow runs", exc)]
    else:
        runs = gh.get("runs") or []
        try:
            this_build = (build or build_sha)()
        except Exception:  # noqa: BLE001
            this_build = ""
        findings.append(deploy_finding(gh.get("main_sha", ""), this_build, deploy_run_of(runs, workflow), repo))
        facts.update(main_sha=gh.get("main_sha", "") or "", build_sha=this_build or "")
        if "runners" in gh:
            findings.append(runners_finding(gh["runners"]))
        else:
            findings.append(Finding("runners", "Runners", UNKNOWN, f"not read: {gh.get('runners_error', 'no answer')}"))
        findings.append(failed_runs_finding(runs, now))

    # The hosts, over ssh when a key is at hand (the laptop today; prod needs one mounted).
    for host in stack.get("hosts", []) or []:
        name = host.get("name") or host.get("ssh") or "host"
        try:
            read = await (host_reader or read_host)(host)
        except Exception as exc:  # noqa: BLE001
            findings.append(Finding("ci_slot", "CI slot", UNKNOWN, f"{name} not reachable from here: {str(exc)[:120]}"))
            continue
        if host.get("ci_slot_dir"):
            findings.append(slot_finding(read.get("slots", []), now, int(host.get("ci_slot_stale_minutes") or DEFAULT_STALE_MINUTES), name))
        findings.append(disk_finding(name, read.get("disks", []), key=f"disk_{name}"))
        findings.append(load_finding(name, read.get("load"), key=f"load_{name}"))

    # This process: its box's load, its disk, Claude's walls.
    findings.append(load_finding("here", (load or local_load)(), key="load_here"))
    try:
        findings.append(disk_finding("here", (here or local_disk)(), key="disk_here"))
    except Exception as exc:  # noqa: BLE001
        findings.append(_unknown("disk_here", "Disk (here)", exc))
    try:
        findings.append(claude_finding((claude or _claude_status)()))
    except Exception as exc:  # noqa: BLE001
        findings.append(_unknown("claude", "Claude", exc))

    # The day's harness run on the test bed.
    target = str((stack.get("harness") or {}).get("repo") or "")
    records: list[dict] = []
    if harness is not None and target:
        try:
            records = list(await harness(target))
            findings.append(harness_finding(records, now.date()))
        except Exception as exc:  # noqa: BLE001
            findings.append(_unknown("harness", "Harness", exc))

    # D4 — what DevOps measures: the CI's pace per job, the cycle's price.
    if isinstance(gh_jobs := (gh.get("jobs") if isinstance(gh, dict) else None), list):
        from theswarm.agents.devops_measures import ci_measures, cycle_measure, measures_facts, measures_finding

        jobs = ci_measures(gh_jobs)
        cycle = cycle_measure(records)
        findings.append(measures_finding(jobs, cycle))
        facts["measures"] = measures_facts(jobs, cycle)
    if isinstance(gh, dict) and isinstance(gh.get("devops_prs"), list):
        facts["devops_prs"] = gh["devops_prs"]
    return OpsReport(tuple(findings), read_at=now, stack=stack_summary(stack),
                     took_s=(_now() - started).total_seconds(), facts=facts)


def _claude_status() -> dict:
    from theswarm.presentation.web.shell import claude_status

    return claude_status()


# ── The preflight (D2): go or no-go before a cycle starts ────────────


# What stops a cycle before it starts: a finding that would make it die
# or lie. A warning never stops it; an unknown never does either — the
# cycle's own checks (repo access, credentials) still run.
NO_GO_KEYS = ("claude", "disk_here", "runners", "ci_slot")


@dataclass(frozen=True)
class Preflight:
    go: bool
    reasons: tuple[str, ...]
    report: OpsReport

    @property
    def word(self) -> str:
        return "go" if self.go else "no-go: " + "; ".join(self.reasons)

    def as_dict(self) -> dict:
        return {"go": self.go, "reasons": list(self.reasons), "word": self.word, **self.report.as_dict()}


def preflight_of(report: OpsReport) -> Preflight:
    """The go/no-go a report answers: a bad Claude, a full disk here, no
    runner, a stale CI slot stop a cycle before it is spent on them."""
    reasons = tuple(f"{f.label}: {f.detail}" for f in report.findings if f.key in NO_GO_KEYS and f.status == BAD)
    return Preflight(go=not reasons, reasons=reasons, report=report)


# ── The deploy watch (D2): did the last merge land? ──────────────────


DEPLOY_WATCH_MINUTES = 45


def deploy_watch_finding(main_sha: str, build_sha: str, run: dict | None, main_since: datetime | None,
                         now: datetime | None = None, minutes: int = DEPLOY_WATCH_MINUTES) -> Finding | None:
    """A deploy that failed, or main that moved and did not reach the box in
    `minutes`: the alert D2 raises after every merge. None while it is fine."""
    now = now or _now()
    short_main, short_build = (main_sha or "")[:7], (build_sha or "")[:7]
    if not short_main or not short_build or short_main == short_build:
        return None
    url = (run or {}).get("html_url", "") or ""
    if run and run.get("status") == "completed" and run.get("conclusion") not in (None, "success"):
        return Finding("deploy_watch", "Deploy watch", BAD,
                       f"the deploy of {short_main} failed ({run.get('conclusion')}); this box still runs {short_build}", url)
    waited = _minutes(now - main_since) if main_since else 0
    if waited >= minutes:
        return Finding("deploy_watch", "Deploy watch", BAD,
                       f"main moved to {short_main} {waited} min ago and this box still runs {short_build} — the deploy did not land", url)
    return None


# ── The report, in words ─────────────────────────────────────────────


ICONS = {OK: "✅", WARN: "⚠️", BAD: "🔴", UNKNOWN: "◌"}
HEADLINES = {OK: "the pipeline is fine", WARN: "something to look at", BAD: "something is wrong", UNKNOWN: "nothing could be read"}


def format_report(report: OpsReport, title: str = "DevOps — daily report") -> str:
    """The daily report as Mattermost markdown (and the CLI's words)."""
    lines = [f"### {title}", f"{ICONS[report.status]} **{HEADLINES[report.status]}** — {report.stack or 'no stack declared'}, "
             f"read {report.read_at.astimezone(timezone.utc).strftime('%d %b %H:%M UTC').lstrip('0')}", ""]
    for f in report.findings:
        link = f" [↗]({f.url})" if f.url else ""
        lines.append(f"- {ICONS.get(f.status, '◌')} **{f.label}** — {f.detail}{link}")
    return "\n".join(lines)
