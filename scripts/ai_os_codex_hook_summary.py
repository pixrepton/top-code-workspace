#!/usr/bin/env python3
"""SessionStart summary for Codex — thin host adapter over shared Execution Plane projection."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_hook_common import clip  # noqa: E402

# Host additionalContext budget (see .codex/hooks.json). Keep under limit with margin.
SUMMARY_CHAR_LIMIT = 2200


def build_session_summary(data: dict[str, Any] | None = None) -> str:
    """Render compact current-state inject from the shared session-start projector.

    Codex-specific formatting only clips for the host context budget. Semantics come
    exclusively from ``ai_os_execution.session_start.project_session_state``.
    """
    task_id = ""
    if isinstance(data, dict):
        task_id = str(data.get("task_id") or "").strip()
    try:
        from ai_os_execution.session_start import project_session_state

        projected = project_session_state(task_id=task_id)
        inject = str(projected.get("inject") or "").strip()
        if inject:
            return clip(inject, SUMMARY_CHAR_LIMIT)
    except Exception as exc:  # pragma: no cover - never break host SessionStart
        return clip(f"CURRENT EXECUTION: UNAVAILABLE ({clip(str(exc), 120)})", SUMMARY_CHAR_LIMIT)
    return "CURRENT TASK: none\nKIND: NONE\nDo not invent an Execution Bundle."
