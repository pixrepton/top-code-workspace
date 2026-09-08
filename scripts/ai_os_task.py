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
    add_scope,
    adopt_path,
    close_task,
    clear_next,
    finalize_task,
    list_tasks_cmd,
    new_checkpoint,
    remove_state,
    resume_task,
    status_task,
    update_checkpoint,
)
from ai_os_task_state import resolve_task_id
from ai_os_task_scope import normalize_scope_path, scope_entries_overlap, scopes_conflict

try:
    from ai_os_execution import CAPABILITY_PROFILES, EXECUTION_MODES, LEGACY_EXECUTION_MODES, SEED_ORIGINS, WRITE_MODES
except Exception:  # pragma: no cover - package always ships with this change
    WRITE_MODES = {"TEST", "BENCHMARK", "REPLAY", "PROOF", "LIVE_READ_ONLY", "MUTATE"}
    EXECUTION_MODES = WRITE_MODES
    LEGACY_EXECUTION_MODES = {"DOCS", "STATIC", "READ_ONLY_LOCAL"}
    CAPABILITY_PROFILES = {"NO_EXTERNAL", "DECLARED_LLM", "LIVE_READ_ONLY"}
    SEED_ORIGINS = {"EMPTY", "FIXTURE", "SNAPSHOT", "HISTORICAL_REPLAY"}

START_EXECUTION_MODES = sorted(EXECUTION_MODES | LEGACY_EXECUTION_MODES)

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


def add_execution_context_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--execution-id", help="Execution Bundle id (sets AI_OS_EXECUTION_ID)")
    parser.add_argument(
        "--repo-path",
        dest="repo_path_flag",
        help="Override runtime repo/worktree path for this invocation",
    )


