"""Tests for commit decision evaluation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from ai_os_task_commit_decision import (  # noqa: E402
    DECISION_COMMIT_LATER,
    DECISION_COMMIT_NOW,
    DECISION_NO_COMMIT,
    evaluate_commit_decision,
)


def _base_checkpoint(**overrides):
    data = {
        "task_id": "TEST-001",
        "status": "IN_PROGRESS",
        "next_action": "",
        "publication_mode": "LOCAL_ONLY",
        "target_repositories": ["workspace"],
        "declared_write_scope": [{"repo": "workspace", "path": "scripts"}],
        "own_staged_files": [],
        "own_unstaged_files": ["workspace:scripts/foo.py"],
        "own_untracked_files": [],
        "ownership_conflicts": [],
    }
    data.update(overrides)
    return data


def test_no_commit_when_plan_empty():
    plan = {"verdict": "NO_COMMIT", "owned_paths": [], "reasons": [], "warnings": []}
    decision = evaluate_commit_decision(_base_checkpoint(), "workspace", plan)
    assert decision["decision"] == DECISION_NO_COMMIT


def test_commit_later_when_blocked():
    plan = {
        "verdict": "BLOCKED",
        "owned_paths": ["scripts/foo.py"],
        "reasons": ["stale gate"],
        "warnings": [],
    }
    decision = evaluate_commit_decision(_base_checkpoint(), "workspace", plan)
    assert decision["decision"] == DECISION_COMMIT_LATER
    assert "stale gate" in decision["blockers"]


def test_commit_now_when_ready():
    plan = {
        "verdict": "COMMIT_READY",
        "owned_paths": ["scripts/foo.py"],
        "reasons": [],
        "warnings": [],
    }
    decision = evaluate_commit_decision(_base_checkpoint(), "workspace", plan)
    assert decision["decision"] == DECISION_COMMIT_NOW
    assert decision["ask_operator"] is False


def test_commit_later_when_next_action_set():
    plan = {
        "verdict": "COMMIT_READY",
        "owned_paths": ["scripts/foo.py"],
        "reasons": [],
        "warnings": [],
    }
    data = _base_checkpoint(next_action="finish inject hook")
    decision = evaluate_commit_decision(data, "workspace", plan)
    assert decision["decision"] == DECISION_COMMIT_LATER


def test_commit_later_when_path_outside_scope():
    plan = {
        "verdict": "COMMIT_READY",
        "owned_paths": [".cursor/mcp.json"],
        "reasons": [],
        "warnings": [],
    }
    decision = evaluate_commit_decision(_base_checkpoint(), "workspace", plan)
    assert decision["decision"] == DECISION_COMMIT_LATER
    assert decision["paths_outside_scope"] == [".cursor/mcp.json"]
