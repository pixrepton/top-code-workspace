#!/usr/bin/env python3
"""Codex hook payload emission and cwd resolution."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_hook_common import ROOT, clip, emit  # noqa: E402

__all__ = ["ROOT", "clip", "resolve_cwd", "stop", "success"]


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


def resolve_cwd(payload: dict[str, Any]) -> Path:
    raw = payload.get("cwd")
    if isinstance(raw, str) and raw:
        try:
            return Path(raw).resolve()
        except OSError:
            return ROOT
    return ROOT
