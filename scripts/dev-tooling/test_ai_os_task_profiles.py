"""P1: test profiles resolve deterministically and fail closed."""

from __future__ import annotations

import sys

import pytest

from ai_os_task_errors import TaskError
from ai_os_task_profiles import (
    TEST_PROFILES,
    available_profiles,
    resolve_profile,
)


def test_gmail_agent_profiles_exist() -> None:
    profiles = available_profiles("gmail-agent")
    assert "FULL_GATE_A" in profiles
    assert "SPINE_CORE" in profiles
    assert "P1_MULTI_INTENT" in profiles
    assert "P1_EPISTEMIC" in profiles
    assert "HITL_WRITE" in profiles


def test_profile_command_is_deterministic() -> None:
    p1 = resolve_profile("gmail-agent", "P1_MULTI_INTENT")
    p2 = resolve_profile("gmail-agent", "P1_MULTI_INTENT")
    assert p1.command() == p2.command()
    cmd = p1.command()
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "pytest"]
    assert cmd[-2:] == ["-q", "--timeout=120"]


def test_full_gate_a_profile_points_at_whole_suite() -> None:
    p = resolve_profile("gmail-agent", "FULL_GATE_A")
    assert p.pytest_paths == ("tools/gmail_audit/tests",)
    assert p.gate_timeout >= 600


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(TaskError):
        resolve_profile("gmail-agent", "NOT_A_PROFILE")


def test_unknown_repo_fails_closed() -> None:
    with pytest.raises(TaskError):
        resolve_profile("no-such-repo", "FULL_GATE_A")


def test_profile_commands_contain_no_forbidden_markers() -> None:
    from ai_os_task_constants import FORBIDDEN_COMMAND_MARKERS

    for repo, profiles in TEST_PROFILES.items():
        for name, profile in profiles.items():
            rendered = " ".join(profile.command()).lower()
            for marker in FORBIDDEN_COMMAND_MARKERS:
                assert marker not in rendered, f"{repo}:{name} contains forbidden {marker}"
