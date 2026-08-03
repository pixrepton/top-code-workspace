#!/usr/bin/env python3
"""Thin AI-OS task checkpoint, gate ledger, and closure helper."""

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

from ai_os_task_commit import commit_task, create_task_branch, guard_write, plan_commit
from ai_os_task_constants import ALLOWED_CLASSES, ALLOWED_PUBLICATION_MODES, ALLOWED_STATUSES, WORKSPACE
from ai_os_task_errors import TaskError
from ai_os_task_gates import run_gate
from ai_os_task_lifecycle import (
    close_task,
    list_tasks_cmd,
    new_checkpoint,
    remove_state,
    resume_task,
    status_task,
    update_checkpoint,
)
from ai_os_task_scope import normalize_scope_path, scope_entries_overlap, scopes_conflict

# Re-exports required by tests / external imports
__all__ = [
    "TaskError",
    "WORKSPACE",
    "normalize_scope_path",
    "scope_entries_overlap",
    "scopes_conflict",
    "main",
]

def add_task_id_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task-id", help="Explicit task id (default: AI_OS_TASK_ID or single active task)")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-OS Codex execution task checkpoint helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("task-start")
    start.add_argument("--task-id", required=True)
    start.add_argument("--title", required=True)
    start.add_argument("--class", dest="task_class", choices=sorted(ALLOWED_CLASSES), required=True)
    start.add_argument("--repo", action="append")
    start.add_argument("--scope", action="append", required=True, help="repo:path")
    start.add_argument(
        "--adopt-baseline",
        action="append",
        help="repo:path already dirty at task start that this task is explicitly authorized to own",
    )
    start.add_argument("--next", dest="next_action", default="")
    start.add_argument("--publication-mode", choices=sorted(ALLOWED_PUBLICATION_MODES), default="LOCAL_ONLY")
    start.add_argument("--summary", default="")
    start.add_argument("--replace", action="store_true")
    start.set_defaults(func=new_checkpoint)

    status = sub.add_parser("task-status")
    add_task_id_arg(status)
    status.add_argument("--all", action="store_true", help="List active task ids")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=status_task)

    resume = sub.add_parser("task-resume")
    add_task_id_arg(resume)
    resume.set_defaults(func=resume_task)

    checkpoint = sub.add_parser("task-checkpoint")
    add_task_id_arg(checkpoint)
    checkpoint.add_argument("--status", choices=sorted(ALLOWED_STATUSES))
    checkpoint.add_argument("--phase")
    checkpoint.add_argument("--next", dest="next_action")
    checkpoint.add_argument("--summary")
    checkpoint.add_argument("--publication-mode", choices=sorted(ALLOWED_PUBLICATION_MODES))
    checkpoint.add_argument("--decision", action="append")
    checkpoint.add_argument("--step", action="append")
    checkpoint.add_argument("--blocker", action="append")
    checkpoint.add_argument("--resolve-blocker", action="append")
    checkpoint.add_argument("--commit", action="append", help="repo:sha or sha")
    checkpoint.set_defaults(func=update_checkpoint)

    gate = sub.add_parser("task-gate")
    add_task_id_arg(gate)
    gate.add_argument("--gate-id", required=True)
    gate.add_argument("--repo", required=True)
    gate.add_argument("--scope", action="append")
    gate.add_argument("--config-path", action="append")
    gate.add_argument("--runtime-id")
    gate.add_argument("--runtime-command", nargs="+")
    gate.add_argument("--always-fresh", action="store_true")
    gate.add_argument("--summary")
    gate.add_argument("--limitations")
    gate.add_argument("--log-path")
    gate.add_argument("command", nargs=argparse.REMAINDER)
    gate.set_defaults(func=run_gate)

    branch = sub.add_parser("task-branch")
    add_task_id_arg(branch)
    branch.add_argument("--repo", required=True)
    branch.add_argument("--name", required=True)
    branch.set_defaults(func=create_task_branch)

    commit_plan = sub.add_parser("task-commit-plan")
    add_task_id_arg(commit_plan)
    commit_plan.add_argument("--repo", required=True)
    commit_plan.add_argument("--json", action="store_true")
    commit_plan.set_defaults(func=plan_commit)

    commit = sub.add_parser("task-commit")
    add_task_id_arg(commit)
    commit.add_argument("--repo", required=True)
    commit.add_argument("--message", required=True)
    commit.add_argument("--json", action="store_true")
    commit.set_defaults(func=commit_task)

    write_guard = sub.add_parser("task-guard-write")
    add_task_id_arg(write_guard)
    write_guard.add_argument("--path", required=True)
    write_guard.set_defaults(func=guard_write)

    close = sub.add_parser("task-close")
    add_task_id_arg(close)
    close.add_argument("--validate-only", action="store_true")
    close.add_argument("--json", action="store_true")
    close.add_argument("--summary")
    close.add_argument("--summary-file")
    close.set_defaults(func=close_task)

    cleanup = sub.add_parser("task-cleanup")
    add_task_id_arg(cleanup)
    cleanup.add_argument("--archive", action="store_true")
    cleanup.set_defaults(func=remove_state)

    list_tasks = sub.add_parser("task-list")
    list_tasks.add_argument("--json", action="store_true")
    list_tasks.set_defaults(func=list_tasks_cmd)
    return parser

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except TaskError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
