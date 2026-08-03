#!/usr/bin/env python3
"""Claude Code lifecycle adapter for the shared AI-OS task/Git control engine."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_claude_hook_guards import handle_bash_guard, handle_write_guard  # noqa: E402
from ai_os_claude_hook_handlers import (  # noqa: E402
    handle_post_write,
    handle_precompact,
    handle_session_start,
    handle_task_completed,
)
from ai_os_claude_hook_io import block, refresh  # noqa: E402
from ai_os_hook_common import ROOT  # noqa: E402


WRITE_TOOLS = {"Edit", "Write", "MultiEdit"}
HARD_FAIL_EVENTS = {"PreToolUse", "PreCompact", "TaskCompleted"}


def dispatch_pretool(tool: Any, payload: dict[str, Any], cwd: Path) -> int:
    if tool in WRITE_TOOLS:
        return handle_write_guard(payload, cwd)
    if tool == "Bash":
        return handle_bash_guard(payload, cwd)
    return 0


def dispatch(event: Any, payload: dict[str, Any], cwd: Path) -> int:
    tool = payload.get("tool_name")
    if event == "SessionStart":
        return handle_session_start(cwd)
    if event == "PreCompact":
        return handle_precompact(cwd)
    if event == "PreToolUse":
        return dispatch_pretool(tool, payload, cwd)
    if event == "PostToolUse":
        return handle_post_write(cwd) if tool in WRITE_TOOLS else 0
    if event == "TaskCompleted":
        return handle_task_completed(cwd)
    if event == "SessionEnd":
        refresh(cwd, strict=False)
        return 0
    return 0


def failure_exit(event: Any, message: str) -> int:
    return block(message) if event in HARD_FAIL_EVENTS else 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        return block(f"Invalid Claude hook input: {exc}")
    cwd = Path(str(payload.get("cwd") or ROOT)).resolve()
    event = payload.get("hook_event_name")
    try:
        return dispatch(event, payload, cwd)
    except subprocess.TimeoutExpired:
        return failure_exit(event, "AI-OS Claude hook timed out")
    except Exception as exc:
        return failure_exit(event, f"AI-OS Claude hook failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
