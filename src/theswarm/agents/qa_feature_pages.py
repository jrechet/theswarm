"""The pages a cycle's feature lives on, read off its pull requests.

QA's video and screenshots walked the pages the target declares (the
dashboard and the homepage on concert-tour-app), whatever the feature
was: every demo looked the same. A feature is where its pull requests
touched the API: the GET routes a diff adds, or whose body a hunk lands
in, with the router's prefix and its path parameters filled in. Those
pages join the walk, and each PR's first page is its story's "after"
capture. Only GET: a POST needs a body nobody can invent.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

_ROUTE_RE = re.compile(
    r'^\s*@(?P<router>\w+)\.(?P<method>get|post|put|patch|delete)\(\s*["\'](?P<path>[^"\']*)["\']',
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
    """Every route decorator in a router file, in order."""
    routes: list[Route] = []
    for number, line in enumerate(source.splitlines(), start=1):
        match = _ROUTE_RE.match(line)
        if match:
            routes.append(Route(match["router"], match["method"], match["path"], number))
    return routes


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
    neighbour into the demo.
    """
    lines: set[int] = set()
    number = 0
    for raw in (patch or "").splitlines():
        hunk = _HUNK_RE.match(raw)
        if hunk:
            number = int(hunk["start"])
            continue
        if raw.startswith("+"):
            lines.add(number)
            number += 1
        elif raw.startswith("-"):
            continue
        else:
            number += 1
    return lines


def touched_get_paths(patch: str, source: str, *, module: str = "", main_source: str = "") -> list[str]:
    """The GET routes the patch adds or whose body it touches, as URL paths.

    A hunk belongs to the last route declared before it; the route's path
    parameters are filled with "1".
    """
    routes = routes_in(source)
    if not routes:
        return []
    prefixes = _prefixes(source, module, main_source)
    touched: list[str] = []
    for line in sorted(_touched_lines(patch)):
        owner = None
        for route in routes:
            if route.line <= line:
                owner = route
            else:
                break
        if owner is None or owner.method != "get":
            continue
        path = prefixes.get(owner.router, "") + owner.path
        path = _PARAM_RE.sub(_PARAM_VALUE, path) or "/"
        if path not in touched:
            touched.append(path)
    return touched


def _is_router_file(entry: dict) -> bool:
    name = entry.get("filename") or ""
    patch = entry.get("patch") or ""
    return name.endswith(".py") and ("@router" in patch or "APIRouter" in patch or "/routers/" in name)


async def pages_per_pr(github, prs: list[dict]) -> dict[int, list[str]]:
    """PR number → the feature pages its diff touched, in order, each once."""
    pages: dict[int, list[str]] = {}
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
        found: list[str] = []
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
            for path in touched_get_paths(entry.get("patch") or "", source, module=module,
                                          main_source=main_source or ""):
                if path not in found:
                    found.append(path)
        pages[number] = found
    return pages


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
