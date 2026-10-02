"""The pages a cycle's feature lives on, read off its pull requests.

QA's video and screenshots walked the pages the target declares (the
dashboard and the homepage on concert-tour-app), whatever the feature
was: every demo looked the same. A feature is where its pull requests
touched the API: the GET routes a diff adds, or whose body a hunk lands
in, with the router's prefix and its path parameters filled in. Those
pages join the walk, and each PR's first page is its story's "after"
capture. Only GET here: a POST needs a body, and `qa_feature_calls`
has one written from the code and played.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# Read over the whole file, not a line: the path may sit on the line after
# the decorator (`@api_router.delete(` then `"/{concert_id}/lineup/…",`).
_ROUTE_RE = re.compile(
    r'^[ \t]*@(?P<router>\w+)\.(?P<method>get|post|put|patch|delete)\('
    r'\s*(?:path\s*=\s*)?["\'](?P<path>[^"\']*)["\']',
    re.MULTILINE,
)
_ROUTER_RE = re.compile(r'^(?P<name>\w+)\s*=\s*APIRouter\((?P<args>[^)]*)\)', re.MULTILINE)
_PREFIX_RE = re.compile(r'prefix\s*=\s*["\'](?P<prefix>[^"\']*)["\']')
_INCLUDE_RE = re.compile(
    r'include_router\(\s*(?:(?P<module>\w+)\.)?(?P<name>\w+)\s*(?:,[^)]*?prefix\s*=\s*["\'](?P<prefix>[^"\']*)["\'])?',
)
_HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@')
_PARAM_RE = re.compile(r"\{[^}]+\}")
_PARAM_VALUE = "1"


@dataclass(frozen=True)
class Route:
    router: str
    method: str
    path: str
    line: int  # 1-based, of the decorator


def routes_in(source: str) -> list[Route]:
    """Every route decorator in a router file, in order — its path on the
    decorator's line or further down. lineup-remove's DELETE
    (concert-tour-app#514) put it on the next line and was no route at all:
    its lines went to the GET route above, and the demo walked the lineup
    with nothing taken off it."""
    return [Route(m["router"], m["method"], m["path"], source.count("\n", 0, m.start()) + 1)
            for m in _ROUTE_RE.finditer(source)]


def _prefixes(source: str, module: str, main_source: str) -> dict[str, str]:
    """Router variable → URL prefix: its own `APIRouter(prefix=…)`, else the
    prefix `main.py` gave it at include time, else none."""
    prefixes: dict[str, str] = {}
    for match in _ROUTER_RE.finditer(source):
        prefix = _PREFIX_RE.search(match["args"])
        prefixes[match["name"]] = prefix["prefix"] if prefix else ""
    for match in _INCLUDE_RE.finditer(main_source or ""):
        if match["prefix"] and (match["module"] in (None, module)) and not prefixes.get(match["name"]):
            prefixes[match["name"]] = match["prefix"]
    return prefixes


def _touched_lines(patch: str) -> set[int]:
    """The post-image line numbers of the lines the patch *adds*.

    Not a hunk's context lines: the three above a new route belong to the
    route before it, and counting them made every addition drag its
    neighbour into the demo. Nor a blank line it adds: git puts the two
    between functions above a new route as often as below it.
    """
    lines: set[int] = set()
    number = 0
    for raw in (patch or "").splitlines():
        hunk = _HUNK_RE.match(raw)
        if hunk:
            number = int(hunk["start"])
            continue
        if raw.startswith("+"):
            if raw[1:].strip():
                lines.add(number)
            number += 1
        elif raw.startswith("-"):
            continue
        else:
            number += 1
    return lines


def touched_routes(patch: str, source: str, *, module: str = "", main_source: str = "") -> list[tuple[str, str]]:
    """(method, path template) of every route the patch adds or whose body
    it touches, the router's prefix included. A hunk belongs to the last
    route declared before it."""
    routes = routes_in(source)
    if not routes:
        return []
    prefixes = _prefixes(source, module, main_source)
    touched: list[tuple[str, str]] = []
    for line in sorted(_touched_lines(patch)):
        owner = None
        for route in routes:
            if route.line <= line:
                owner = route
            else:
                break
        if owner is None:
            continue
        found = (owner.method, prefixes.get(owner.router, "") + owner.path or "/")
        if found not in touched:
            touched.append(found)
    return touched


def touched_get_paths(patch: str, source: str, *, module: str = "", main_source: str = "") -> list[str]:
    """The GET routes the patch adds or whose body it touches, as URL paths,
    their path parameters filled with "1"."""
    touched: list[str] = []
    for method, template in touched_routes(patch, source, module=module, main_source=main_source):
        path = _PARAM_RE.sub(_PARAM_VALUE, template) or "/"
        if method == "get" and path not in touched:
            touched.append(path)
    return touched


def _is_router_file(entry: dict) -> bool:
    name = entry.get("filename") or ""
    patch = entry.get("patch") or ""
    return name.endswith(".py") and ("@router" in patch or "APIRouter" in patch or "/routers/" in name)


async def pages_per_pr(github, prs: list[dict]) -> dict[int, list[str]]:
    """PR number → the feature pages its diff touched, in order, each once."""
    pages: dict[int, list[str]] = {}
    for number, routes in (await routes_per_pr(github, prs)).items():
        found: list[str] = []
        for method, template in routes:
            path = _PARAM_RE.sub(_PARAM_VALUE, template) or "/"
            if method == "get" and path not in found:
                found.append(path)
        pages[number] = found
    return pages


async def routes_per_pr(github, prs: list[dict]) -> dict[int, list[tuple[str, str]]]:
    """PR number → (method, path template) of the routes its diff touched."""
    touched: dict[int, list[tuple[str, str]]] = {}
    for pr in prs:
        number, ref = pr.get("number"), pr.get("head_sha") or ""
        if not isinstance(number, int):
            continue
        try:
            files = await github.get_pr_files(number)
        except Exception as exc:  # noqa: BLE001 — a page is a courtesy, never a failed demo
            log.warning("QA: could not read PR #%s for its feature pages: %s", number, exc)
            continue
        main_source: str | None = None
        found: list[tuple[str, str]] = []
        for entry in files:
            if not _is_router_file(entry):
                continue
            module = entry["filename"].rsplit("/", 1)[-1].removesuffix(".py")
            try:
                source = await github.get_file_content(entry["filename"], ref=ref)
                # A router without a prefix of its own got one at include time.
                if main_source is None and not all(_prefixes(source, module, "").values()):
                    main_source = await _main_source(github, ref)
            except Exception as exc:  # noqa: BLE001
                log.warning("QA: could not read %s at %s: %s", entry.get("filename"), ref[:7], exc)
                continue
            for route in touched_routes(entry.get("patch") or "", source, module=module,
                                        main_source=main_source or ""):
                if route not in found:
                    found.append(route)
        touched[number] = found
    return touched


async def _main_source(github, ref: str) -> str:
    for candidate in ("src/main.py", "main.py", "app/main.py"):
        try:
            return await github.get_file_content(candidate, ref=ref)
        except Exception:  # noqa: BLE001
            continue
    return ""


def _label(number: int, path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
    slug = re.sub(r"^api_v\d+_", "", slug) or "root"
    return f"feature_pr_{number}_{slug}"


_LABEL_RE = re.compile(r"^feature_pr_(?P<pr>\d+)_")


def pr_of_label(label: str) -> int | None:
    """The PR a feature-page capture belongs to, read back off its label."""
    match = _LABEL_RE.match(label or "")
    return int(match["pr"]) if match else None


async def feature_pages(github, prs: list[dict]) -> list[tuple[str, str]]:
    """(path, label) for every feature page of the cycle, each path once."""
    pages: list[tuple[str, str]] = []
    seen: set[str] = set()
    for number, paths in (await pages_per_pr(github, prs)).items():
        for path in paths:
            if path not in seen:
                seen.add(path)
                pages.append((path, _label(number, path)))
    if pages:
        log.info("QA: %d feature page(s) from the cycle's PRs: %s", len(pages), ", ".join(p for p, _ in pages))
    return pages


def story_preview_urls(pages: dict[int, list[str]], *, port: int) -> dict[int, dict[str, str | None]]:
    """Each PR's first feature page on the demo server, as its story's
    "after" capture; there is no server running the code before, so no
    "before"."""
    return {
        number: {"before": None, "after": f"http://127.0.0.1:{port}{paths[0]}"}
        for number, paths in pages.items() if paths
    }


def feature_pages_gate(
    pages: list[tuple[str, str]] | tuple,
    statuses: dict[str, int | None],
    *,
    launch_error: str = "",
) -> dict:
    """QA's verdict on the feature's own pages, walked on the running target.

    A 5xx is a feature that crashes: `fail`, the page named. A 2xx on at
    least one page, and no 5xx, is `pass`. A 4xx proves nothing either way
    — path parameters are filled with "1" and that row may not exist in
    the demo's database — and neither does a page nobody could reach, so a
    walk with no 2xx is `not_run`.
    """
    if not pages:
        return {"status": "not_run", "pages": [], "reason": "the PRs add no GET route to walk"}
    walked = [{"path": path, "status": statuses.get(path)} for path, _ in pages]
    if launch_error and not any(p["status"] for p in walked):
        return {"status": "not_run", "pages": walked,
                "reason": f"the demo server did not start: {launch_error}"}
    crashed = [p for p in walked if isinstance(p["status"], int) and p["status"] >= 500]
    if crashed:
        return {"status": "fail", "pages": walked,
                "reason": "; ".join(f"{p['path']} answered {p['status']}" for p in crashed)}
    answered = [p for p in walked if isinstance(p["status"], int) and 200 <= p["status"] < 300]
    if not answered:
        return {"status": "not_run", "pages": walked,
                "reason": "no feature page answered 2xx: "
                          + ", ".join(f"{p['path']} {p['status'] or 'unreachable'}" for p in walked)}
    return {"status": "pass", "pages": walked,
            "reason": f"{len(answered)} of {len(walked)} feature page(s) answered 2xx"}


_FEATURE_TEST_RESULT_RE = re.compile(r"::(test_feature\w*)(?:\[[^\]]*\])?\s+(PASSED|FAILED|ERROR)\b")
_FEATURE_TEST_SUMMARY_RE = re.compile(r"^(FAILED|ERROR) \S+::(test_feature\w*)", re.MULTILINE)


def feature_e2e_gate(output: str) -> dict:
    """QA's verdict on the E2E tests of the feature delivered — the ones its
    file names `test_feature_*` — out of pytest's `-v` output.

    The rest of the file probes the whole API, written blind; a wrong guess
    there (a stale `?status=planning`, answered 422) says nothing about what
    the cycle built. Any feature test failing or erroring is `fail`; at
    least one passing and none failing is `pass`; none at all is `not_run`.
    """
    outcomes: dict[str, str] = {}
    for match in _FEATURE_TEST_RESULT_RE.finditer(output or ""):
        key = match.group(0).split("::", 1)[1].split()[0]
        outcomes[key] = match.group(2)
    for match in _FEATURE_TEST_SUMMARY_RE.finditer(output or ""):
        outcomes.setdefault(match.group(2), match.group(1))
        if outcomes.get(match.group(2)) == "PASSED":
            outcomes[match.group(2)] = match.group(1)
    failed = sorted(name for name, outcome in outcomes.items() if outcome in ("FAILED", "ERROR"))
    passed = [name for name, outcome in outcomes.items() if outcome == "PASSED"]
    if failed:
        return {"status": "fail", "passed": len(passed), "failed": len(failed),
                "reason": "failed: " + ", ".join(failed)}
    if passed:
        return {"status": "pass", "passed": len(passed), "failed": 0,
                "reason": f"{len(passed)} feature test(s) passed"}
    return {"status": "not_run", "passed": 0, "failed": 0,
            "reason": "the E2E file names no test_feature_* test"}
