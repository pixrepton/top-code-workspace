"""Deterministic test profiles for task-gate.

Profiles are derived from actually repeated gate commands in the workspace
(AI-OS Intelligence Spine slices). They exist so the agent does not hand-build
long pytest path lists; they never decide what a test result means.

Design rules:
- profiles are repo-scoped data (no second runner, no AI impact engine);
- unknown profile -> TaskError (never a silent empty set);
- FULL_GATE_A stays the canonical full-suite gate;
- profile commands still pass the same forbidden-marker checks as raw commands.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from ai_os_task_errors import TaskError


@dataclass(frozen=True)
class TestProfile:
    description: str
    pytest_paths: tuple[str, ...]
    pytest_args: tuple[str, ...] = ("-q", "--timeout=120")
    # Gate-level timeout in seconds (whole-suite hang protection).
    gate_timeout: int = 300
    env: dict[str, str] = field(default_factory=dict)

    def command(self) -> list[str]:
        return [sys.executable, "-m", "pytest", *self.pytest_paths, *self.pytest_args]


# Repo-scoped profiles. Paths are relative to the repo root (cwd of task-gate).
TEST_PROFILES: dict[str, dict[str, TestProfile]] = {
    "gmail-agent": {
        "P1_MULTI_INTENT": TestProfile(
            description="P1.4 multi-intent contract/projection/draft/runtime slice (31 tests)",
            pytest_paths=(
                "tools/gmail_audit/tests/test_customer_intent_contract.py",
                "tools/gmail_audit/tests/test_multi_intent_projection.py",
                "tools/gmail_audit/tests/test_draft_multi_intent_coverage.py",
                "tools/gmail_audit/tests/test_multi_intent_runtime_slice.py",
            ),
        ),
        "P1_EPISTEMIC": TestProfile(
            description="P1.3 epistemic correctness slice + A1 projection (41 tests)",
            pytest_paths=(
                "tools/gmail_audit/tests/test_epistemic_claims.py",
                "tools/gmail_audit/tests/test_draft_epistemic_guard.py",
                "tools/gmail_audit/tests/test_epistemic_properties.py",
                "tools/gmail_audit/tests/test_epistemic_runtime_slice.py",
                "tools/gmail_audit/tests/test_a1_case_understanding_projection.py",
            ),
        ),
        "SPINE_CORE": TestProfile(
            description="AI-OS Intelligence Spine core regression: P0 CAD, P0.5 boundary, P1.1 revision, P1.2 argument, P1.3 epistemic, P1.4 multi-intent",
            pytest_paths=(
                "tools/gmail_audit/tests/test_canonical_action_decision.py",
                "tools/gmail_audit/tests/test_canonical_action_decision_properties.py",
                "tools/gmail_audit/tests/test_untrusted_input_execution_boundary.py",
                "tools/gmail_audit/tests/test_untrusted_intelligence_context.py",
                "tools/gmail_audit/tests/test_evidence_provenance_roundtrip.py",
                "tools/gmail_audit/tests/test_decision_revision_lifecycle.py",
                "tools/gmail_audit/tests/test_decision_revision_durable_restart.py",
                "tools/gmail_audit/tests/test_decision_revision_stale_guard.py",
                "tools/gmail_audit/tests/test_decision_revision_worker_boot.py",
                "tools/gmail_audit/tests/test_tool_argument_constraints.py",
                "tools/gmail_audit/tests/test_tool_argument_reference_monitor.py",
                "tools/gmail_audit/tests/test_tool_argument_revision_binding.py",
                "tools/gmail_audit/tests/test_tool_argument_properties.py",
                "tools/gmail_audit/tests/test_write_argument_binding.py",
                "tools/gmail_audit/tests/test_epistemic_claims.py",
                "tools/gmail_audit/tests/test_draft_epistemic_guard.py",
                "tools/gmail_audit/tests/test_epistemic_properties.py",
                "tools/gmail_audit/tests/test_epistemic_runtime_slice.py",
                "tools/gmail_audit/tests/test_customer_intent_contract.py",
                "tools/gmail_audit/tests/test_multi_intent_projection.py",
                "tools/gmail_audit/tests/test_draft_multi_intent_coverage.py",
                "tools/gmail_audit/tests/test_multi_intent_runtime_slice.py",
            ),
            gate_timeout=600,
        ),
        "HITL_WRITE": TestProfile(
            description="planner/policy spine + HITL + draft identity + write binding regression",
            pytest_paths=(
                "tools/gmail_audit/tests/test_planner_execution_fidelity_01.py",
                "tools/gmail_audit/tests/test_planner_spine_handoff_closeout.py",
                "tools/gmail_audit/tests/test_slice3b_policy_execution_spine.py",
                "tools/gmail_audit/tests/test_pf01_draft_sanity_coverage.py",
                "tools/gmail_audit/tests/test_generate_draft_reply_contract.py",
                "tools/gmail_audit/tests/test_agent_pr_c.py",
                "tools/gmail_audit/tests/test_agent_hitl_bridge.py",
                "tools/gmail_audit/tests/test_canonical_draft_identity.py",
                "tools/gmail_audit/tests/test_write_argument_binding.py",
            ),
            gate_timeout=600,
        ),
        "FULL_GATE_A": TestProfile(
            description="Full gmail-agent Gate A (entire tools/gmail_audit/tests suite)",
            pytest_paths=("tools/gmail_audit/tests",),
            gate_timeout=900,
        ),
    },
}


def available_profiles(repo: str) -> list[str]:
    return sorted((TEST_PROFILES.get(repo) or {}).keys())


def resolve_profile(repo: str, name: str) -> TestProfile:
    """Resolve a repo-scoped profile or fail closed (never empty)."""
    repo_profiles = TEST_PROFILES.get(repo) or {}
    profile = repo_profiles.get(name)
    if profile is None:
        available = ", ".join(available_profiles(repo)) or "<none>"
        raise TaskError(
            f"unknown test profile '{name}' for repo {repo}; available profiles: {available}"
        )
    return profile


__all__ = ["TestProfile", "TEST_PROFILES", "available_profiles", "resolve_profile"]
