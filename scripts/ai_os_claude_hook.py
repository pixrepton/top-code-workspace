#!/usr/bin/env python3
"""Claude Code lifecycle adapter for the shared AI-OS task/Git control engine."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASK_SCRIPT = ROOT / "scripts" / "ai_os_task.py"
ACTIVE_STATUSES = {"INITIALIZED", "IN_PROGRESS", "BLOCKED", "READY_TO_CLOSE"}
DESTRUCTIVE_PATTERNS = (
    (re.compile(r"(^|[;&|]\s*)git\s+reset(?:\s|$)", re.I), "git reset is not allowed; preserve the shared working tree"),
    (re.compile(r"(^|[;&|]\s*)git\s+clean(?:\s|$)", re.I), "git clean is not allowed; inspect untracked files instead"),
    (re.compile(r"(^|[;&|]\s*)git\s+push\b[^\n]*(?:--force(?:-with-lease)?|-f)(?:\s|$)", re.I), "force push is forbidden"),
    (re.compile(r"(^|[;&|]\s*)git\s+stash\s+(?:drop|clear)(?:\s|$)", re.I), "stash deletion is forbidden"),
    (re.compile(r"(^|[;&|]\s*)git\s+branch\s+-D(?:\s|$)", re.I), "forced branch deletion is forbidden"),
    (re.compile(r"(^|[;&|]\s*)git\s+(?:checkout\s+--|restore\b)", re.I), "destructive checkout/restore must be handled manually after reviewing impact"),
)


def emit(payload: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return 0


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


def run_task(args: list[str], cwd: Path, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TASK_SCRIPT), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
        env=os.environ.copy(),
    )


def task_json(cwd: Path) -> dict[str, Any] | None:
    proc = run_task(["task-status", "--json"], cwd)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        lowered = detail.lower()
        # Soft-miss cases: no single resolvable active task. Callers that need a
        # hard failure (write/bash guards) go through task-guard-write / deny.
        if (
            "checkpoint not found" in lowered
            or "no active task" in lowered
            or "multiple active tasks" in lowered
        ):
            return None
        raise RuntimeError(detail)
    return json.loads(proc.stdout)


def compact_summary(data: dict[str, Any]) -> str:
    branches = ", ".join(
        f"{repo}={branch or '<detached>'}" for repo, branch in data.get("current_branches", {}).items()
    )
    return (
        f"AI-OS task {data.get('task_id')} [{data.get('status')}] route={data.get('task_class')}\n"
        f"phase={data.get('current_phase')} publication={data.get('publication_mode')}\n"
        f"branches={branches or '<none>'}\n"
        f"next={str(data.get('next_action') or '<none>')[:180]}"
    )


def refresh(cwd: Path, *, strict: bool) -> tuple[bool, str]:
    proc = run_task(["task-checkpoint"], cwd, timeout=8.0)
    if proc.returncode == 0:
        return True, ""
    detail = (proc.stderr or proc.stdout).strip() or "task-checkpoint failed"
    if strict:
        return False, detail
    return True, detail


def publication_mode(cwd: Path) -> str:
    data = task_json(cwd)
    return str(data.get("publication_mode", "LOCAL_ONLY")) if data else "LOCAL_ONLY"


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


def _require_resolvable_task(cwd: Path) -> str | None:
    """Return a deny reason when Bash/Edit guards cannot resolve exactly one task."""
    proc = run_task(["task-status", "--json"], cwd)
    if proc.returncode == 0:
        return None
    detail = (proc.stderr or proc.stdout).strip()
    lowered = detail.lower()
    if "multiple active tasks" in lowered:
        return (
            "Multiple active AI-OS tasks are open; set AI_OS_TASK_ID to the owning "
            "task or close/archive the orphans before editing."
        )
    if "no active task" in lowered or "checkpoint not found" in lowered:
        return "No active AI-OS task checkpoint; run task-start with exact repo:path scope before writing."
    return detail or "AI-OS task-status failed"


def handle_write_guard(payload: dict[str, Any], cwd: Path) -> int:
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path")
    if not isinstance(path, str) or not path:
        return deny_pretool("Cannot resolve the target file path; use a scoped write with an active AI-OS task checkpoint.")
    unresolved = _require_resolvable_task(cwd)
    if unresolved:
        return deny_pretool(unresolved)
    proc = run_task(["task-guard-write", "--path", path], cwd)
    if proc.returncode == 0:
        return 0
    detail = (proc.stderr or proc.stdout).strip()
    return deny_pretool(detail or "AI-OS write guard denied the edit")


def handle_bash_guard(payload: dict[str, Any], cwd: Path) -> int:
    tool_input = payload.get("tool_input") or {}
    command = str(tool_input.get("command") or "")
    for pattern, reason in DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            return deny_pretool(reason)
    if re.search(r"(^|[;&|]\s*)git\s+add(?:\s|$)", command, re.I):
        return deny_pretool("Raw git add is disabled for agent work. Use scripts/ai_os_task.py task-commit.")
    if re.search(r"(^|[;&|]\s*)git\s+commit(?:\s|$)", command, re.I):
        return deny_pretool("Raw git commit is disabled for agent work. Run task-commit-plan, then task-commit.")
    if re.search(r"(^|[;&|]\s*)git\s+push(?:\s|$)", command, re.I):
        unresolved = _require_resolvable_task(cwd)
        if unresolved:
            return deny_pretool(unresolved)
        mode = publication_mode(cwd)
        if mode == "LOCAL_ONLY":
            return deny_pretool("Push is outside LOCAL_ONLY mode. Change the checkpoint to PUBLISH or SHIP first.")
    if re.search(r"(^|[;&|]\s*)gh\s+pr\s+create(?:\s|$)", command, re.I):
        unresolved = _require_resolvable_task(cwd)
        if unresolved:
            return deny_pretool(unresolved)
        mode = publication_mode(cwd)
        if mode == "LOCAL_ONLY":
            return deny_pretool("PR creation is outside LOCAL_ONLY mode. Change the checkpoint to PUBLISH or SHIP first.")
    if re.search(r"(^|[;&|]\s*)gh\s+pr\s+merge(?:\s|$)", command, re.I):
        return deny_pretool("PR merge remains a separate operator-approved action; SHIP mode does not auto-authorize merge.")
    return 0


def handle_post_write(cwd: Path) -> int:
    try:
        data = task_json(cwd)
        if data and data.get("status") in ACTIVE_STATUSES:
            refresh(cwd, strict=False)
    except Exception:
        return 0
    return 0


def handle_task_completed(cwd: Path) -> int:
    data = task_json(cwd)
    if not data or data.get("status") != "READY_TO_CLOSE":
        return 0
    for repo in data.get("target_repositories", []):
        proc = run_task(["task-commit-plan", "--repo", repo, "--json"], cwd)
        try:
            plan = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return block((proc.stderr or proc.stdout).strip() or f"commit plan failed for {repo}")
        verdict = plan.get("verdict")
        if verdict == "COMMIT_READY":
            paths = ", ".join(plan.get("owned_paths") or [])
            return block(
                f"Task has commit-ready local changes in {repo}: {paths}. "
                "Choose an accurate message and run task-commit, then rerun final post-commit gates."
            )
        if verdict == "BLOCKED":
            return block(f"Task cannot complete: {'; '.join(plan.get('reasons') or ['commit plan blocked'])}")
    closure = run_task(["task-close", "--validate-only", "--json"], cwd)
    try:
        result = json.loads(closure.stdout or "{}")
    except json.JSONDecodeError:
        return block((closure.stderr or closure.stdout).strip() or "task-close validation failed")
    if closure.returncode != 0:
        return block("Task cannot complete: " + "; ".join(result.get("issues") or ["closure validation failed"]))
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:
        return block(f"Invalid Claude hook input: {exc}")
    cwd = Path(str(payload.get("cwd") or ROOT)).resolve()
    event = payload.get("hook_event_name")
    tool = payload.get("tool_name")
    try:
        if event == "SessionStart":
            return handle_session_start(cwd)
        if event == "PreCompact":
            return handle_precompact(cwd)
        if event == "PreToolUse" and tool in {"Edit", "Write", "MultiEdit"}:
            return handle_write_guard(payload, cwd)
        if event == "PreToolUse" and tool == "Bash":
            return handle_bash_guard(payload, cwd)
        if event == "PostToolUse" and tool in {"Edit", "Write", "MultiEdit"}:
            return handle_post_write(cwd)
        if event == "TaskCompleted":
            return handle_task_completed(cwd)
        if event == "SessionEnd":
            refresh(cwd, strict=False)
            return 0
        return 0
    except subprocess.TimeoutExpired:
        return block("AI-OS Claude hook timed out") if event in {"PreToolUse", "PreCompact", "TaskCompleted"} else 0
    except Exception as exc:
        return block(f"AI-OS Claude hook failed: {exc}") if event in {"PreToolUse", "PreCompact", "TaskCompleted"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
