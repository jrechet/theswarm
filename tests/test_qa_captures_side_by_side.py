"""QA's demo captures run in two lanes, side by side (V2 runtime, M5b).

The screenshot walk launches its demo server on e2e_port()+1, the video walk
on +2, and neither reads the other's answer: QA can spend the longer of the
two instead of their sum. SWARM_QA_CAPTURE_CONCURRENCY=1 keeps the order the
four sequential nodes had.
"""

from __future__ import annotations

import asyncio

import pytest

from theswarm.agents import qa


def _fakes(monkeypatch, log: list[str], *, meet: bool, fail: str = ""):
    """The four captures, logging when they start and end. With `meet`, the
    screenshot walk waits until the video walk has started — it only
    finishes if the lanes really overlap."""
    video_started = asyncio.Event()

    async def screenshots(state):
        log.append("shots:start")
        if meet:
            await asyncio.wait_for(video_started.wait(), timeout=2)
        if fail == "shots":
            raise RuntimeError("chromium died")
        log.append("shots:end")
        return {"demo_artifacts": ["s.png"], "tokens_used": 1, "demo_launch_error": ""}

    async def before_after(state):
        log.append("before_after")
        return {"story_artifacts": {}, "tokens_used": 0}

    async def story_video(state):
        log.append("story_video")
        return {"story_videos": {}, "tokens_used": 0}

    async def demo_video(state):
        log.append("video:start")
        video_started.set()
        await asyncio.sleep(0)
        log.append("video:end")
        return {"video_artifacts": ["v.webm"], "tokens_used": 2,
                "demo_launch_error": "server never answered"}

    monkeypatch.setattr(qa, "capture_demo_screenshots", screenshots)
    monkeypatch.setattr(qa, "capture_before_after_per_story", before_after)
    monkeypatch.setattr(qa, "record_story_video", story_video)
    monkeypatch.setattr(qa, "record_demo_video", demo_video)


async def test_the_two_lanes_overlap(monkeypatch):
    log: list[str] = []
    _fakes(monkeypatch, log, meet=True)
    monkeypatch.delenv("SWARM_QA_CAPTURE_CONCURRENCY", raising=False)

    out = await qa.run_captures({})

    assert log.index("video:start") < log.index("shots:end")
    assert out["demo_artifacts"] == ["s.png"] and out["video_artifacts"] == ["v.webm"]


async def test_the_answers_merge(monkeypatch):
    _fakes(monkeypatch, [], meet=False)

    out = await qa.run_captures({})

    assert out["tokens_used"] == 3
    # The first launch error is the one the report explains; an empty one
    # from the other lane does not erase it.
    assert out["demo_launch_error"] == "server never answered"
    assert set(out) >= {"demo_artifacts", "video_artifacts", "story_artifacts", "story_videos"}


async def test_one_at_a_time_keeps_the_old_order(monkeypatch):
    log: list[str] = []
    _fakes(monkeypatch, log, meet=False)
    monkeypatch.setenv("SWARM_QA_CAPTURE_CONCURRENCY", "1")

    await qa.run_captures({})

    assert log == ["shots:start", "shots:end", "before_after",
                   "story_video", "video:start", "video:end"]


async def test_a_lane_that_fails_lets_the_other_finish_then_surfaces(monkeypatch):
    log: list[str] = []
    _fakes(monkeypatch, log, meet=False, fail="shots")

    with pytest.raises(RuntimeError, match="chromium died"):
        await qa.run_captures({})

    assert "video:end" in log


def test_the_graph_runs_the_captures_as_one_node():
    graph = qa.build_qa_graph()
    nodes = set(graph.nodes)

    assert "captures" in nodes
    assert not nodes & {"capture_screenshots", "record_video"}


@pytest.mark.parametrize("raw,expected", [("", 2), ("1", 1), ("3", 3), ("0", 1), ("x", 2)])
def test_the_width_is_read_defensively(monkeypatch, raw, expected):
    if raw:
        monkeypatch.setenv("SWARM_QA_CAPTURE_CONCURRENCY", raw)
    else:
        monkeypatch.delenv("SWARM_QA_CAPTURE_CONCURRENCY", raising=False)
    assert qa._capture_concurrency() == expected
