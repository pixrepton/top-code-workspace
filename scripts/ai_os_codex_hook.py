#!/usr/bin/env python3
"""Thin Codex lifecycle hook adapter for AI-OS task checkpoints."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_codex_hook_checkpoint import (  # noqa: E402
    active_checkpoint,
    checkpoint_is_active,
    checkpoint_state,
    maybe_resume,
    refresh_checkpoint,
)
from ai_os_codex_hook_io import clip, resolve_cwd, stop, success  # noqa: E402
from ai_os_codex_hook_summary import build_session_summary  # noqa: E402


def session_start_gate(state: str, data: dict[str, Any] | None, detail: str) -> int | None:
    """Return a final exit code when there is nothing active to summarize."""
    if state in {"missing", "multiple"}:
        return success()
    if state == "corrupt":
        return stop("AI-OS checkpoint is corrupt; repair it before continuing.")
    if state != "ok" or data is None:
        return success(system_message=f"AI-OS checkpoint refresh failed: {clip(detail, 180)}")
    if not checkpoint_is_active(data):
        return success()
    return None


def session_start_report(cwd: Path, resumed: bool, resume_detail: str) -> int:
    state, data, detail = checkpoint_state(cwd)
    if state != "ok" or data is None:
        message = "AI-OS checkpoint refreshed but summary is unavailable."
        if detail:
            message = f"{message} {clip(detail, 140)}"
        return success(system_message=message)
    message = None if resumed else f"AI-OS task-resume failed: {clip(resume_detail, 180)}"
    return success(system_message=message, additional_context=build_session_summary(data))


def handle_session_start(payload: dict[str, Any], cwd: Path) -> int:
    state, data, detail = checkpoint_state(cwd)
    early = session_start_gate(state, data, detail)
    if early is not None:
        return early
    refreshed, refresh_detail = refresh_checkpoint(cwd, timeout=5.0)
    if not refreshed:
        return success(system_message=f"AI-OS checkpoint refresh failed: {clip(refresh_detail, 180)}")
    resumed, resume_detail = maybe_resume(cwd)
    return session_start_report(cwd, resumed, resume_detail)


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
    if active_checkpoint(cwd) is None:
        return success()
    try:
        ok, detail = refresh_checkpoint(cwd, timeout=2.5)
        if not ok and detail:
            return success(system_message=f"AI-OS session-end refresh failed: {clip(detail, 180)}")
    except subprocess.TimeoutExpired:
        return success(system_message="AI-OS session-end refresh timed out.")
    return success()


def dispatch(hook_event: Any, payload: dict[str, Any], cwd: Path) -> int:
    if hook_event == "SessionStart":
        return handle_session_start(payload, cwd)
    if hook_event == "PreCompact":
        return handle_pre_compact(cwd)
    if hook_event == "SessionEnd":
        return handle_session_end(cwd)
    return success(system_message=f"Unsupported AI-OS hook event: {hook_event}")


def failure_exit(hook_event: Any, reason: str) -> int:
    if hook_event == "SessionEnd":
        return success()
    return stop(reason)


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
        return dispatch(hook_event, payload, cwd)
    except subprocess.TimeoutExpired:
        return failure_exit(hook_event, "AI-OS hook timed out.")
    except Exception as exc:  # pragma: no cover - defensive
        return failure_exit(hook_event, f"AI-OS hook failed: {clip(str(exc), 180)}")


if __name__ == "__main__":
    raise SystemExit(main())
