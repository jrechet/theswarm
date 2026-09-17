"""`demo.pages` and `demo.setup` — the demo card showed a JSON 404 page.

Cycle 05b7dceeea99 got the mechanics right (readiness, scoped E2E, an
honest `not_run`) and still put a 404 in the demo: the screenshot/video walk
guesses `/`, `/docs`, `/health`, and this app's `/docs` 404s (#144). And the
QA workspace is a plain clone — `static/v2/app.css` is generated
(`scripts/build-css.sh`), so the one real page it did capture rendered
unstyled (Times, blue links). `demo.pages` replaces the guess, a non-2xx
page is skipped instead of captured, and `demo.setup` runs the build once
before the first launch.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.agents.qa import (
    DEMO_SETUP_TIMEOUT_SECONDS,
    _DEMO_SETUP_DONE,
    _demo_pages,
    _guessed_pages,
    _label_for_path,
    _page_status,
    _pages_to_capture,
    _run_demo_setup,
    capture_demo_screenshots,
)


# ── _label_for_path ──────────────────────────────────────────────────────


def test_root_path_is_homepage():
    assert _label_for_path("/") == "homepage"


def test_empty_path_is_homepage():
    assert _label_for_path("") == "homepage"


def test_nested_path_becomes_a_safe_label():
    assert _label_for_path("/r/jrechet/theswarm") == "r_jrechet_theswarm"


# ── _demo_pages / _pages_to_capture ──────────────────────────────────────


def test_undeclared_pages_returns_none(tmp_path):
    assert _demo_pages(str(tmp_path)) is None


def test_declared_pages_are_read_with_derived_labels(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  pages:\n    - '/'\n    - '/r/jrechet/theswarm'\n",
    )

    pages = _demo_pages(str(tmp_path))

    assert pages == [("/", "homepage"), ("/r/jrechet/theswarm", "r_jrechet_theswarm")]


def test_empty_declared_pages_falls_back_to_none(tmp_path):
    (tmp_path / "theswarm.yaml").write_text("demo:\n  command: 'x'\n  pages: []\n")

    assert _demo_pages(str(tmp_path)) is None


def test_pages_to_capture_uses_the_guess_when_undeclared(tmp_path):
    assert _pages_to_capture(str(tmp_path)) == _guessed_pages(str(tmp_path))


def test_pages_to_capture_prefers_the_declaration(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  pages:\n    - '/only'\n",
    )

    assert _pages_to_capture(str(tmp_path)) == [("/only", "only")]


def test_theswarms_own_manifest_declares_its_pages():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    pages = _demo_pages(root)

    assert pages == [("/", "homepage"), ("/r/jrechet/theswarm", "r_jrechet_theswarm")]


# ── _page_status ──────────────────────────────────────────────────────────


async def test_page_status_returns_the_response_code():
    resp = MagicMock(status_code=404)
    client = AsyncMock()
    client.get = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=client):
        assert await _page_status("http://x/docs") == 404


async def test_page_status_is_none_on_request_failure():
    client = AsyncMock()
    client.get = AsyncMock(side_effect=RuntimeError("boom"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=client):
        assert await _page_status("http://x/") is None


# ── _run_demo_setup ───────────────────────────────────────────────────────


async def _fake_proc(returncode=0, output=b"ok"):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(output, None))
    proc.kill = MagicMock()
    return proc


async def test_no_setup_declared_runs_nothing(tmp_path):
    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as create:
        await _run_demo_setup(str(tmp_path))

    create.assert_not_called()


async def test_declared_setup_commands_run_in_the_workspace(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  setup:\n    - 'bash scripts/build-css.sh'\n",
    )
    proc = await _fake_proc()

    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=proc) as create:
        await _run_demo_setup(str(tmp_path))

    create.assert_called_once()
    args, kwargs = create.call_args
    assert args[0] == "bash scripts/build-css.sh"
    assert kwargs["cwd"] == str(tmp_path)


async def test_setup_env_is_scrubbed_like_the_launch(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_real")
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  setup:\n    - 'true'\n  env:\n    FOO: bar\n",
    )
    proc = await _fake_proc()

    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=proc) as create:
        await _run_demo_setup(str(tmp_path))

    env = create.call_args.kwargs["env"]
    assert "GITHUB_TOKEN" not in env
    assert env["FOO"] == "bar"


async def test_a_failing_setup_command_is_logged_and_does_not_raise(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  setup:\n    - 'exit 1'\n",
    )
    proc = await _fake_proc(returncode=1, output=b"error output")

    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=proc):
        await _run_demo_setup(str(tmp_path))  # does not raise


async def test_a_timed_out_setup_command_is_logged_and_does_not_raise(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  setup:\n    - 'sleep 999'\n",
    )
    proc = await _fake_proc()
    proc.kill = MagicMock()

    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=proc), \
         patch("asyncio.wait_for", new_callable=AsyncMock, side_effect=TimeoutError()):
        await _run_demo_setup(str(tmp_path))  # does not raise

    proc.kill.assert_called_once()


async def test_setup_runs_once_per_workspace(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  setup:\n    - 'true'\n",
    )
    proc = await _fake_proc()

    with patch("asyncio.create_subprocess_shell", new_callable=AsyncMock, return_value=proc) as create:
        await _run_demo_setup(str(tmp_path))
        await _run_demo_setup(str(tmp_path))

    create.assert_called_once()


async def test_each_command_gets_its_own_budget(tmp_path):
    assert DEMO_SETUP_TIMEOUT_SECONDS == 300


# ── a 404 page is skipped, never screenshotted ───────────────────────────


async def _fake_server_proc():
    proc = AsyncMock()
    proc.returncode = None
    proc.wait = AsyncMock(return_value=0)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


async def test_a_404_page_is_skipped_and_logged_not_screenshotted(tmp_path, caplog):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: '{python} -m x'\n  pages:\n    - '/'\n    - '/docs'\n",
    )
    claude = MagicMock()
    fake_proc = await _fake_server_proc()

    recorder = MagicMock()
    recorder.screenshot = AsyncMock(side_effect=lambda url, label: (label, url))
    recorder.close = AsyncMock()

    async def fake_status(url):
        return 404 if url.endswith("/docs") else 200

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready",
               new_callable=AsyncMock, return_value=None), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder",
               return_value=recorder), \
         patch("theswarm.agents.qa._page_status", side_effect=fake_status), \
         caplog.at_level("INFO"):
        state = {"workspace": str(tmp_path), "claude": claude}
        result = await capture_demo_screenshots(state)

    assert len(result["demo_artifacts"]) == 1
    recorder.screenshot.assert_called_once()
    called_url = recorder.screenshot.call_args[0][0]
    assert called_url.endswith("/") and "/docs" not in called_url
    assert "skipped /docs (404)" in caplog.text


@pytest.fixture(autouse=True)
def _reset_setup_dedup():
    """`_DEMO_SETUP_DONE` is a module-level set keyed by workspace path —
    each test uses its own `tmp_path`, but clear it defensively so test
    order can never make one test's run count leak into another's."""
    yield
    _DEMO_SETUP_DONE.clear()
