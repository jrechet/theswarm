"""Settings → Agents: each persona's Claude model and effort, the owner's choice.

The settings are kept per persona (v037); a cycle reads them when it starts
and hands each agent its own Claude — the base one on the chosen model and
effort, its progress callback and learned timeout kept; the effort reaches
Claude Code as `--effort`. A persona nobody set runs on the instance's
model, as every call did before. Before this, the per-role models a project
carried were computed and dropped: every agent ran on `SWARM_CLAUDE_MODEL`.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from theswarm import api as api_module
from theswarm.application.events.bus import EventBus
from theswarm.application.services.agent_settings import AgentSettingsService
from theswarm.config import CycleConfig
from theswarm.cycle_graph import CycleRuntime, _claude_for
from theswarm.domain.agents.settings import AgentSetting, AgentSettingError
from theswarm.infrastructure.persistence.agent_settings_repo import SQLiteAgentSettingsRepository
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.tools.claude import ClaudeCLI


class TestTheSetting:
    def test_a_persona_a_model_alias_and_an_effort(self):
        s = AgentSetting(persona="dev", model="opus", effort="high")
        assert (s.persona, s.model, s.effort) == ("dev", "opus", "high")
        assert AgentSetting(persona="qa", model="haiku").effort == ""
        for bad in (dict(persona="cto", model="opus"), dict(persona="dev", model="claude-opus-5"),
                    dict(persona="dev", model="opus", effort="extreme")):
            with pytest.raises(AgentSettingError):
                AgentSetting(**bad)


@pytest.fixture()
async def service(tmp_path):
    conn = await init_db(str(tmp_path / "agents.db"))
    yield AgentSettingsService(SQLiteAgentSettingsRepository(conn))
    await conn.close()


class TestTheService:
    async def test_saved_read_back_and_put_back_on_the_instance_s_model(self, service, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_MODEL", "sonnet")
        assert await service.effective() == {}
        await service.save_all({"dev": ("opus", "high"), "qa": ("haiku", "low"), "po": ("", "")}, by="jrechet")
        assert await service.effective() == {"dev": ("opus", "high"), "qa": ("haiku", "low")}
        assert service.snapshot()["dev"].updated_by == "jrechet"
        await service.save_all({"dev": ("", "")})
        assert await service.effective() == {"qa": ("haiku", "low")}

    async def test_the_claude_of_a_call_outside_the_cycle(self, service, monkeypatch):
        monkeypatch.setenv("SWARM_CLAUDE_MODEL", "sonnet")
        await service.save_all({"devops": ("opus", "max")})
        devops = service.claude_for("devops")
        assert (devops.model, devops.effort) == ("opus", "max")
        po = service.claude_for("po", base_model="haiku")  # nobody set the PO: SWARM_SUMMARY_MODEL, then the instance's model
        assert (po.model, po.effort) == ("haiku", "")
        assert service.claude_for("qa").model == "sonnet"


class TestTheClaudeWrapper:
    def test_a_persona_s_claude_keeps_the_base_one_s_callback_and_floor(self):
        async def heard(_):
            return None

        base = ClaudeCLI(model="sonnet", on_event=heard, timeout=300)
        base._timeout_floor = 420
        dev = base.with_settings("opus", "high")
        assert (dev.model, dev.effort, dev.on_event, dev._timeout_floor, dev.timeout) == ("opus", "high", heard, 420, 300)
        assert base.model == "sonnet" and base.effort == ""  # the base is untouched
        assert base.with_settings("", "").model == "sonnet"

    def test_the_effort_reaches_claude_code_and_nothing_is_sent_without_one(self):
        opts = ClaudeCLI(model="opus", effort="high")._sdk_options("text", None, "claude-opus-5", drop_oauth_env=False, resume=None)
        assert opts.effort == "high" and opts.model == "claude-opus-5"
        assert ClaudeCLI()._sdk_options("text", None, "claude-sonnet-5", drop_oauth_env=False, resume=None).effort is None


def _runtime(settings: dict, base=None) -> CycleRuntime:
    return CycleRuntime(config=CycleConfig(github_repo="o/r", agent_settings=settings),
                        base_state={"claude": base}, progress=AsyncMock())


class TestInTheCycle:
    def test_each_persona_gets_its_claude_once_per_cycle(self):
        base = ClaudeCLI(model="sonnet")
        rt = _runtime({"dev": ("opus", "high"), "qa": ("haiku", "low")}, base)
        dev = _claude_for(rt, "dev")
        assert (dev.model, dev.effort) == ("opus", "high") and _claude_for(rt, "dev") is dev
        assert (_claude_for(rt, "qa").model, _claude_for(rt, "qa").effort) == ("haiku", "low")
        assert _claude_for(rt, "po") is base and _claude_for(rt, "techlead") is base  # nobody set them

    def test_stub_mode_and_no_settings_keep_the_base(self):
        assert _claude_for(_runtime({"dev": ("opus", "high")}, None), "dev") is None
        base = ClaudeCLI()
        assert _claude_for(_runtime({}, base), "dev") is base

    def test_every_agent_of_the_graph_is_handed_its_persona_s_claude(self):
        import inspect

        from theswarm import cycle_graph

        source = inspect.getsource(cycle_graph)
        assert source.count("_invoke_agent(_cycle().build_") == source.count('"claude": _claude_for(rt, ')
        for role in ("po", "techlead", "dev", "qa"):
            assert f'"claude": _claude_for(rt, "{role}")' in source


class TestTheApiCycle:
    @pytest.fixture(autouse=True)
    def _hook(self):
        api_module.set_agent_settings(None)
        yield
        api_module.set_agent_settings(None)

    async def test_a_cycle_reads_the_settings_when_it_starts(self):
        seen = {}

        async def daily(config, **kw):
            seen["settings"] = dict(config.agent_settings)
            return {"cost_usd": 0.0, "prs": [], "date": "2026-10-09"}

        api_module.set_agent_settings(SimpleNamespace(effective=AsyncMock(return_value={"dev": ("opus", "high")})))
        with patch("theswarm.cycle.run_daily_cycle", new=daily):
            await api_module.run_api_cycle(cycle_id="abc123abc125", repo="o/r", description="Play", callback_url="",
                                           allowed_repos=[], event_bus=EventBus())
        assert seen["settings"] == {"dev": ("opus", "high")}

    async def test_a_failing_read_leaves_every_persona_on_the_instance_s_model(self):
        seen = {}

        async def daily(config, **kw):
            seen["settings"] = dict(config.agent_settings)
            return {"cost_usd": 0.0, "prs": [], "date": "2026-10-09"}

        api_module.set_agent_settings(SimpleNamespace(effective=AsyncMock(side_effect=RuntimeError("database is locked"))))
        with patch("theswarm.cycle.run_daily_cycle", new=daily):
            await api_module.run_api_cycle(cycle_id="abc123abc126", repo="o/r", description="Play", callback_url="",
                                           allowed_repos=[], event_bus=EventBus())
        assert seen["settings"] == {}


class TestWhatTheCycleSays:
    @pytest.fixture(autouse=True)
    def _hook(self):
        api_module.set_agent_settings(None)
        yield
        api_module.set_agent_settings(None)

    async def test_the_cycle_tells_what_each_agent_runs_on(self):
        from theswarm.domain.cycles.events import AgentActivity

        bus = EventBus()
        told = []

        async def keep(e):
            if isinstance(e, AgentActivity) and e.action == "agent_models":
                told.append(e)

        bus.subscribe_all(keep)
        api_module.set_agent_settings(SimpleNamespace(effective=AsyncMock(return_value={"dev": ("opus", "high"), "qa": ("haiku", "low")})))
        with patch("theswarm.cycle.run_daily_cycle", new=AsyncMock(return_value={"cost_usd": 0.0, "prs": [], "date": "2026-10-09"})):
            await api_module.run_api_cycle(cycle_id="abc123abc127", repo="o/r", description="Play", callback_url="",
                                           allowed_repos=[], event_bus=bus)
        [act] = told
        assert act.agent == "system" and str(act.cycle_id) == "abc123abc127"
        assert act.metadata == {"po": {"model": "sonnet", "effort": ""}, "techlead": {"model": "sonnet", "effort": ""},
                                "dev": {"model": "opus", "effort": "high"}, "qa": {"model": "haiku", "effort": "low"}}
        assert act.detail == "The agents run on: Product Owner Sonnet, Tech Lead Sonnet, Developer Opus · high, QA Haiku · low"

    async def test_nothing_is_told_without_settings(self):
        from theswarm.domain.cycles.events import AgentActivity

        bus = EventBus()
        told = []

        async def keep(e):
            if isinstance(e, AgentActivity) and e.action == "agent_models":
                told.append(e)

        bus.subscribe_all(keep)
        with patch("theswarm.cycle.run_daily_cycle", new=AsyncMock(return_value={"cost_usd": 0.0, "prs": [], "date": "2026-10-09"})):
            await api_module.run_api_cycle(cycle_id="abc123abc128", repo="o/r", description="Play", callback_url="",
                                           allowed_repos=[], event_bus=bus)
        assert told == []  # the CLI, the tests: no Settings → Agents, no line
