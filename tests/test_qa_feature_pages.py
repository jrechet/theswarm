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
