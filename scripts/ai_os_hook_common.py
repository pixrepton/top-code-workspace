#!/usr/bin/env python3
"""Primitives shared by the Codex and Claude lifecycle hook adapters."""

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


def emit(payload: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return 0


def run_task(args: list[str], cwd: Path, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TASK_SCRIPT), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
        env=os.environ.copy(),
    )


def proc_detail(proc: subprocess.CompletedProcess[str], fallback: str = "") -> str:
    """Preferred stderr, then stdout, then the caller's fallback."""
    detail = (proc.stderr or proc.stdout or "").strip()
    return detail or fallback


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
