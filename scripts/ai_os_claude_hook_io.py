#!/usr/bin/env python3
"""Claude hook payload emission and AI-OS task-state queries."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_hook_common import emit, proc_detail, run_task  # noqa: E402


SOFT_MISS_MARKERS = ("checkpoint not found", "no active task", "multiple active tasks")


def allow(additional_context: str | None = None, event: str | None = None) -> int:
    if additional_context and event:
        return emit(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": additional_context,
                }
            }
        )
    return 0


def deny_pretool(reason: str) -> int:
    return emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def block(reason: str) -> int:
    print(reason, file=sys.stderr)
    return 2


def is_soft_miss(detail: str) -> bool:
    """No single resolvable active task; callers needing a hard failure use guards."""
    lowered = detail.lower()
    return any(marker in lowered for marker in SOFT_MISS_MARKERS)


def task_json(cwd: Path) -> dict[str, Any] | None:
    proc = run_task(["task-status", "--json"], cwd)
    if proc.returncode != 0:
        detail = proc_detail(proc)
        if is_soft_miss(detail):
            return None
        raise RuntimeError(detail)
    return json.loads(proc.stdout)


def compact_summary(data: dict[str, Any]) -> str:
    branches = ", ".join(
        f"{repo}={branch or '<detached>'}" for repo, branch in data.get("current_branches", {}).items()
    )
    base = (
        f"AI-OS task {data.get('task_id')} [{data.get('status')}] route={data.get('task_class')}\n"
        f"phase={data.get('current_phase')} publication={data.get('publication_mode')}\n"
        f"branches={branches or '<none>'}\n"
        f"next={str(data.get('next_action') or '<none>')[:180]}"
    )
    try:
        from ai_os_execution.session_start import project_session_state

        projected = project_session_state(task_id=str(data.get("task_id") or ""))
        inject = str(projected.get("inject") or "").strip()
        if inject:
            return f"{inject}\n\n{base}"
    except Exception:
        pass
    return base


def refresh(cwd: Path, *, strict: bool) -> tuple[bool, str]:
    proc = run_task(["task-checkpoint"], cwd, timeout=8.0)
    if proc.returncode == 0:
        return True, ""
    detail = proc_detail(proc, "task-checkpoint failed")
    if strict:
        return False, detail
    return True, detail


def publication_mode(cwd: Path) -> str:
    data = task_json(cwd)
    return str(data.get("publication_mode", "LOCAL_ONLY")) if data else "LOCAL_ONLY"


def require_resolvable_task(cwd: Path) -> str | None:
    """Return a deny reason when Bash/Edit guards cannot resolve exactly one task."""
    proc = run_task(["task-status", "--json"], cwd)
    if proc.returncode == 0:
        return None
    detail = proc_detail(proc)
    lowered = detail.lower()
    if "multiple active tasks" in lowered:
        return (
            "Multiple active AI-OS tasks are open; set AI_OS_TASK_ID to the owning "
            "task or close/archive the orphans before editing."
        )
    if "no active task" in lowered or "checkpoint not found" in lowered:
        return "No active AI-OS task checkpoint; run task-start with exact repo:path scope before writing."
    return detail or "AI-OS task-status failed"
