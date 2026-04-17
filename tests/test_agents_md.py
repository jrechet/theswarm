"""Tests for theswarm.tools.agents_md — AGENTS.md auto-generator."""

from __future__ import annotations

from theswarm.tools.agents_md import (
    AgentInfo,
    _extract_nodes,
    _extract_tools,
    generate_agents_md,
    introspect_agents,
)


# ── Unit tests for helpers ────────────────────────────────────────


class TestExtractNodes:
    def test_finds_add_node_calls(self) -> None:
        source = '''
graph.add_node("load_context", load_context)
graph.add_node("pick_task", pick_task)
graph.add_node("implement", implement_task)
'''
        nodes = _extract_nodes(source)
        assert nodes == ["load_context", "pick_task", "implement"]

    def test_single_quotes(self) -> None:
        source = "graph.add_node('run_tests', run_tests)"
        assert _extract_nodes(source) == ["run_tests"]

    def test_empty_source(self) -> None:
        assert _extract_nodes("") == []


class TestExtractTools:
    def test_finds_tool_imports(self) -> None:
        source = """
from theswarm.tools.github import GitHubClient
from theswarm.tools.claude import ClaudeCLI
"""
        tools = _extract_tools(source)
        assert tools == ["claude", "github"]

    def test_finds_git_tool(self) -> None:
        source = "from theswarm.tools.git import clone_repo"
        assert _extract_tools(source) == ["git"]

    def test_no_tools(self) -> None:
        source = "import json\nimport logging"
        assert _extract_tools(source) == []


# ── Integration tests ─────────────────────────────────────────────


class TestIntrospectAgents:
    def test_returns_all_four_agents(self) -> None:
        agents = introspect_agents()
        names = [a.name for a in agents]
        assert "po" in names
        assert "techlead" in names
        assert "dev" in names
        assert "qa" in names

    def test_agents_have_nodes(self) -> None:
        agents = introspect_agents()
        for agent in agents:
            assert len(agent.nodes) > 0, f"{agent.name} should have graph nodes"

    def test_agents_have_descriptions(self) -> None:
        agents = introspect_agents()
        for agent in agents:
            assert agent.description, f"{agent.name} should have a description"

    def test_all_agents_have_load_context_node(self) -> None:
        agents = introspect_agents()
        for agent in agents:
            assert "load_context" in agent.nodes, (
                f"{agent.name} should have load_context node"
            )

    def test_missing_module_is_skipped(self) -> None:
        agents = introspect_agents(["theswarm.agents.nonexistent"])
        assert agents == []


class TestGenerateAgentsMd:
    def test_produces_valid_markdown(self) -> None:
        md = generate_agents_md()
        assert md.startswith("# AGENTS.md")
        assert "## Pipeline Overview" in md

    def test_contains_agent_sections(self) -> None:
        md = generate_agents_md()
        assert "## PO Agent" in md
        assert "## Techlead Agent" in md
        assert "## Dev Agent" in md
        assert "## QA Agent" in md

    def test_contains_state_schema(self) -> None:
        md = generate_agents_md()
        assert "## State Schema" in md
        assert "| `team_id`" in md
        assert "| `github_repo`" in md

    def test_contains_configuration(self) -> None:
        md = generate_agents_md()
        assert "## Configuration" in md
        assert "CycleConfig" in md

    def test_accepts_custom_agents(self) -> None:
        custom = [
            AgentInfo(
                name="custom",
                module_path="my.module",
                nodes=["step_a", "step_b"],
                tools_used=["github"],
                description="A custom agent.",
            )
        ]
        md = generate_agents_md(custom)
        assert "## Custom Agent" in md
        assert "- `step_a`" in md
        assert "`github`" in md
        assert "A custom agent." in md

    def test_auto_generated_notice(self) -> None:
        md = generate_agents_md()
        assert "Auto-generated" in md
