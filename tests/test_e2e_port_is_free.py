"""The demo servers must not fight another program for a port.

`E2E_PORT = 8000` was hardcoded. On a machine where something else already
listens there — a `solana-te` process, on the owner's laptop — QA's server
could not take the port, the readiness probe talked to the stranger, got a
flat 400 for the full 90s wait, and reported:

    QA E2E: server at http://127.0.0.1:8000/ not ready after 90.0s
    (179 attempts, last: status=400) — server still running but not serving

Four local cycles in a row reported `e2e=0` for that reason alone, while the
screenshot and video servers on 8001/8002 worked fine. The message blamed the
target; the truth was the port.

The base port is chosen once per process: the generated E2E test file bakes it
into its URLs, and `run_e2e_tests` must bind the same one.
"""

from __future__ import annotations

import socket

import pytest

from theswarm.agents.qa import E2E_PORT, _pick_base_port, e2e_port


@pytest.fixture
def occupied():
    """Hold a real listener, the way the stray process did."""
    held = []

    def _take(port: int) -> int:
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind(("127.0.0.1", port))
        s.listen(1)
        held.append(s)
        return s.getsockname()[1]

    yield _take
    for s in held:
        s.close()


def _is_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def test_the_preferred_base_is_used_when_it_is_free():
    free = _pick_base_port(preferred=_free_triplet_base())
    assert _is_free(free)


def _free_triplet_base() -> int:
    """A base whose three ports are all currently free."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        base = s.getsockname()[1]
    return base + 1000


def test_an_occupied_base_is_skipped(occupied):
    base = _free_triplet_base()
    occupied(base)

    chosen = _pick_base_port(preferred=base)

    assert chosen != base, (
        "taking a port another program already listens on is what made the "
        "readiness probe talk to a stranger for 90s"
    )
    assert all(_is_free(chosen + offset) for offset in (0, 1, 2))


def test_the_whole_triplet_must_be_free(occupied):
    """Screenshots and video use base+1 and base+2; all three must be ours."""
    base = _free_triplet_base()
    occupied(base + 2)

    chosen = _pick_base_port(preferred=base)

    assert chosen != base
    assert all(_is_free(chosen + offset) for offset in (0, 1, 2))


def test_the_port_is_chosen_once_per_process():
    """The generated test file bakes the port in; the server must match it."""
    assert e2e_port() == e2e_port()


def test_the_preferred_default_is_still_8000():
    """Nothing changes on a machine where 8000 is free."""
    assert E2E_PORT == 8000
