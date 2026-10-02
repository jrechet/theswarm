"""A feature's own requests, played on the running demo.

The demo walks GET pages (`qa_feature_pages`). A feature that adds only a
POST had nothing to walk: sell-tickets (cycle 68fd55bf81e5, 2026-09-29)
added `POST /api/v1/concerts/{concert_id}/tickets`, and its demo was four
seconds of the API root and the dashboard — nobody saw a ticket sold, and
the `feature_pages` gate said "not run".

When the cycle's PRs touch a route that is not GET, one Claude call reads
the workspace (routers, schemas, the demo seed) and writes a short script
against the seeded data: the state before, the feature's own request with
a real body, the state after. Each capture lane plays it on its own demo
server — a database of its own, thrown away after — and draws every
exchange legibly (`playwright_recorder.present_exchange`). What the
feature's own calls answered is the `feature_calls` gate.
"""

from __future__ import annotations

import logging
import re

from theswarm.agents.qa_feature_pages import _label, routes_per_pr
from theswarm.tools.claude import ClaudeFatalError

log = logging.getLogger(__name__)

MAX_DEMO_CALLS = 6
DEMO_CALLS_TIMEOUT_SECONDS = 240
CALL_TIMEOUT_SECONDS = 10.0
BODY_LIMIT = 20_000
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_PARAM_RE = re.compile(r"\{[^}]+\}")

DEMO_CALLS_PROMPT = """\
You are QA, preparing the demo of a feature this cycle just built. The demo
runs this repository's app on a fresh database{seed}

The feature added or changed these routes (method, path template, pull request):
{routes}

The demo already walks every GET route as is: its path with ids filled with
1, no query string. Write calls only where that walk cannot show the
feature: a route that changes data, and a GET route that needs query
parameters (or ids the walk would not guess). A GET route that answers as
is needs no call — answer an empty list when no route needs one.

Read the code — the routers, the request schemas, the seed — and write at
most {limit} HTTP calls that SHOW the feature working on that data, in order:
1. what the data looks like before (a GET), when the feature changes something;
2. the feature's own request(s): a JSON body built from the schema, or the
   query parameters a GET needs;
3. what changed after (the same GET).

Rules:
- Use ids and values the seed creates; never invent a row that is not there.
- A path starts with "/" and has its ids filled in; no host, no query secrets.
- Each call has a one-line caption a viewer reads, saying what it shows
  ("Before: 120 of 500 tickets sold", "Sell two tickets").
- Nothing else: no call the feature does not need.
"""


async def feature_routes(github, prs: list[dict]) -> list[dict]:
    """The routes the cycle's PRs touched, each once, with the PR that
    touched it first: ``{"pr", "method", "path"}``. GET ones too: a GET that
    needs a query parameter shows nothing to the page walk — artist-search's
    `/tours/search` answered it 422 and its demo showed the dashboard
    (da79522769b3); the writer decides which need a call."""
    routes: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for number, touched in (await routes_per_pr(github, prs)).items():
        for method, template in touched:
            key = (method.upper(), template)
            if key not in seen:
                seen.add(key)
                routes.append({"pr": number, "method": key[0], "path": template})
    return routes


def _valid_path(path: object) -> bool:
    """A path on the demo server itself: "/…", never a host of its own."""
    return (isinstance(path, str) and path.startswith("/") and not path.startswith("//")
            and "://" not in path and not any(c in path for c in "\r\n\t "))


def _template_re(template: str) -> re.Pattern:
    """`/concerts/{concert_id}/tickets` → a pattern any filled-in id matches."""
    pieces = _PARAM_RE.split(template)
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in pieces) + "/?$")


def _route_of(call: dict, routes: list[dict]) -> dict | None:
    """The feature route a call exercises, matching its path template."""
    path = call["path"].split("?")[0]
    for route in routes:
        if call["method"] == route["method"] and _template_re(route["path"]).match(path):
            return route
    return None


def label_calls(calls: list[dict], routes: list[dict]) -> list[dict]:
    """Each call with its capture label: a call of the feature's own route
    is its PR's story capture (`feature_pr_<n>_<method>_…`), the others
    (before/after) are `feature_call_<k>_…`."""
    labelled = []
    for position, call in enumerate(calls, start=1):
        route = _route_of(call, routes)
        if route is not None:
            slug = _label(route["pr"], call["path"]).removeprefix(f"feature_pr_{route['pr']}_")
            label = f"feature_pr_{route['pr']}_{call['method'].lower()}_{slug}"
        else:
            label = _label(position, call["path"]).replace("feature_pr_", "feature_call_", 1)
        labelled.append({**call, "label": label})
    return labelled


