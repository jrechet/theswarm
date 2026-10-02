"""The demo shows the feature that was built, not only the declared pages.

QA's video and screenshots walked the pages the target declares — the
dashboard and the homepage — whatever the feature was; every demo of
2026-09-25/26 looked the same. The pages a feature lives on can be read off
its pull requests: the GET routes a diff adds, or whose body it touches, with
the router's prefix and its path parameters filled in.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from theswarm.agents import qa_feature_pages as fp

TOURS_AFTER = '''from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/tours", tags=["tours"])


@router.get("/", response_model=list)
def list_tours():
    return []


@router.get("/{tour_id}/summary", response_model=TourSummary)
def tour_summary(tour_id: int):
    return summarise(tour_id)


@router.post("/", status_code=201)
def create_tour(payload):
    return payload


@router.get("/{tour_id}/dates")
def tour_dates(tour_id: int):
    return dates(tour_id)
'''

ADDS_SUMMARY = '''@@ -8,3 +8,8 @@ def list_tours():
     return []
 
 
+@router.get("/{tour_id}/summary", response_model=TourSummary)
+def tour_summary(tour_id: int):
+    return summarise(tour_id)
+
+
 @router.post("/", status_code=201)
'''

TOUCHES_DATES_BODY = '''@@ -20,3 +20,4 @@ def create_tour(payload):
 @router.get("/{tour_id}/dates")
 def tour_dates(tour_id: int):
-    return dates(tour_id)
+    ordered = sorted(dates(tour_id))
+    return ordered
'''


def test_routes_are_read_off_the_file_with_their_router_and_line():
    routes = fp.routes_in(TOURS_AFTER)

    assert [(r.router, r.method, r.path) for r in routes] == [
        ("router", "get", "/"), ("router", "get", "/{tour_id}/summary"),
        ("router", "post", "/"), ("router", "get", "/{tour_id}/dates"),
    ]
    assert routes[1].line == 11


def test_a_route_the_diff_adds_is_a_feature_page():
    assert fp.touched_get_paths(ADDS_SUMMARY, TOURS_AFTER) == ["/api/v1/tours/1/summary"]


def test_a_route_whose_body_the_diff_touches_is_a_feature_page():
    assert fp.touched_get_paths(TOUCHES_DATES_BODY, TOURS_AFTER) == ["/api/v1/tours/1/dates"]


def test_a_post_route_is_never_a_page():
    patch = '''@@ -16,3 +16,4 @@
 @router.post("/", status_code=201)
 def create_tour(payload):
+    validate(payload)
     return payload
'''
    assert fp.touched_get_paths(patch, TOURS_AFTER) == []


def test_two_routers_in_one_file_keep_their_own_prefixes():
    concerts = '''router = APIRouter(prefix="/api/v1/dashboard")
api_router = APIRouter(prefix="/api/v1/concerts")


@api_router.get("/next")
def next_concert():
    return soonest()


@router.get("/concerts")
def dashboard_concerts():
    return cards()
'''
    patch = '''@@ -3,3 +3,6 @@ api_router = APIRouter(prefix="/api/v1/concerts")
 
 
+@api_router.get("/next")
+def next_concert():
+    return soonest()
'''
    assert fp.touched_get_paths(patch, concerts) == ["/api/v1/concerts/next"]


def test_a_prefix_given_at_include_time_is_used():
    stats = '''router = APIRouter()


@router.get("/countries")
def countries():
    return {}
'''
    patch = '''@@ -1,3 +1,6 @@
 router = APIRouter()
+
+
+@router.get("/countries")
+def countries():
+    return {}
'''
    main = 'app.include_router(stats.router, prefix="/api/v1/stats")\n'

    assert fp.touched_get_paths(patch, stats, module="stats", main_source=main) == ["/api/v1/stats/countries"]


def test_query_parameters_stay_off_the_page_and_the_root_is_kept_clean():
    root = 'router = APIRouter(prefix="/api/v1/concerts")\n\n@router.get("/")\ndef concerts(min_price: float | None = None):\n    return []\n'
    patch = '@@ -3,2 +3,3 @@\n @router.get("/")\n-def concerts():\n+def concerts(min_price: float | None = None):\n     return []\n'

    assert fp.touched_get_paths(patch, root) == ["/api/v1/concerts/"]


async def test_feature_pages_come_from_every_pr_once_with_their_label():
    github = AsyncMock()
    github.get_pr_files = AsyncMock(side_effect=[
        [{"filename": "src/routers/tours.py", "patch": ADDS_SUMMARY, "status": "modified"},
         {"filename": "tests/test_tours.py", "patch": "+def test_x(): pass", "status": "added"}],
        [{"filename": "src/routers/tours.py", "patch": ADDS_SUMMARY, "status": "modified"}],
    ])
    github.get_file_content = AsyncMock(return_value=TOURS_AFTER)
    prs = [{"number": 362, "head_sha": "abc"}, {"number": 363, "head_sha": "def"}]

    pages = await fp.feature_pages(github, prs)

    assert pages == [("/api/v1/tours/1/summary", "feature_pr_362_tours_1_summary")]
    github.get_file_content.assert_any_call("src/routers/tours.py", ref="abc")


async def test_a_pr_that_cannot_be_read_costs_nothing():
    github = AsyncMock()
    github.get_pr_files = AsyncMock(side_effect=RuntimeError("502"))

    assert await fp.feature_pages(github, [{"number": 1, "head_sha": "x"}]) == []


async def test_no_router_change_means_no_feature_page():
    github = AsyncMock()
    github.get_pr_files = AsyncMock(return_value=[{"filename": "src/services/csv.py", "patch": "+x", "status": "added"}])

    assert await fp.feature_pages(github, [{"number": 1, "head_sha": "x"}]) == []
    github.get_file_content.assert_not_called()


def test_story_preview_urls_point_every_pr_at_its_first_page():
    pages = {362: ["/api/v1/tours/1/summary", "/api/v1/tours/1/dates"], 363: []}

    urls = fp.story_preview_urls(pages, port=8001)

    assert urls == {362: {"before": None, "after": "http://127.0.0.1:8001/api/v1/tours/1/summary"}}


# ── A decorator over several lines (lineup-remove, 2026-09-30) ───────
# concert-tour-app#514 added `@api_router.delete(` with its path on the next
# line. The route was not a route to QA: its lines went to the GET lineup
# route above, the demo walked the lineup untouched, no call removed an act
# and the feature_calls gate said "the pages are the demo".

LINEUP_AFTER = '''from fastapi import APIRouter, Response

api_router = APIRouter(prefix="/api/v1/concerts", tags=["concerts"])


@api_router.get(
    "/{concert_id}/lineup",
    response_model=list,
)
def list_concert_lineup(concert_id: int):
    return lineup(concert_id)


@api_router.post(
    path="/{concert_id}/lineup",
    status_code=201,
)
def create_concert_lineup_entry(concert_id: int, payload):
    return entry


@api_router.delete(
    "/{concert_id}/lineup/{entry_id}",
    status_code=204,
)
def delete_concert_lineup_entry(concert_id: int, entry_id: int):
    delete_lineup_entry(concert_id, entry_id)
    return Response(status_code=204)


@api_router.get("/{concert_id}/occupancy")
def occupancy(concert_id: int):
    return occupancy_of(concert_id)
'''

# The shape git gave #514: the new function, then the two blank lines.
ADDS_DELETE = '''@@ -18,5 +18,14 @@ def create_concert_lineup_entry(concert_id: int, payload):
 def create_concert_lineup_entry(concert_id: int, payload):
     return entry
 
 
+@api_router.delete(
+    "/{concert_id}/lineup/{entry_id}",
+    status_code=204,
+)
+def delete_concert_lineup_entry(concert_id: int, entry_id: int):
+    delete_lineup_entry(concert_id, entry_id)
+    return Response(status_code=204)
+
+
 @api_router.get("/{concert_id}/occupancy")
'''

# The same addition with the blank lines first: they are nobody's code.
ADDS_DELETE_BLANKS_FIRST = '''@@ -18,4 +18,13 @@ def create_concert_lineup_entry(concert_id: int, payload):
 def create_concert_lineup_entry(concert_id: int, payload):
     return entry
+
+
+@api_router.delete(
+    "/{concert_id}/lineup/{entry_id}",
+    status_code=204,
+)
+def delete_concert_lineup_entry(concert_id: int, entry_id: int):
+    delete_lineup_entry(concert_id, entry_id)
+    return Response(status_code=204)
 
 
'''


def test_a_path_on_the_line_after_the_decorator_is_a_route():
    routes = fp.routes_in(LINEUP_AFTER)

    assert [(r.method, r.path, r.line) for r in routes] == [
        ("get", "/{concert_id}/lineup", 6), ("post", "/{concert_id}/lineup", 14),
        ("delete", "/{concert_id}/lineup/{entry_id}", 22), ("get", "/{concert_id}/occupancy", 31),
    ]


def test_the_route_the_diff_adds_is_the_feature_not_its_neighbour():
    assert fp.touched_routes(ADDS_DELETE, LINEUP_AFTER) == [
        ("delete", "/api/v1/concerts/{concert_id}/lineup/{entry_id}")]
    assert fp.touched_get_paths(ADDS_DELETE, LINEUP_AFTER) == []


def test_blank_lines_the_diff_adds_touch_no_route():
    assert fp.touched_routes(ADDS_DELETE_BLANKS_FIRST, LINEUP_AFTER) == [
        ("delete", "/api/v1/concerts/{concert_id}/lineup/{entry_id}")]
