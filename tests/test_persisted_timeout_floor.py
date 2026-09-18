"""The learned CLI timeout floor survives a deploy.

`_REPO_FLOORS` lives in the process, and every self-cycle ends with a merge
and a deploy, so each one started at 420s again, timed out, and paid seven
minutes to relearn what the cycle before already knew (#133). Cycle
`b209a76055a6` did it twice and then hit the subscription's session limit.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.persistence.timeout_floor_repo import (
    FLOOR_MAX_AGE_DAYS,
    SQLiteTimeoutFloorRepository,
)
from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import ClaudeCLI

WS = "/home/botuser/.swarm-workspaces/alpha/theswarm"


@pytest.fixture(autouse=True)
def _clean_floors():
    before = dict(claude_mod._REPO_FLOORS)
    claude_mod._REPO_FLOORS.clear()
    claude_mod.set_floor_store(None)
    yield
    claude_mod._REPO_FLOORS.clear()
    claude_mod._REPO_FLOORS.update(before)
    claude_mod.set_floor_store(None)


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "test.db"))
    yield SQLiteTimeoutFloorRepository(conn)
    await conn.close()


class TestTheStore:
    async def test_a_saved_floor_comes_back(self, repo):
        await repo.save(WS, 546)

        assert await repo.load_all() == {WS: 546}

    async def test_only_the_highest_is_kept(self, repo):
        await repo.save(WS, 709)
        await repo.save(WS, 546)

        assert await repo.load_all() == {WS: 709}

    async def test_a_stale_floor_is_ignored(self, repo):
        """A target's suite may have got faster; a floor is not forever."""
        await repo.save(WS, 709)
        old = (datetime.now(timezone.utc) - timedelta(days=FLOOR_MAX_AGE_DAYS + 1)).isoformat()
        await repo._conn.execute(
            "UPDATE cli_timeout_floors SET updated_at = ? WHERE workdir = ?", (old, WS),
        )
        await repo._conn.commit()

        assert await repo.load_all() == {}

    async def test_each_workspace_has_its_own(self, repo):
        await repo.save(WS, 709)
        await repo.save("/ws/small-app", 420)

        assert await repo.load_all() == {WS: 709, "/ws/small-app": 420}


class TestTheWiring:
    async def test_priming_makes_the_first_call_start_at_the_learned_floor(self, repo):
        await repo.save(WS, 709)

        await claude_mod.prime_repo_floors(repo)

        assert ClaudeCLI(model="haiku")._effective_timeout(420, workdir=WS) == 709

    async def test_a_raised_floor_is_written_through(self, repo):
        claude_mod.set_floor_store(repo)
        cli = ClaudeCLI(model="haiku")

        grown = cli._retry_timeout(420, TimeoutError("CLI timed out after 420s"), workdir=WS)
        await claude_mod.drain_floor_writes()

        assert grown == 546
        assert await repo.load_all() == {WS: 546}

    async def test_without_a_store_the_floor_still_works_in_process(self):
        cli = ClaudeCLI(model="haiku")

        cli._retry_timeout(420, TimeoutError("CLI timed out after 420s"), workdir=WS)
        await claude_mod.drain_floor_writes()

        assert claude_mod._REPO_FLOORS[WS] == 546

    async def test_a_failing_store_never_breaks_a_call(self, repo):
        class Broken:
            async def save(self, *_a):
                raise RuntimeError("database is locked")

        claude_mod.set_floor_store(Broken())
        cli = ClaudeCLI(model="haiku")

        grown = cli._retry_timeout(420, TimeoutError("CLI timed out after 420s"), workdir=WS)
        await claude_mod.drain_floor_writes()

        assert grown == 546  # the call goes on


class TestTheImplementationBudget:
    def test_it_holds_a_real_implementation(self):
        """420s timed out on this repo in every self-cycle that wrote code
        (fbd5cf8615e0, 5b1da00155c2, b209a76055a6); the successful calls ran
        five to eight minutes."""
        from theswarm.agents.dev import IMPLEMENT_TIMEOUT_SECONDS

        assert IMPLEMENT_TIMEOUT_SECONDS >= 600

    def test_one_call_plus_its_retry_still_fit_the_phase(self):
        from theswarm.agents.dev import (
            DEP_INSTALL_TIMEOUT_SECONDS,
            IMPLEMENT_TIMEOUT_SECONDS,
            TEST_RUN_TIMEOUT_SECONDS,
        )
        from theswarm.cycle import PHASE_TIMEOUTS

        success_path = (
            IMPLEMENT_TIMEOUT_SECONDS + DEP_INSTALL_TIMEOUT_SECONDS
            + TEST_RUN_TIMEOUT_SECONDS + IMPLEMENT_TIMEOUT_SECONDS + TEST_RUN_TIMEOUT_SECONDS
        )
        assert PHASE_TIMEOUTS["dev_iter"] >= success_path
