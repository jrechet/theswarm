"""A report's thumbnail path (from V1's demos tests, M6): what the demo card and the player use."""

from __future__ import annotations

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.entities import DemoReport, StoryReport
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType


class TestDemoThumbnails:
    def test_thumbnail_path_prefers_top_level_screenshot(self):
        report = DemoReport(
            id="r1",
            cycle_id=CycleId("cyc-r1"),
            project_id="p",
            artifacts=(
                Artifact(type=ArtifactType.VIDEO, path="cyc/video/demo.webm", label="demo"),
                Artifact(type=ArtifactType.SCREENSHOT, path="cyc/screenshot/a.png", label="a"),
            ),
        )
        assert report.thumbnail_path == "cyc/screenshot/a.png"

    def test_thumbnail_path_falls_back_to_story_screenshot(self):
        story = StoryReport(
            ticket_id="T-1",
            title="t",
            status="completed",
            screenshots_after=(
                Artifact(type=ArtifactType.SCREENSHOT, path="cyc/screenshot/after.png", label="after"),
            ),
        )
        report = DemoReport(
            id="r2",
            cycle_id=CycleId("cyc-r2"),
            project_id="p",
            stories=(story,),
        )
        assert report.thumbnail_path == "cyc/screenshot/after.png"

    def test_thumbnail_path_none_when_no_screenshots(self):
        report = DemoReport(id="r3", cycle_id=CycleId("cyc-r3"), project_id="p")
        assert report.thumbnail_path is None
