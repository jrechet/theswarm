"""The stale-cycle banner must describe the reaper that actually runs.

The wording predated the periodic reaper: it promised cleanup "on next boot"
when the loop now sweeps every 15 minutes. The banner and the loop read the
same threshold so the UI can never advertise a window that isn't real.
"""

from __future__ import annotations

import inspect

from theswarm.application.services.orphan_reaper import (
    DEFAULT_REAP_INTERVAL_SECONDS,
    REAP_GRACE_SECONDS,
    reap_max_age_seconds,
)
from theswarm.presentation.web.routes import health as health_routes


def test_reap_window_sits_above_the_cycle_hard_timeout():
    """A live cycle must never be reaped out from under its own task."""
    from theswarm.api import CYCLE_HARD_TIMEOUT_SECONDS

    assert reap_max_age_seconds() == CYCLE_HARD_TIMEOUT_SECONDS + REAP_GRACE_SECONDS
    assert reap_max_age_seconds() > CYCLE_HARD_TIMEOUT_SECONDS


def test_server_reaps_with_the_shared_threshold():
    """The loop must use the same value the banner quotes."""
    from theswarm.presentation.web import server

    source = inspect.getsource(server.start_server)
    assert "reap_max_age_seconds()" in source
    # The old hardcoded grace must be gone, or the two can drift apart
    assert "CYCLE_HARD_TIMEOUT_SECONDS + 1800" not in source


def test_banner_no_longer_promises_next_boot():
    source = inspect.getsource(health_routes)
    assert "reaper will clean on next boot" not in source


def test_banner_quotes_the_real_interval_and_window():
    source = inspect.getsource(health_routes)
    assert "reap_max_age_seconds" in source
    assert "DEFAULT_REAP_INTERVAL_SECONDS" in source
    assert DEFAULT_REAP_INTERVAL_SECONDS == 15 * 60
