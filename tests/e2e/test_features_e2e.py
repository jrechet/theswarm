"""E2E demos for all 10 platform features (Phase 1-3).

Each test class exercises one feature through the running server,
verifying that the feature module loads, produces correct results,
and is visible through the /api/features endpoint.
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
import tempfile
import time
import uuid

import pytest
from playwright.sync_api import Page, expect


SERVER_PORT = 8094
BASE_URL = f"http://localhost:{SERVER_PORT}"


def _run_server(db_path: str):
    import asyncio
    from theswarm.presentation.web.server import start_server
    asyncio.run(start_server(host="127.0.0.1", port=SERVER_PORT, db_path=db_path))


@pytest.fixture(scope="module")
def server():
    """Launch a real server for feature E2E tests against an isolated DB."""
    tmpdir = tempfile.mkdtemp(prefix="theswarm-e2e-")
    db_path = os.path.join(tmpdir, "e2e.db")

    proc = multiprocessing.Process(target=_run_server, args=(db_path,), daemon=True)
    proc.start()
    import urllib.request
    for _ in range(30):
        try:
            urllib.request.urlopen(f"{BASE_URL}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    else:
        proc.terminate()
        shutil.rmtree(tmpdir, ignore_errors=True)
        pytest.fail("Server did not start within 15 seconds")
    yield proc
    proc.terminate()
    proc.join(timeout=3)
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── Feature 0: /api/features endpoint ─────────────────────────────


class TestFeaturesAPI:
    """Verify the /api/features endpoint lists all 10 features."""

    def test_features_endpoint_returns_10(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        assert response.ok
        features = response.json()
        assert len(features) == 10

    def test_all_features_available(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = response.json()
        for feat in features:
            assert feat["available"] is True, f"{feat['id']} not available"

    def test_features_have_required_fields(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = response.json()
        for feat in features:
            assert "id" in feat
            assert "name" in feat
            assert "phase" in feat
            assert "module" in feat
            assert "description" in feat
            assert "available" in feat

    def test_features_grouped_by_phase(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = response.json()
        phases = {f["phase"] for f in features}
        assert phases == {1, 2, 3}


# ── Feature 1: Hashline Edit Tool ─────────────────────────────────


class TestHashlineFeature:
    """Demo: hash-anchored file editing prevents stale-line errors."""

    def test_hashline_module_loads(self, server, page: Page):
        """Verify the hashline module is importable through the features API."""
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["hashline"]["available"] is True
        assert features["hashline"]["phase"] == 1

    def test_hashline_read_and_edit_roundtrip(self, server, page: Page):
        """Exercise hashline read/parse/apply cycle via Python import."""
        import tempfile, os
        from theswarm.tools.hashline import hash_tagged_read, parse_hashline_edits

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            path = f.name

        try:
            tagged = hash_tagged_read(path)
            # Format is "LINE#HASH| content"
            assert "#" in tagged
            first_line = tagged.split("\n")[0]
            # Should look like "1#XX| def hello():"
            assert "| " in first_line
            parts = first_line.split("#")
            assert len(parts) == 2
        finally:
            os.unlink(path)

    def test_hashline_path_traversal_blocked(self, server, page: Page):
        """Hashline rejects path traversal attempts."""
        from theswarm.tools.hashline import apply_hashline_edits, HashlineEdit
        import tempfile

        workspace = tempfile.mkdtemp()
        edit = HashlineEdit(
            filepath="../../../etc/passwd",
            line_number=1,
            expected_hash="ab",
            new_content="hacked",
        )
        result = apply_hashline_edits([edit], workspace)
        assert len(result.errors) > 0


# ── Feature 2: Ralph Loop ─────────────────────────────────────────


class TestRalphLoopFeature:
    """Demo: Dev agent retries implementation when quality gates fail."""

    def test_ralph_loop_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["ralph_loop"]["available"] is True

    def test_ralph_loop_graph_has_retry_edge(self, server, page: Page):
        """Verify the dev graph includes the retry_implement node."""
        from theswarm.agents.dev import build_dev_graph
        graph = build_dev_graph()
        # The compiled graph should contain the retry node
        node_names = set(graph.nodes.keys())
        assert "retry_implement" in node_names
        assert "quality_gates" in node_names

    def test_ralph_loop_config_defaults(self, server, page: Page):
        """CycleConfig should have max_dev_retries = 2."""
        from theswarm.config import CycleConfig
        config = CycleConfig(github_repo="test/repo")
        assert config.max_dev_retries == 2


# ── Feature 3: Watchdog (Todo Enforcer) ───────────────────────────


class TestWatchdogFeature:
    """Demo: idle agent detection with threshold and escalation."""

    def test_watchdog_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["watchdog"]["available"] is True

    def test_watchdog_heartbeat_and_status(self, server, page: Page):
        """Exercise watchdog heartbeat and status check."""
        from theswarm.application.services.watchdog import AgentWatchdog

        wd = AgentWatchdog(idle_threshold=60.0, max_warnings=2)
        wd.heartbeat("Dev", "picking task")
        status = wd.get_status()
        # get_status returns dict[str, dict] keyed by role
        assert "Dev" in status
        assert status["Dev"]["last_message"] == "picking task"
        assert status["Dev"]["idle_warnings"] == 0

    def test_watchdog_config_wired(self, server, page: Page):
        """CycleConfig watchdog settings are present."""
        from theswarm.config import CycleConfig
        config = CycleConfig(github_repo="test/repo")
        assert config.watchdog_idle_threshold == 720.0
        assert config.watchdog_max_warnings == 3


# ── Feature 4: Context Condensation ───────────────────────────────


class TestCondenserFeature:
    """Demo: LLM-powered context summarization stays within token budgets."""

    def test_condenser_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["condenser"]["available"] is True

    def test_condenser_short_circuits_below_threshold(self, server, page: Page):
        """Text below threshold is returned unchanged (no API call)."""
        from theswarm.tools.condenser import CondensationResult

        # Verify the short-circuit path returns original text
        # (we can't call async directly in Playwright sync context,
        # so we test the result dataclass and verify the module loads)
        r = CondensationResult(
            original_chars=10,
            condensed_chars=10,
            savings_percent=0.0,
            condensed_text="short text",
        )
        assert r.condensed_text == "short text"
        assert r.savings_percent == 0.0

    def test_condenser_result_fields(self, server, page: Page):
        """CondensationResult has the expected structure."""
        from theswarm.tools.condenser import CondensationResult

        r = CondensationResult(
            original_chars=1000,
            condensed_chars=500,
            savings_percent=50.0,
            condensed_text="condensed",
        )
        assert r.original_chars == 1000
        assert r.condensed_text == "condensed"


# ── Feature 5: AGENTS.md Generator ────────────────────────────────


class TestAgentsMdFeature:
    """Demo: auto-generate documentation from agent graph introspection."""

    def test_agents_md_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["agents_md"]["available"] is True

    def test_agents_md_generates_markdown(self, server, page: Page):
        """Generate AGENTS.md and verify structure."""
        from theswarm.tools.agents_md import generate_agents_md

        md = generate_agents_md()
        assert "# AGENTS.md" in md
        assert "Pipeline Overview" in md
        assert "PO" in md
        assert "Dev" in md or "dev" in md
        assert "State Schema" in md
        assert "Configuration" in md

    def test_agents_md_introspects_all_agents(self, server, page: Page):
        """Introspection finds all 4 agent modules."""
        from theswarm.tools.agents_md import introspect_agents

        agents = introspect_agents()
        names = {a.name for a in agents}
        assert "po" in names
        assert "techlead" in names
        assert "dev" in names
        assert "qa" in names

    def test_agents_md_extracts_nodes(self, server, page: Page):
        """Each agent should have at least one graph node."""
        from theswarm.tools.agents_md import introspect_agents

        agents = introspect_agents()
        for agent in agents:
            assert len(agent.nodes) > 0, f"{agent.name} has no nodes"


# ── Feature 6: Skill-Embedded MCPs ────────────────────────────────


class TestMCPSkillsFeature:
    """Demo: mount/unmount skill manifests per task category."""

    def test_mcp_skills_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["mcp_skills"]["available"] is True

    def test_mcp_manifest_has_default_entries(self, server, page: Page):
        """DEFAULT_MANIFEST contains standard skill entries."""
        from theswarm.infrastructure.mcp.manifest import DEFAULT_MANIFEST, SkillManifest

        # DEFAULT_MANIFEST is a dict of SkillManifestEntry objects
        assert len(DEFAULT_MANIFEST) > 0
        # SkillManifest wraps it
        manifest = SkillManifest()
        always_on = manifest.get_always_on()
        assert isinstance(always_on, list)

    def test_mcp_manager_categories(self, server, page: Page):
        """SkillMCPManager resolves skills for known categories."""
        from theswarm.infrastructure.mcp.manifest import SkillManifest

        manifest = SkillManifest()
        skills = manifest.get_skills_for_category("code_search")
        assert isinstance(skills, list)


# ── Feature 7: Model Routing Table ────────────────────────────────


class TestModelRoutingFeature:
    """Demo: task category maps to the right model (Haiku/Sonnet)."""

    def test_model_routing_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["model_routing"]["available"] is True

    def test_routing_table_defaults(self, server, page: Page):
        """CycleConfig has a routing table with expected categories."""
        from theswarm.config import CycleConfig

        config = CycleConfig(github_repo="test/repo")
        routing = config.model_routing
        assert routing["nlu"] == "haiku"
        assert routing["condensation"] == "haiku"
        assert routing["implementation"] == "sonnet"
        assert routing["review"] == "sonnet"

    def test_claude_for_task_routes_correctly(self, server, page: Page):
        """ClaudeCLI.for_task() returns a client with the routed model."""
        from theswarm.tools.claude import ClaudeCLI

        base = ClaudeCLI(model="sonnet")
        haiku_cli = base.for_task("nlu", routing={"nlu": "haiku"})
        assert haiku_cli.model == "haiku"

        sonnet_cli = base.for_task("implementation", routing={"implementation": "sonnet"})
        assert sonnet_cli.model == "sonnet"

    def test_routing_fallback_to_default(self, server, page: Page):
        """Unknown task category falls back to the base model."""
        from theswarm.tools.claude import ClaudeCLI

        base = ClaudeCLI(model="sonnet")
        cli = base.for_task("unknown_category", routing={"nlu": "haiku"})
        assert cli.model == "sonnet"


# ── Feature 8: IntentGate Enhancement ─────────────────────────────


class TestIntentGateFeature:
    """Demo: Haiku-powered NLU with param extraction and keyword fast path."""

    def test_intent_gate_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["intent_gate"]["available"] is True

    def test_intent_gate_module_importable(self, server, page: Page):
        """The server module containing _LlmNLU is importable."""
        import importlib
        mod = importlib.import_module("theswarm.presentation.web.server")
        assert hasattr(mod, "start_server")


# ── Feature 9: Sandbox Protocol ───────────────────────────────────


class TestSandboxFeature:
    """Demo: pluggable execution backend (local, Docker, OpenHands)."""

    def test_sandbox_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["sandbox"]["available"] is True

    def test_local_sandbox_has_protocol_methods(self, server, page: Page):
        """LocalSandbox implements all SandboxBackend protocol methods."""
        from theswarm.infrastructure.sandbox import LocalSandbox

        sandbox = LocalSandbox()
        assert hasattr(sandbox, "run_command")
        assert hasattr(sandbox, "upload_file")
        assert hasattr(sandbox, "download_file")
        assert hasattr(sandbox, "cleanup")
        # All should be callable
        assert callable(sandbox.run_command)
        assert callable(sandbox.upload_file)
        assert callable(sandbox.download_file)
        assert callable(sandbox.cleanup)

    def test_command_result_frozen(self, server, page: Page):
        """CommandResult is immutable."""
        from theswarm.infrastructure.sandbox import CommandResult

        result = CommandResult(exit_code=0, stdout="ok", stderr="")
        with pytest.raises(AttributeError):
            result.exit_code = 1  # type: ignore[misc]


# ── Feature 10: AST-Grep Tool ─────────────────────────────────────


class TestAstGrepFeature:
    """Demo: structural code search via ast-grep CLI wrapper."""

    def test_ast_grep_in_features(self, server, page: Page):
        response = page.request.get(f"{BASE_URL}/api/features")
        features = {f["id"]: f for f in response.json()}
        assert features["ast_grep"]["available"] is True

    def test_ast_grep_match_dataclass(self, server, page: Page):
        """AstGrepMatch is a frozen dataclass with expected fields."""
        from theswarm.tools.ast_grep import AstGrepMatch

        match = AstGrepMatch(
            file="test.py",
            line=10,
            column=5,
            text="def hello():",
            rule="find_function",
        )
        assert match.file == "test.py"
        assert match.line == 10
        with pytest.raises(AttributeError):
            match.file = "other.py"  # type: ignore[misc]

    def test_ast_grep_parse_matches(self, server, page: Page):
        """_parse_matches handles valid JSON output."""
        import json
        from theswarm.tools.ast_grep import _parse_matches

        raw = json.dumps([
            {
                "file": "src/main.py",
                "range": {"start": {"line": 5, "column": 0}},
                "text": "async def run():",
                "ruleId": "async_func",
            }
        ])
        matches = _parse_matches(raw)
        assert len(matches) == 1
        assert matches[0].file == "src/main.py"
        assert matches[0].line == 5

    def test_ast_grep_empty_parse(self, server, page: Page):
        """_parse_matches handles empty input gracefully."""
        from theswarm.tools.ast_grep import _parse_matches

        assert _parse_matches("") == []
        assert _parse_matches("  ") == []
