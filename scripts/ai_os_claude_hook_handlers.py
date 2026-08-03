#!/usr/bin/env python3
"""Claude lifecycle event handlers backed by the shared AI-OS task engine."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_claude_hook_io import (  # noqa: E402
    allow,
    block,
    compact_summary,
    refresh,
    task_json,
)
from ai_os_hook_common import ACTIVE_STATUSES, proc_detail, run_task  # noqa: E402


def handle_session_start(cwd: Path) -> int:
    data = task_json(cwd)
    if not data or data.get("status") not in ACTIVE_STATUSES:
        return 0
    refresh(cwd, strict=False)
    data = task_json(cwd) or data
    return allow(compact_summary(data), "SessionStart")


def handle_precompact(cwd: Path) -> int:
    data = task_json(cwd)
    if not data or data.get("status") not in ACTIVE_STATUSES:
        return 0
    ok, detail = refresh(cwd, strict=True)
    return 0 if ok else block(f"AI-OS checkpoint refresh failed before compaction: {detail}")


def handle_post_write(cwd: Path) -> int:
    try:
        data = task_json(cwd)
        if data and data.get("status") in ACTIVE_STATUSES:
            ok, detail = refresh(cwd, strict=False)
            if not ok and detail:
                print(f"AI-OS post-write refresh warning: {detail}", file=sys.stderr)
    except subprocess.TimeoutExpired as exc:
        print(f"AI-OS post-write refresh timed out: {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - never fail the editor tool
        print(f"AI-OS post-write refresh error: {exc}", file=sys.stderr)
    return 0


def commit_plan(cwd: Path, repo: str) -> tuple[dict[str, Any], str | None]:
    """Return (plan, hard_error). A plan with a verdict survives a non-zero exit."""
    proc = run_task(["task-commit-plan", "--repo", repo, "--json"], cwd)
    fallback = f"commit plan failed for {repo}"
    try:
        plan = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}, proc_detail(proc, fallback)
    if proc.returncode == 0:
        return plan, None
    if plan.get("verdict"):
        return plan, None
    return {}, proc_detail(proc, fallback)


def verdict_block_reason(repo: str, plan: dict[str, Any]) -> str | None:
    verdict = plan.get("verdict")
    if verdict == "NO_COMMIT":
        return None
    if verdict == "COMMIT_READY":
        paths = ", ".join(plan.get("owned_paths") or [])
        return (
            f"Task has commit-ready local changes in {repo}: {paths}. "
            "Choose an accurate message and run task-commit, then rerun final post-commit gates."
        )
    if verdict == "BLOCKED":
        return f"Task cannot complete: {'; '.join(plan.get('reasons') or ['commit plan blocked'])}"
    return f"Task cannot complete: unexpected commit-plan verdict for {repo}: {verdict!r}"


def repositories_block_reason(cwd: Path, repositories: Iterable[str]) -> str | None:
    for repo in repositories:
        plan, error = commit_plan(cwd, repo)
        if error:
            return error
        reason = verdict_block_reason(repo, plan)
        if reason:
            return reason
    return None


def closure_block_reason(cwd: Path) -> str | None:
    closure = run_task(["task-close", "--validate-only", "--json"], cwd)
    try:
        result = json.loads(closure.stdout or "{}")
    except json.JSONDecodeError:
        return proc_detail(closure, "task-close validation failed")
    if closure.returncode == 0:
        return None
    return "Task cannot complete: " + "; ".join(result.get("issues") or ["closure validation failed"])


def handle_task_completed(cwd: Path) -> int:
    data = task_json(cwd)
    if not data or data.get("status") != "READY_TO_CLOSE":
        return 0
    reason = repositories_block_reason(cwd, data.get("target_repositories", []))
    if reason is None:
        reason = closure_block_reason(cwd)
    return block(reason) if reason else 0
