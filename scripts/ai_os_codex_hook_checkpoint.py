#!/usr/bin/env python3
"""Checkpoint state reads for the Codex hook, with soft/hard miss taxonomy."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_hook_common import ACTIVE_STATUSES, proc_detail, run_task  # noqa: E402


def classify_task_status_failure(detail: str) -> str:
    """Map task-status errors to a shared soft/hard miss taxonomy."""
    lowered = detail.lower()
    if "corrupt json" in lowered:
        return "corrupt"
    if "multiple active tasks" in lowered:
        return "multiple"
    if "no active task" in lowered or "checkpoint not found" in lowered:
        return "missing"
    return "error"


def checkpoint_state(cwd: Path) -> tuple[str, dict[str, Any] | None, str]:
    proc = run_task(["task-status", "--json"], cwd, timeout=5.0)
    if proc.returncode == 0:
        try:
            return "ok", json.loads(proc.stdout), ""
        except json.JSONDecodeError as exc:
            return "error", None, f"task-status returned invalid JSON: {exc}"
    detail = proc_detail(proc)
    return classify_task_status_failure(detail), None, detail


def checkpoint_is_active(data: dict[str, Any]) -> bool:
    return data.get("status") in ACTIVE_STATUSES


def active_checkpoint(cwd: Path) -> dict[str, Any] | None:
    """Return the checkpoint only when it is readable and in an active status."""
    state, data, _detail = checkpoint_state(cwd)
    if state != "ok" or data is None:
        return None
    return data if checkpoint_is_active(data) else None


def refresh_checkpoint(cwd: Path, *, timeout: float) -> tuple[bool, str]:
    proc = run_task(["task-checkpoint"], cwd, timeout=timeout)
    if proc.returncode == 0:
        return True, ""
    return False, proc_detail(proc, "task-checkpoint failed")


def maybe_resume(cwd: Path) -> tuple[bool, str]:
    proc = run_task(["task-resume"], cwd, timeout=5.0)
    if proc.returncode == 0:
        return True, ""
    return False, proc_detail(proc, "task-resume failed")
