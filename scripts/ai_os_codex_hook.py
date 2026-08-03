#!/usr/bin/env python3
"""Thin Codex lifecycle hook adapter for AI-OS task checkpoints."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TASK_SCRIPT = ROOT / "scripts" / "ai_os_task.py"
ACTIVE_STATUSES = {"INITIALIZED", "IN_PROGRESS", "BLOCKED", "READY_TO_CLOSE"}
SUMMARY_CHAR_LIMIT = 700


def emit(payload: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return 0


def success(*, system_message: str | None = None, additional_context: str | None = None) -> int:
    payload: dict[str, Any] = {"continue": True}
    if system_message:
        payload["systemMessage"] = system_message
    if additional_context:
        payload["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    return emit(payload)


def stop(reason: str) -> int:
    return emit(
        {
            "continue": False,
            "stopReason": reason,
            "systemMessage": reason,
        }
    )


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def run_task(args: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, str(TASK_SCRIPT), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )


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
    proc = run_task(["task-status", "--json"], cwd=cwd, timeout=5.0)
    if proc.returncode == 0:
        try:
            return "ok", json.loads(proc.stdout), ""
        except json.JSONDecodeError as exc:
            return "error", None, f"task-status returned invalid JSON: {exc}"
    detail = (proc.stderr or proc.stdout or "").strip()
    return classify_task_status_failure(detail), None, detail


def checkpoint_is_active(data: dict[str, Any]) -> bool:
    return data.get("status") in ACTIVE_STATUSES


def refresh_checkpoint(cwd: Path, *, timeout: float) -> tuple[bool, str]:
    proc = run_task(["task-checkpoint"], cwd=cwd, timeout=timeout)
    if proc.returncode == 0:
        return True, ""
    detail = (proc.stderr or proc.stdout or "").strip()
    return False, detail or "task-checkpoint failed"


def maybe_resume(cwd: Path) -> tuple[bool, str]:
    proc = run_task(["task-resume"], cwd=cwd, timeout=5.0)
    if proc.returncode == 0:
        return True, ""
    detail = (proc.stderr or proc.stdout or "").strip()
    return False, detail or "task-resume failed"


def format_scope(data: dict[str, Any]) -> str:
    scope = data.get("declared_write_scope") or []
    rendered = [f"{item['repo']}:{item['path']}" for item in scope[:3] if "repo" in item and "path" in item]
    if len(scope) > 3:
        rendered.append(f"+{len(scope) - 3} more")
    return ", ".join(rendered) if rendered else "<none>"


def format_last_gate(data: dict[str, Any]) -> str:
    gates = data.get("gates") or []
    if not gates:
        return "<none>"
    gate = gates[-1]
    return f"{gate.get('gate_id', '?')} {gate.get('verdict', '?')}"


def format_last_commit(data: dict[str, Any]) -> str:
    commits = data.get("commits") or []
    if not commits:
        return "<none>"
    return str(commits[-1]).split(":")[-1][:7]


def format_blockers(data: dict[str, Any]) -> str:
    blockers = data.get("blockers") or []
    open_count = sum(1 for blocker in blockers if blocker.get("status") not in {"RESOLVED", "DEFERRED_WITH_EVIDENCE", "ACCEPTED"})
    return str(open_count)


def build_session_summary(data: dict[str, Any]) -> str:
    lines = [
        f"task: {data.get('task_id', '<unknown>')}",
        f"status: {data.get('status', '<unknown>')}",
        f"phase: {data.get('current_phase', '<unknown>')}",
        f"commit: {format_last_commit(data)}",
        f"scope: {format_scope(data)}",
        f"gate: {format_last_gate(data)}",
        f"next: {clip(str(data.get('next_action') or '<none>'), 160)}",
        f"blockers_open: {format_blockers(data)}",
    ]
    return clip("\n".join(lines), SUMMARY_CHAR_LIMIT)


def resolve_cwd(payload: dict[str, Any]) -> Path:
    raw = payload.get("cwd")
    if isinstance(raw, str) and raw:
        try:
            return Path(raw).resolve()
        except OSError:
            return ROOT
    return ROOT


def handle_session_start(payload: dict[str, Any], cwd: Path) -> int:
    state, data, detail = checkpoint_state(cwd)
    if state in {"missing", "multiple"}:
        return success()
    if state == "corrupt":
        return stop("AI-OS checkpoint is corrupt; repair it before continuing.")
    if state != "ok" or data is None:
        return success(system_message=f"AI-OS checkpoint refresh failed: {clip(detail, 180)}")
    if not checkpoint_is_active(data):
        return success()
    refreshed, refresh_detail = refresh_checkpoint(cwd, timeout=5.0)
    if not refreshed:
        return success(system_message=f"AI-OS checkpoint refresh failed: {clip(refresh_detail, 180)}")
    resumed, resume_detail = maybe_resume(cwd)
    state, data, detail = checkpoint_state(cwd)
    if state != "ok" or data is None:
        message = "AI-OS checkpoint refreshed but summary is unavailable."
        if detail:
            message = f"{message} {clip(detail, 140)}"
        return success(system_message=message)
    message = None if resumed else f"AI-OS task-resume failed: {clip(resume_detail, 180)}"
    return success(system_message=message, additional_context=build_session_summary(data))


def handle_pre_compact(cwd: Path) -> int:
    state, data, detail = checkpoint_state(cwd)
    if state == "missing":
        return success()
    if state == "corrupt":
        return stop("AI-OS checkpoint is corrupt; repair it before compaction.")
    if state != "ok" or data is None:
        return stop(f"AI-OS checkpoint cannot be refreshed before compaction: {clip(detail, 180)}")
    if not checkpoint_is_active(data):
        return success()
    refreshed, refresh_detail = refresh_checkpoint(cwd, timeout=5.0)
    if not refreshed:
        return stop(f"AI-OS checkpoint refresh failed before compaction: {clip(refresh_detail, 180)}")
    return success()


def handle_session_end(cwd: Path) -> int:
    state, data, _detail = checkpoint_state(cwd)
    if state != "ok" or data is None or not checkpoint_is_active(data):
        return success()
    try:
        ok, detail = refresh_checkpoint(cwd, timeout=2.5)
        if not ok and detail:
            return success(system_message=f"AI-OS session-end refresh failed: {clip(detail, 180)}")
    except subprocess.TimeoutExpired:
        return success(system_message="AI-OS session-end refresh timed out.")
    return success()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return stop("Hook input is not valid JSON.")
    except Exception as exc:  # pragma: no cover - defensive
        return stop(f"Hook input error: {exc}")

    hook_event = payload.get("hook_event_name")
    cwd = resolve_cwd(payload)

    try:
        if hook_event == "SessionStart":
            return handle_session_start(payload, cwd)
        if hook_event == "PreCompact":
            return handle_pre_compact(cwd)
        if hook_event == "SessionEnd":
            return handle_session_end(cwd)
        return success(system_message=f"Unsupported AI-OS hook event: {hook_event}")
    except subprocess.TimeoutExpired:
        if hook_event == "SessionEnd":
            return success()
        return stop("AI-OS hook timed out.")
    except Exception as exc:  # pragma: no cover - defensive
        if hook_event == "SessionEnd":
            return success()
        return stop(f"AI-OS hook failed: {clip(str(exc), 180)}")


if __name__ == "__main__":
    raise SystemExit(main())
