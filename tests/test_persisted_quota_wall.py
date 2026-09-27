"""The closed subscription window outlives a deploy.

`tools/quota_wall` remembered the wall in the process, and a merge
redeploys the service: every deploy forgot it, `/health` read `claude: ok`
on the new container, and the next harness run created its issue and
started a cycle that died on the first call. The wall is now stored with
its reset time and primed at boot, like the CLI timeout floors (#133).
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from theswarm.infrastructure.persistence.quota_wall_repo import SQLiteQuotaWallRepository
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.tools import quota_wall

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEEKLY = "You've hit your weekly limit · resets Sep 29, 4am (UTC)"
NOW = datetime(2026, 9, 27, 7, 15, tzinfo=timezone.utc)


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "wall.db"))
    yield SQLiteQuotaWallRepository(conn)
    await conn.close()


async def test_a_saved_wall_comes_back(repo):
    until = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)

    await repo.save(until, WEEKLY)

    assert await repo.load() == (until, WEEKLY)


async def test_nothing_saved_is_none(repo):
    assert await repo.load() is None


async def test_the_latest_save_wins(repo):
    await repo.save(datetime(2026, 9, 27, 13, 20, tzinfo=timezone.utc), "session")
    await repo.save(datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc), WEEKLY)

    assert (await repo.load())[1] == WEEKLY


async def test_priming_restores_a_wall_still_standing(repo):
    until = datetime.now(timezone.utc) + timedelta(days=1)
    await repo.save(until, WEEKLY)

    await quota_wall.prime(repo)

    assert quota_wall.wall_until() == until
    assert quota_wall.reason() == WEEKLY


async def test_priming_ignores_a_wall_that_has_passed(repo):
    await repo.save(datetime.now(timezone.utc) - timedelta(hours=1), WEEKLY)

    await quota_wall.prime(repo)

    assert quota_wall.wall_until() is None


async def test_a_raised_wall_is_written_to_the_store(repo):
    await quota_wall.prime(repo)

    quota_wall.raise_wall(WEEKLY, now=NOW)
    await quota_wall.drain_writes()

    until, reason = await repo.load()
    assert until == datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc) and reason == WEEKLY


async def test_a_broken_store_never_stops_a_call(repo):
    class Broken:
        async def load(self):
            raise RuntimeError("database is locked")

        async def save(self, until, reason):
            raise RuntimeError("database is locked")

    await quota_wall.prime(Broken())
    quota_wall.raise_wall(WEEKLY, now=NOW)
    await quota_wall.drain_writes()

    assert quota_wall.wall_until(now=NOW) is not None


def test_the_server_primes_the_wall_at_boot():
    source = (ROOT / "src/theswarm/presentation/web/server.py").read_text()

    assert "quota_wall.prime(SQLiteQuotaWallRepository(conn))" in source
