from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_os_task_constants import TASK_ID_PATTERN
from ai_os_task_errors import TaskError

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def state_dir() -> Path:
    explicit = os.environ.get("AI_OS_TASK_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    scratch = Path(os.environ.get("TOP_CODE_SESSION_SCRATCH", r"C:\top-code-session-scratch"))
    return scratch / "ai-os-execution" / "top-code-workspace"

def legacy_checkpoint_path() -> Path:
    return state_dir() / "current-task.json"

def summary_path() -> Path:
    return state_dir() / "last-summary.json"

def tasks_active_dir() -> Path:
    return state_dir() / "tasks" / "active"

def tasks_archive_dir() -> Path:
    return state_dir() / "tasks" / "archive"

def sanitize_task_id(task_id: str) -> str:
    task_id = task_id.strip()
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise TaskError(f"invalid task_id: {task_id}")
    return task_id

def active_task_path(task_id: str) -> Path:
    return tasks_active_dir() / f"{sanitize_task_id(task_id)}.json"

def archive_task_path(task_id: str) -> Path:
    return tasks_archive_dir() / f"{sanitize_task_id(task_id)}.json"

def list_active_task_ids() -> list[str]:
    directory = tasks_active_dir()
    if not directory.exists():
        return []
    return sorted(
        path.stem
        for path in directory.glob("*.json")
        if TASK_ID_PATTERN.fullmatch(path.stem)
    )

def checkpoint_path() -> Path:
    """Backward-compatible path hint; prefer active_task_path(task_id)."""
    active = list_active_task_ids()
    if len(active) == 1:
        return active_task_path(active[0])
    return legacy_checkpoint_path()
