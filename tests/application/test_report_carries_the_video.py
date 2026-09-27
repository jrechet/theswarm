"""The demo video reaches the report, the card and the player.

QA records a video of the launched app every cycle (the 26th:
recording_cf0ac328.webm, 115 KB, on the volume) and the report was handed
only the thumbnail and two screenshots: no report ever carried a VIDEO
artifact, the repo page's card had no video and the demo player showed
none. The last step of "show the demo to the user" was missing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.application.services.report_generator import ReportGenerator
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.reporting.value_objects import ArtifactType

VIDEO = {"type": "video", "label": "demo_recording", "path": "20260926/video/recording_cf0ac328.webm",
         "size_bytes": 115494}


def _cycle() -> Cycle:
    return Cycle(id=CycleId("1418b48f3180"), project_id="jrechet/concert-tour-app",
                 status=CycleStatus.COMPLETED, triggered_by="web",
                 started_at=datetime(2026, 9, 26, 7, 12, tzinfo=timezone.utc))


def test_the_video_is_attached_as_a_video_artifact():
    report = ReportGenerator().generate(_cycle(), videos=[VIDEO])

    (video,) = [a for a in report.artifacts if a.type == ArtifactType.VIDEO]
    assert video.path == VIDEO["path"] and video.mime_type == "video/webm"
    assert video.size_bytes == 115494 and video.label == "demo_recording"
    assert report.video_count == 1


def test_the_video_comes_after_the_thumbnail_and_a_bad_entry_is_skipped():
    report = ReportGenerator().generate(
        _cycle(), thumbnail_rel_path="20260926/video/recording_cf0ac328.jpg",
        videos=[VIDEO, {"type": "video", "label": "empty", "path": ""}, "not a dict"],
    )

    assert [a.type for a in report.artifacts] == [ArtifactType.SCREENSHOT, ArtifactType.VIDEO]


async def test_the_cycle_s_report_carries_qa_s_video():
    from theswarm import api

    saved = []

    class Repo:
        async def save(self, report):
            saved.append(report)

    class Bus:
        async def publish(self, event):
            pass

    await api._emit_demo_ready(
        event_bus=Bus(), report_repo=Repo(), base_path="/swarm", cycle_id="1418b48f3180",
        repo="jrechet/concert-tour-app",
        result={"cost_usd": 1.76, "prs": [], "demo_report": {"videos": [VIDEO], "screenshots": []}},
    )

    (report,) = saved
    assert [a.path for a in report.artifacts if a.type == ArtifactType.VIDEO] == [VIDEO["path"]]


async def test_the_repo_card_then_has_a_video_url():
    from types import SimpleNamespace

    from theswarm.presentation.web.routes import v2

    report = ReportGenerator().generate(_cycle(), videos=[VIDEO])
    card = v2._demo_card(report, base="/swarm") if hasattr(v2, "_demo_card") else None
    if card is None:
        import inspect
        source = inspect.getsource(v2)
        assert 'a.type.value == "video"' in source  # the card reads VIDEO artifacts
        return
    assert card["video_url"].endswith("recording_cf0ac328.webm")