async def write_demo_calls(claude, workspace: str, routes: list[dict], *, seed: str = "") -> dict:
    """``{"routes", "calls", "reason"}``: the demo's calls, labelled, or why
    there are none. One Claude call, only when a route is not GET."""
    if not routes:
        return {"routes": [], "calls": [], "reason": ""}
    from theswarm.agents.schemas import DemoScript

    prompt = DEMO_CALLS_PROMPT.format(
        seed=(", filled by:\n" + seed) if seed else ".",
        routes="\n".join(f"- {r['method']} {r['path']} (PR #{r['pr']})" for r in routes),
        limit=MAX_DEMO_CALLS,
    )
    try:
        result = await claude.run(prompt, workdir=workspace, timeout=DEMO_CALLS_TIMEOUT_SECONDS,
                                  output_schema=DemoScript.model_json_schema())
        answered = (getattr(result, "structured", None) or {}).get("calls") or []
    except ClaudeFatalError:
        raise
    except Exception as exc:  # noqa: BLE001 — no script, the demo shows the pages
        log.warning("QA: the feature's demo calls could not be written (%s)", exc)
        return {"routes": routes, "calls": [], "error": True,
                "reason": f"the demo calls could not be written: {exc}"}
    calls = [
        {"method": str(c.get("method", "")).upper(), "path": c.get("path"),
         "json_body": c.get("json_body"), "caption": str(c.get("caption") or "")[:200]}
        for c in answered if isinstance(c, dict)
    ]
    calls = [c for c in calls if c["method"] in _METHODS and _valid_path(c["path"])][:MAX_DEMO_CALLS]
    log.info("QA: %d demo call(s) for the feature: %s", len(calls),
             ", ".join(f"{c['method']} {c['path']}" for c in calls))
    return {"routes": routes, "calls": label_calls(calls, routes),
            "reason": "" if calls else "the demo script named no usable call"}


async def play_calls(base_url: str, calls: list[dict]) -> list[dict]:
    """Every call made in order on the demo server; each result is the call
    plus ``status`` (None when nothing answered), ``content_type``, ``body``
    and the ``request`` body sent."""
    import httpx

    results: list[dict] = []
    async with httpx.AsyncClient(base_url=base_url, timeout=CALL_TIMEOUT_SECONDS) as client:
        for call in calls:
            body = call.get("json_body")
            try:
                response = await client.request(
                    call["method"], call["path"], **({"json": body} if body is not None else {}))
                status, kind, text = (response.status_code, response.headers.get("content-type", ""),
                                      response.text[:BODY_LIMIT])
            except Exception as exc:  # noqa: BLE001 — an unanswered call is a fact of the demo
                status, kind, text = None, "", f"no answer: {exc}"
            log.info("QA: demo call %s %s → %s", call["method"], call["path"], status)
            results.append({**call, "request": body, "status": status,
                            "content_type": kind, "body": text})
    return results


def feature_calls_gate(script: dict | None, results: list[dict], *, launch_error: str = "") -> dict:
    """QA's verdict on the feature's own requests, played on the running target.

    Only the calls of a route the PRs added judge (their label names the
    PR); the before/after reads are there to be seen. A 5xx is `fail`. A
    2xx and no 5xx is `pass`. A 4xx proves nothing — the body was written
    from the code, not from a working request — so none answering 2xx is
    `not_run`, as is a script nobody could write or a server that never
    started.
    """
    script = script or {}
    played = [{"method": r.get("method"), "path": r.get("path"), "status": r.get("status")}
              for r in results]
    routes = script.get("routes") or []
    if not routes:
        return {"status": "not_run", "calls": [], "reason": "the PRs touch no route"}
    if not script.get("calls"):
        if all(str(r.get("method", "")).upper() == "GET" for r in routes) and not script.get("error"):
            return {"status": "not_run", "calls": [],
                    "reason": "the pages are the demo — every route walks as is"}
        return {"status": "not_run", "calls": [], "reason": script.get("reason") or "no demo call"}
    if launch_error and not any(r.get("status") for r in results):
        return {"status": "not_run", "calls": played,
                "reason": f"the demo server did not start: {launch_error}"}
    own = [r for r in results if str(r.get("label", "")).startswith("feature_pr_")]
    crashed = [r for r in own if isinstance(r.get("status"), int) and r["status"] >= 500]
    if crashed:
        return {"status": "fail", "calls": played,
                "reason": "; ".join(f"{r['method']} {r['path']} answered {r['status']}" for r in crashed)}
    answered = [r for r in own if isinstance(r.get("status"), int) and 200 <= r["status"] < 300]
    if not own:
        return {"status": "not_run", "calls": played,
                "reason": "the demo script made no call of the feature's own routes"}
    if not answered:
        heard = ", ".join(f"{r['method']} {r['path']} {r.get('status') or 'unanswered'}" for r in own)
        return {"status": "not_run", "calls": played,
                "reason": f"no call of the feature answered 2xx: {heard}"}
    return {"status": "pass", "calls": played,
            "reason": f"{len(answered)} of {len(own)} call(s) of the feature answered 2xx"}

