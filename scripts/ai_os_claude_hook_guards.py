#!/usr/bin/env python3
"""PreToolUse guards for Claude Bash and file-write tools."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_claude_hook_io import (  # noqa: E402
    deny_pretool,
    publication_mode,
    require_resolvable_task,
)
from ai_os_hook_common import proc_detail, run_task  # noqa: E402


DESTRUCTIVE_PATTERNS = (
    (re.compile(r"(^|[;&|]\s*)git\s+reset(?:\s|$)", re.I), "git reset is not allowed; preserve the shared working tree"),
    (re.compile(r"(^|[;&|]\s*)git\s+clean(?:\s|$)", re.I), "git clean is not allowed; inspect untracked files instead"),
    (re.compile(r"(^|[;&|]\s*)git\s+push\b[^\n]*(?:--force(?:-with-lease)?|-f)(?:\s|$)", re.I), "force push is forbidden"),
    (re.compile(r"(^|[;&|]\s*)git\s+stash\s+(?:drop|clear)(?:\s|$)", re.I), "stash deletion is forbidden"),
    (re.compile(r"(^|[;&|]\s*)git\s+branch\s+-D(?:\s|$)", re.I), "forced branch deletion is forbidden"),
    (re.compile(r"(^|[;&|]\s*)git\s+(?:checkout\s+--|restore\b)", re.I), "destructive checkout/restore must be handled manually after reviewing impact"),
)
RAW_GIT_PATTERNS = (
    (
        re.compile(r"(^|[;&|]\s*)git\s+add(?:\s|$)", re.I),
        "Raw git add is disabled for agent work. Use scripts/ai_os_task.py task-commit.",
    ),
    (
        re.compile(r"(^|[;&|]\s*)git\s+commit(?:\s|$)", re.I),
        "Raw git commit is disabled for agent work. Run task-commit-plan, then task-commit.",
    ),
)
PUBLICATION_PATTERNS = (
    (
        re.compile(r"(^|[;&|]\s*)git\s+push(?:\s|$)", re.I),
        "Push is outside LOCAL_ONLY mode. Change the checkpoint to PUBLISH or SHIP first.",
    ),
    (
        re.compile(r"(^|[;&|]\s*)gh\s+pr\s+create(?:\s|$)", re.I),
        "PR creation is outside LOCAL_ONLY mode. Change the checkpoint to PUBLISH or SHIP first.",
    ),
)
MERGE_PATTERNS = (
    (
        re.compile(r"(^|[;&|]\s*)gh\s+pr\s+merge(?:\s|$)", re.I),
        "PR merge remains a separate operator-approved action; SHIP mode does not auto-authorize merge.",
    ),
)

Rules = Iterable[tuple[re.Pattern[str], str]]


def first_match_reason(command: str, rules: Rules) -> str | None:
    for pattern, reason in rules:
        if pattern.search(command):
            return reason
    return None


def publication_denial(command: str, cwd: Path) -> str | None:
    """Deny push/PR-create while the checkpoint stays in LOCAL_ONLY."""
    for pattern, reason in PUBLICATION_PATTERNS:
        if not pattern.search(command):
            continue
        unresolved = require_resolvable_task(cwd)
        if unresolved:
            return unresolved
        if publication_mode(cwd) == "LOCAL_ONLY":
            return reason
    return None


def bash_denial(command: str, cwd: Path) -> str | None:
    reason = first_match_reason(command, DESTRUCTIVE_PATTERNS)
    if reason is None:
        reason = first_match_reason(command, RAW_GIT_PATTERNS)
    if reason is None:
        reason = publication_denial(command, cwd)
    if reason is None:
        reason = first_match_reason(command, MERGE_PATTERNS)
    return reason


def handle_bash_guard(payload: dict[str, Any], cwd: Path) -> int:
    tool_input = payload.get("tool_input") or {}
    reason = bash_denial(str(tool_input.get("command") or ""), cwd)
    return deny_pretool(reason) if reason else 0


def write_denial(payload: dict[str, Any], cwd: Path) -> str | None:
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path")
    if not isinstance(path, str) or not path:
        return "Cannot resolve the target file path; use a scoped write with an active AI-OS task checkpoint."
    unresolved = require_resolvable_task(cwd)
    if unresolved:
        return unresolved
    proc = run_task(["task-guard-write", "--path", path], cwd)
    if proc.returncode == 0:
        return None
    return proc_detail(proc, "AI-OS write guard denied the edit")


def handle_write_guard(payload: dict[str, Any], cwd: Path) -> int:
    reason = write_denial(payload, cwd)
    return deny_pretool(reason) if reason else 0
