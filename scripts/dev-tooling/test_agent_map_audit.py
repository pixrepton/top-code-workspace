"""Tests for deterministic agent_map_audit (harness navigation map)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
AUDIT = WORKSPACE / "scripts" / "agent_map_audit.py"
SCENARIOS = (
    WORKSPACE
    / "knowledge"
    / "system-atlas"
    / "tooling"
    / "agent-harness"
    / "AGENT_MAP_SCENARIOS.yaml"
)


def test_agent_map_scenarios_file_exists():
    assert SCENARIOS.is_file(), f"missing {SCENARIOS}"


def test_agent_map_audit_passes():
    proc = subprocess.run(
        [sys.executable, str(AUDIT), "--json"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "PASS"
    assert payload["fail"] == 0
    assert payload["scenario_count"] >= 8
    assert payload["core_skill_count"] >= 6


def test_agent_map_audit_covers_mcp_first_exploration():
    proc = subprocess.run(
        [sys.executable, str(AUDIT), "--json"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    joined = "\n".join(payload["oks"])
    assert "explore_unknown_code" in joined
    assert "exploration_policy:skill:Explore via MCP/graph" in joined
    assert "mcp:server:gitnexus" in joined
    assert "mcp:server:codebase-memory" in joined