def add_start_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--class", dest="task_class", choices=sorted(ALLOWED_CLASSES), required=True)
    parser.add_argument("--repo", action="append")
    parser.add_argument("--scope", action="append", required=True, help="repo:path")
    parser.add_argument(
        "--adopt-baseline",
        action="append",
        help="repo:path already dirty at task start that this task is explicitly authorized to own",
    )
    parser.add_argument("--next", dest="next_action", default="")
    parser.add_argument("--publication-mode", choices=sorted(ALLOWED_PUBLICATION_MODES), default="LOCAL_ONLY")
    parser.add_argument("--summary", default="")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Checkpoint-only SMALL docs/static path (no Execution Plane provisioning)",
    )
    parser.add_argument(
        "--execution-plane",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--execution-mode", default="TEST", choices=START_EXECUTION_MODES)
    parser.add_argument("--campaign-id", default="")
    parser.add_argument("--seed-origin", default="EMPTY", choices=sorted(SEED_ORIGINS))
    parser.add_argument("--capability-profile", default="NO_EXTERNAL", choices=sorted(CAPABILITY_PROFILES))
    parser.add_argument("--replay-as-of", default="", help="Semantic clock pin (ISO-8601)")
    parser.add_argument("--replay-timezone", default="Europe/Warsaw")
    parser.add_argument("--schema-revision", default="")
    parser.add_argument("--evaluator-version", default="")
    parser.add_argument("--fixture-hash", default="")
    parser.add_argument(
        "--scoring-paths-proven",
        action="store_true",
        help="Assert temporal scoring paths use semantic clock (HISTORICAL_REPLAY)",
    )
    parser.add_argument("--runtime-profile", choices=["host", "container"], default="")
    parser.add_argument("--image-digest", default="")
    parser.add_argument("--image-repo", default="")
    parser.add_argument("--db-isolation", dest="db_isolation", action="store_true")
    parser.add_argument("--no-db-isolation", dest="db_isolation", action="store_false")
    parser.add_argument("--db-host", default="")
    parser.add_argument("--db-container-host", default="")
    parser.add_argument("--db-port", default="")
    parser.set_defaults(db_isolation=None, func=new_checkpoint)


def task_repo_cmd(args: argparse.Namespace) -> int:
    from ai_os_task_git import canonical_repo_path, repo_path

    payload = {
        "repo": args.repo,
        "path": str(repo_path(args.repo)),
        "canonical": str(canonical_repo_path(args.repo)),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def exec_task_cmd(args: argparse.Namespace) -> int:
    from ai_os_execution.bundle import load_bundle_for_task, save_bundle
    from ai_os_execution.mediated_exec import run_mediated_command
    from ai_os_task_lifecycle import require_plane_bundle
    from ai_os_task_state import load_checkpoint

    data = load_checkpoint(getattr(args, "task_id", None))
    require_plane_bundle(data)
    command = list(getattr(args, "command", None) or [])
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise TaskError("exec requires a command after --")
    bundle = load_bundle_for_task(data["task_id"])
    if not bundle:
        raise TaskError("execution bundle missing for exec")
    result = run_mediated_command(
        execution_id=bundle["execution_id"],
        repo=args.repo,
        operation_kind="TASK_EXEC",
        command=command,
        gate_timeout=int(getattr(args, "timeout", 0) or 0),
        bundle=bundle,
    )
    save_bundle(bundle)
    receipt = result.receipt or {}
    if receipt.get("receipt_id"):
        print(f"receipt: {receipt['receipt_id']}")
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)
    return 1 if result.exit_code != 0 else 0


def session_start_cmd(args: argparse.Namespace) -> int:
    from ai_os_execution.session_start import project_session_state

    result = project_session_state(task_id=str(getattr(args, "task_id", None) or ""))
    if getattr(args, "json", False):
        payload = dict(result["state"])
        payload["inject"] = result["inject"]
        payload["mutated_execution"] = False
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    print(result["inject"])
    return 0


def apply_runtime_context(args: argparse.Namespace) -> None:
    task_id = getattr(args, "task_id", None)
    if task_id:
        os.environ["AI_OS_TASK_ID"] = str(task_id)
    execution_id = getattr(args, "execution_id", None)
    if execution_id:
        os.environ["AI_OS_EXECUTION_ID"] = str(execution_id)
    repo_override = getattr(args, "repo_path_flag", None)
    if repo_override:
        os.environ["AI_OS_REPO_PATH"] = str(repo_override)

def takeover_cmd(args: argparse.Namespace) -> int:
    from ai_os_execution.plane import takeover_execution

    payload = takeover_execution(resolve_task_id(getattr(args, "task_id", None)))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def close_execution_cmd(args: argparse.Namespace) -> int:
    from ai_os_execution.plane import close_execution

    payload = close_execution(resolve_task_id(getattr(args, "task_id", None)))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def destroy_execution_cmd(args: argparse.Namespace) -> int:
    from ai_os_execution.plane import destroy_execution

    payload = destroy_execution(
        resolve_task_id(getattr(args, "task_id", None)),
        retain_evidence=not getattr(args, "no_retain_evidence", False),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-OS Codex execution task checkpoint helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("task-start")
    add_start_args(start)
    start.set_defaults(cmd="task-start", legacy=False)

    plane_start = sub.add_parser("start", help="task-start with Execution Plane V1 provisioning")
    add_start_args(plane_start)
    plane_start.set_defaults(cmd="start", db_isolation=None, func=new_checkpoint)

    status = sub.add_parser("task-status")
    add_task_id_arg(status)
    status.add_argument("--all", action="store_true", help="List active task ids")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=status_task)

    resume = sub.add_parser("task-resume")
    add_task_id_arg(resume)
    add_execution_context_args(resume)
    resume.set_defaults(func=resume_task)

    resume_alias = sub.add_parser("resume", help="Alias of task-resume")
    add_task_id_arg(resume_alias)
    add_execution_context_args(resume_alias)
    resume_alias.set_defaults(func=resume_task)

    repo_cmd = sub.add_parser("task-repo", help="Print Execution Bundle worktree path for a repo")
    add_task_id_arg(repo_cmd)
    add_execution_context_args(repo_cmd)
    repo_cmd.add_argument("--repo", required=True)
    repo_cmd.set_defaults(func=task_repo_cmd)

    takeover = sub.add_parser("execution-takeover", help="Bump lease generation and allocate new worktrees")
    add_task_id_arg(takeover)
    takeover.set_defaults(func=takeover_cmd)

    exec_close = sub.add_parser("execution-close", help="Close execution bundle; revoke secrets, keep evidence")
    add_task_id_arg(exec_close)
    exec_close.set_defaults(func=close_execution_cmd)

    exec_destroy = sub.add_parser("execution-destroy", help="Destroy execution worktrees and revoke secrets")
    add_task_id_arg(exec_destroy)
    exec_destroy.add_argument("--no-retain-evidence", action="store_true")
    exec_destroy.set_defaults(func=destroy_execution_cmd)

    exec_cmd = sub.add_parser("exec", help="Mediated trusted execution in bundle worktree with command receipt")
    add_task_id_arg(exec_cmd)
    add_execution_context_args(exec_cmd)
    exec_cmd.add_argument("--repo", required=True)
    exec_cmd.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Timeout in seconds (0 = unlimited)",
    )
    exec_cmd.add_argument("command", nargs=argparse.REMAINDER)
    exec_cmd.set_defaults(func=exec_task_cmd)

    session_start = sub.add_parser(
        "session-start",
        help="Read-only cold-start projection: refresh CAMPAIGN_STATE/TASK_ENTRY and print inject",
    )
    add_task_id_arg(session_start)
    session_start.add_argument("--json", action="store_true")
    session_start.set_defaults(func=session_start_cmd)

    owner_add = sub.add_parser("task-owner-add", help="Expand write scope with lease conflict check")
    add_task_id_arg(owner_add)
    owner_add.add_argument("--scope", action="append", required=True, help="repo:path to add")
    owner_add.add_argument("--adopt-existing", action="store_true")
    owner_add.add_argument("--reason", default="")
    owner_add.set_defaults(func=add_scope)

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

    scope_add = sub.add_parser("task-scope-add")
    add_task_id_arg(scope_add)
    scope_add.add_argument("--scope", action="append", required=True, help="repo:path to add to declared scope")
    scope_add.add_argument(
        "--adopt-existing",
        action="store_true",
        help="Adopt current dirty paths under the added scope as task-owned",
    )
    scope_add.add_argument("--reason", default="")
    scope_add.set_defaults(func=add_scope)

    adopt = sub.add_parser("task-adopt-path")
    add_task_id_arg(adopt)
    adopt.add_argument("--path", action="append", required=True, help="repo:path inside declared scope")
    adopt.add_argument("--reason", default="")
    adopt.set_defaults(func=adopt_path)

    next_clear = sub.add_parser("task-next-clear")
    add_task_id_arg(next_clear)
    next_clear.set_defaults(func=clear_next)

    gate = sub.add_parser("task-gate")
    add_task_id_arg(gate)
    add_execution_context_args(gate)
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
    gate.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Gate-level timeout in seconds (0 = unlimited). On expiry the runner "
        "terminates only its own spawned process tree and records a TIMEOUT verdict.",
    )
    gate.add_argument(
        "--profile",
        help="Resolve a deterministic test profile (see scripts/ai_os_task_profiles.py). "
        "Mutually exclusive with a raw command.",
    )
    gate.add_argument("--final-head", action="store_true", help="Record this gate as FINAL_HEAD_GATE class")
    gate.add_argument("command", nargs=argparse.REMAINDER)
    gate.set_defaults(func=run_gate)

    branch = sub.add_parser("task-branch")
    add_task_id_arg(branch)
    branch.add_argument("--repo", required=True)
    branch.add_argument("--name", required=True)
    branch.set_defaults(func=create_task_branch)

    commit_plan = sub.add_parser("task-commit-plan")
    add_task_id_arg(commit_plan)
    add_execution_context_args(commit_plan)
    commit_plan.add_argument("--repo", required=True)
    commit_plan.add_argument("--json", action="store_true")
    commit_plan.set_defaults(func=plan_commit)

    commit = sub.add_parser("task-commit")
    add_task_id_arg(commit)
    add_execution_context_args(commit)
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
    add_execution_context_args(close)
    close.add_argument("--validate-only", action="store_true")
    close.add_argument("--json", action="store_true")
    close.add_argument("--summary")
    close.add_argument("--summary-file")
    close.set_defaults(func=close_task)

    finalize = sub.add_parser("task-finalize")
    add_task_id_arg(finalize)
    finalize.add_argument("--message", default="", help="Commit message used when commit-plan says COMMIT_READY")
    finalize.add_argument("--summary", default="", help="Close summary")
    finalize.add_argument("--gate-id", default="")
    finalize.add_argument("--gate-repo", default="")
    finalize.add_argument("--gate-profile", default="", help="Resolve a test profile for the post-commit gate")
    finalize.add_argument("--gate-scope", action="append")
    finalize.add_argument("--gate-timeout", type=int, default=0)
    finalize.add_argument("--gate-command", nargs=argparse.REMAINDER)
    finalize.add_argument("--json", action="store_true")
    finalize.set_defaults(func=finalize_task)

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
        apply_runtime_context(args)
        return int(args.func(args))
    except TaskError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
