"""DevOps D3 — proposals with the owner's approval (docs/plans/2026-10-v3-one-product.md).

A bad finding that calls for a hand on a machine becomes a proposal with
its exact command; one open proposal per kind and host; the owner's one
click runs it over the host's ssh and the answer is kept; a refusal is
kept too. The policy hook refuses the machine verbs to every agent.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.agents.devops import Finding
from theswarm.application.services import proposals as svc
from theswarm.domain.ops import proposals as d
from theswarm.infrastructure.persistence.ops_repo import SQLiteProposalRepository
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.tools.claude import decide_tool_use

NOW = datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)
STACK = {
    "hosts": [{"name": "jrec.fr", "ssh": "debian@jrec.fr", "port": 5422, "ci_slot_dir": "/srv/gh-runner-work/ci-slots"}],
    "ci": [{"provider": "github-actions", "repo": "jrechet/theswarm", "runner_service": "github_runner_runner_theswarm"}],
    "registry": "ghcr.io/jrechet/theswarm",
    "deploy": {"method": "docker-swarm", "service": "theswarm_theswarm"},
}
STALE = Finding("ci_slot", "CI slot", "bad", "stale: slot1 held by runner-areza (jrechet/areza) for 240 min — past the 180 min rule, every job waits behind it on jrec.fr")


class TestTheProposal:
    def test_its_life(self):
        p = d.Proposal(id="p1", kind="clear_slot", host="jrec.fr", title="Clear the CI slot slot1", why="stale", command="sudo rm -rf /srv/x/slot1")
        assert p.is_open and p.status == "proposed"
        assert p.refused("owner").status == "refused" and not p.refused().is_open
        approved = p.approved("owner", NOW)
        assert approved.status == "approved" and approved.decided_by == "owner" and approved.is_open
        assert approved.approved() is approved  # decided once
        assert p.ran("x", True) is p  # never ran without an approval
        done = approved.ran("removed", True, NOW)
        assert done.status == "run" and done.result == "removed" and done.ran_at == NOW
        assert approved.ran("permission denied", False).status == "failed"


class TestWhatIsProposed:
    def test_a_stale_slot_proposes_to_clear_that_slot(self):
        out = svc.proposals_for((STALE,), STACK)
        assert len(out) == 1 and out[0].kind == "clear_slot" and out[0].host == "jrec.fr"
        assert out[0].command == "sudo rm -rf /srv/gh-runner-work/ci-slots/slot1" and "slot1" in out[0].title
        assert "past the 180 min rule" in out[0].why and out[0].finding_key == "ci_slot"

    def test_a_runner_offline_and_a_deploy_that_did_not_land(self):
        offline = Finding("runners", "Runners", "bad", "1 of 1 offline: runner-theswarm")
        late = Finding("deploy_watch", "Deploy watch", "bad", "main moved to abc1234 50 min ago and this box still runs def5678 — the deploy did not land")
        out = {p.kind: p for p in svc.proposals_for((offline, late), STACK, {"main_sha": "abc1234" + "0" * 33})}
        assert out["restart_runner"].command == "docker service update --force github_runner_runner_theswarm"
        assert out["redeploy"].command == f"docker service update --image ghcr.io/jrechet/theswarm:abc1234{'0' * 33} theswarm_theswarm"
        assert svc.proposals_for((late,), STACK) == []  # main's full sha unknown: nothing exact to propose

    def test_a_host_whose_slots_are_its_own_needs_no_sudo(self):
        here = {"hosts": [{"name": "here", "local": True, "sudo": False, "ci_slot_dir": "/tmp/slots"}]}
        [p] = svc.proposals_for((Finding("ci_slot", "CI slot", "bad", "stale: slot2 held by x for 400 min — past the 180 min rule on here"),), here)
        assert p.command == "rm -rf /tmp/slots/slot2" and p.host == "here"

    def test_nothing_for_a_warning_a_held_slot_or_an_undeclared_stack(self):
        assert svc.proposals_for((Finding("ci_slot", "CI slot", "ok", "slot1 held by x for 8 min"),), STACK) == []
        assert svc.proposals_for((Finding("ci_slot", "CI slot", "warn", "stale: slot1"),), STACK) == []
        assert svc.proposals_for((Finding("runners", "Runners", "bad", "offline"),), {"hosts": [{"name": "h"}], "ci": [{}]}) == []
        assert svc.proposals_for((Finding("deploy_watch", "Deploy watch", "bad", "x"),), {"hosts": [{"name": "h"}], "deploy": {}}, {"main_sha": "a" * 40}) == []


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "ops.db"))
    yield SQLiteProposalRepository(conn)
    await conn.close()


class TestTheService:
    async def test_raise_once_per_kind_and_host_then_the_owner_decides(self, repo):
        ran = []

        async def runner(host, command):
            ran.append((host["name"], command))
            return "slot1 removed"

        service = svc.ProposalService(repo, STACK, runner)
        first = await service.raise_from((STALE,))
        assert len(first) == 1 and (await service.open())[0].id == first[0].id
        assert await service.raise_from((STALE,)) == []  # one open proposal per kind and host
        done = await service.approve(first[0].id, by="jrechet")
        assert done.status == "run" and done.result == "slot1 removed" and done.decided_by == "jrechet"
        assert ran == [("jrec.fr", "sudo rm -rf /srv/gh-runner-work/ci-slots/slot1")]
        assert await service.open() == []
        assert (await service.recent())[0].id == first[0].id
        again = await service.raise_from((STALE,))  # the slot is stale again: a new proposal
        assert len(again) == 1 and again[0].id != first[0].id
        refused = await service.refuse(again[0].id)
        assert refused.status == "refused" and await service.open() == []
        assert await service.approve(again[0].id) is not None and (await repo.get(again[0].id)).status == "refused"  # a refusal stands

    async def test_a_command_that_fails_or_a_host_out_of_reach_is_the_record(self, repo):
        async def broken(host, command):
            raise RuntimeError("permission denied (publickey)")

        service = svc.ProposalService(repo, STACK, broken)
        [p] = await service.raise_from((STALE,))
        done = await service.approve(p.id)
        assert done.status == "failed" and "permission denied" in done.result
        unreachable = svc.ProposalService(repo, STACK, None)
        [q] = await unreachable.raise_from((STALE,))
        done = await unreachable.approve(q.id)
        assert done.status == "failed" and "not reachable from here" in done.result
        assert await service.approve("nope") is None and await service.refuse("nope") is None

    async def test_the_row_round_trips(self, repo):
        p = d.Proposal(id="rt", kind="clear_slot", host="jrec.fr", title="t", why="w", command="c", finding_key="ci_slot", created_at=NOW)
        await repo.save(p)
        got = await repo.get("rt")
        assert got == p
        await repo.save(p.approved("owner", NOW).ran("ok", True, NOW))
        got = await repo.get("rt")
        assert got.status == "run" and got.ran_at == NOW and got.decided_at == NOW


class TestTheLeash:
    @pytest.mark.parametrize("command", [
        "sudo rm -rf /srv/gh-runner-work/ci-slots/slot1",
        "docker service update --force github_runner_runner_theswarm",
        "docker stack up -c docker-compose.yml theswarm",
        "systemctl restart docker",
        "rm -rf /srv/gh-runner-work",
    ])
    def test_the_machine_verbs_are_refused_to_every_agent(self, command):
        allowed, why = decide_tool_use("edit", "/tmp/ws", "Bash", {"command": command})
        assert not allowed and "proposal" in why

    def test_the_target_s_own_docker_and_tests_still_run(self):
        for command in ("docker compose up -d", "pytest -q", "docker build -t app .", "rm -rf .pytest_cache"):
            allowed, _ = decide_tool_use("edit", "/tmp/ws", "Bash", {"command": command})
            assert allowed, command
