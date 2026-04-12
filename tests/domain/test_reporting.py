"""Tests for domain/reporting — 100% coverage target."""

from __future__ import annotations

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.value_objects import (
    Artifact,
    ArtifactType,
    DiffHighlight,
    QualityGate,
    QualityStatus,
)


class TestArtifactType:
    def test_values(self):
        assert ArtifactType.SCREENSHOT == "screenshot"
        assert ArtifactType.VIDEO == "video"
        assert ArtifactType.DIFF == "diff"
        assert ArtifactType.LOG == "log"


class TestQualityStatus:
    def test_values(self):
        assert QualityStatus.PASS == "pass"
        assert QualityStatus.FAIL == "fail"
        assert QualityStatus.WARN == "warn"
        assert QualityStatus.SKIP == "skip"


class TestArtifact:
    def test_creation(self):
        a = Artifact(
            type=ArtifactType.SCREENSHOT, label="login_page",
            path="/artifacts/cycle-1/login.png", mime_type="image/png",
            size_bytes=45000,
        )
        assert a.type == ArtifactType.SCREENSHOT
        assert a.label == "login_page"


class TestDiffHighlight:
    def test_creation(self):
        d = DiffHighlight(
            file_path="src/auth.ts", hunk="+const token = ...",
            annotation="New auth token logic", lines_added=5, lines_removed=2,
        )
        assert d.file_path == "src/auth.ts"


class TestQualityGate:
    def test_pass(self):
        g = QualityGate(name="coverage", status=QualityStatus.PASS, value=85.0)
        assert g.value == 85.0

    def test_fail(self):
        g = QualityGate(name="security", status=QualityStatus.FAIL, detail="2 critical")
        assert g.detail == "2 critical"


class TestStoryReport:
    def test_creation(self):
        s = StoryReport(
            ticket_id="42", title="Fix login", status="completed",
            pr_number=47, files_changed=3, lines_added=100, lines_removed=20,
        )
        assert s.pr_number == 47
        assert s.screenshots_before == ()
        assert s.video is None

    def test_with_artifacts(self):
        before = Artifact(type=ArtifactType.SCREENSHOT, label="before", path="a.png")
        after = Artifact(type=ArtifactType.SCREENSHOT, label="after", path="b.png")
        video = Artifact(type=ArtifactType.VIDEO, label="e2e", path="e2e.webm")
        s = StoryReport(
            ticket_id="42", title="Fix", status="completed",
            screenshots_before=(before,), screenshots_after=(after,),
            video=video,
        )
        assert len(s.screenshots_before) == 1
        assert s.video is not None


class TestReportSummary:
    def test_defaults(self):
        s = ReportSummary()
        assert s.stories_completed == 0
        assert s.cost_usd == 0.0

    def test_creation(self):
        s = ReportSummary(stories_completed=2, stories_total=3, prs_merged=2, cost_usd=5.0)
        assert s.stories_completed == 2


class TestDemoReport:
    def test_creation(self):
        r = DemoReport(
            id="r1", cycle_id=CycleId("c1"), project_id="p1",
        )
        assert r.all_gates_pass is True
        assert r.screenshot_count == 0
        assert r.video_count == 0

    def test_gates_with_failure(self):
        r = DemoReport(
            id="r1", cycle_id=CycleId("c1"), project_id="p1",
            quality_gates=(
                QualityGate(name="tests", status=QualityStatus.PASS),
                QualityGate(name="security", status=QualityStatus.FAIL),
            ),
        )
        assert r.all_gates_pass is False

    def test_artifact_counts(self):
        screenshot = Artifact(type=ArtifactType.SCREENSHOT, label="x", path="x.png")
        video = Artifact(type=ArtifactType.VIDEO, label="y", path="y.webm")
        story = StoryReport(
            ticket_id="1", title="T", status="completed",
            screenshots_before=(screenshot,),
            screenshots_after=(screenshot,),
            video=video,
        )
        r = DemoReport(
            id="r1", cycle_id=CycleId("c1"), project_id="p1",
            stories=(story,),
            artifacts=(screenshot, video),
        )
        assert r.screenshot_count == 3  # 1 top-level + 2 in story
        assert r.video_count == 2  # 1 top-level + 1 in story
