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

from ai_os_task_commit import closure_issues
from ai_os_task_constants import SCHEMA_VERSION, WORKSPACE
from ai_os_task_errors import TaskError
from ai_os_task_git import git_branch, git_head, repo_path
from ai_os_task_locks import RegistryLock
from ai_os_task_ownership import (
    OwnershipError,
    collect_raw_git_state,
    capture_ownership_baseline,
    delete_ownership_baseline,
    scope_contains,
)
from ai_os_task_paths import (
    active_task_path,
    archive_task_path,
    legacy_checkpoint_path,
    list_active_task_ids,
    sanitize_task_id,
    state_dir,
    summary_path,
    utc_now,
)
from ai_os_task_scope import parse_scope, scopes_for_repo
from ai_os_task_state import (
    atomic_write,
    find_scope_conflicts,
    git_mismatches,
    load_checkpoint,
    migrate_legacy_checkpoint,
    migrate_legacy_checkpoint_if_present,
    print_summary,
    refresh_git_fields,
    resolve_task_id,
)

def _require_adopted_inside_scope(scope: list[dict[str, str]], adopted: list[dict[str, str]]) -> None:
    for item in adopted:
        if not scope_contains(scope, item):
            raise TaskError(f"adopted baseline path must be inside declared scope: {item['repo']}:{item['path']}")

def _scope_identity(item: dict[str, str]) -> tuple[str, str]:
    return item["repo"], item["path"]

def _append_unique_scope(target: list[dict[str, str]], additions: list[dict[str, str]]) -> list[dict[str, str]]:
    existing = {_scope_identity(item) for item in target}
    changed = list(target)
    for item in additions:
        key = _scope_identity(item)
        if key not in existing:
            changed.append(item)
            existing.add(key)
    return changed

def _require_known_scope_repos(data: dict[str, Any], additions: list[dict[str, str]]) -> None:
    known = set(data["target_repositories"])
    unknown = sorted({item["repo"] for item in additions} - known)
    if unknown:
        raise TaskError(
            "scope updates can only add paths inside existing target repositories; "
            f"start a new task for repo(s): {', '.join(unknown)}"
        )

def _qualified_dirty_paths(scope: list[dict[str, str]]) -> list[str]:
    dirty: set[str] = set()
    for repo in sorted({item["repo"] for item in scope}):
        raw = collect_raw_git_state(repo_path(repo), scopes_for_repo(scope, repo))
        for paths in raw.values():
            dirty.update(f"{repo}:{path}" for path in paths)
    return sorted(dirty)

def _require_clean_scope_addition(additions: list[dict[str, str]], adopt_existing: bool) -> None:
    if adopt_existing:
        return
    dirty = _qualified_dirty_paths(additions)
    if dirty:
        raise TaskError(
            "cannot add scope with pre-existing dirty paths unless --adopt-existing is set: "
            + ", ".join(dirty[:10])
        )

def _release_replaced_baseline(active_path: Path) -> None:
    try:
        previous = json.loads(active_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if previous:
        delete_ownership_baseline(state_dir(), previous.get("ownership_baseline"))

def _require_free_task_slot(active_path: Path, task_id: str, replace: bool) -> None:
    if not active_path.exists():
        return
    if not replace:
        raise TaskError(
            f"active task already exists for {task_id}; use task-status/task-resume or --replace: {active_path}"
        )
    _release_replaced_baseline(active_path)

def _require_no_scope_conflict(scope: list[dict[str, str]], task_id: str, replace: bool) -> None:
    conflicts = find_scope_conflicts(scope, exclude_task_id=task_id if replace else None)
    if not conflicts:
        return
    first = conflicts[0]
    raise TaskError(
        "scope conflict with active task "
        f"{first['task_id']}: requested {first['requested_scope']} overlaps {first['existing_scope']}"
    )

def _head_map(repos: list[str]) -> dict[str, str]:
    return {repo: git_head(repo) for repo in repos}

def _branch_map(repos: list[str]) -> dict[str, str]:
    return {repo: git_branch(repo) for repo in repos}

def _repo_path_map(repos: list[str]) -> dict[str, Path]:
    return {repo: repo_path(repo) for repo in repos}

def _initial_checkpoint(
    args: argparse.Namespace,
    scope: list[dict[str, str]],
    adopted: list[dict[str, str]],
    now: str,
) -> dict[str, Any]:
    repos = args.repo or sorted({item["repo"] for item in scope})
    baseline = _head_map(repos)
    branches = _branch_map(repos)
    try:
        ownership_baseline = capture_ownership_baseline(
            _repo_path_map(repos), scope, baseline, adopted, state_dir(), now
        )
    except OwnershipError as exc:
        raise TaskError(str(exc)) from exc
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": sanitize_task_id(args.task_id),
        "task_title": args.title,
        "task_class": args.task_class,
        "workspace_path": str(WORKSPACE),
        "started_at_utc": now,
        "updated_at_utc": now,
        "status": "INITIALIZED",
        "current_phase": "task-start",
        "target_repositories": repos,
        "baseline_shas": baseline,
        "current_shas": dict(baseline),
        "declared_write_scope": scope,
        "own_staged_files": [],
        "own_unstaged_files": [],
        "own_untracked_files": [],
        "ownership_baseline": ownership_baseline,
        "adopted_baseline_scope": adopted,
        "ownership_conflicts": [],
        "decisions": [],
        "completed_steps": [],
        "gates": [],
        "commits": [],
        "blockers": [],
        "next_action": args.next_action,
        "proof_limits": {
            "checkpoint_json": 1,
            "final_execution_summary": 1,
            "test_logs": 1,
            "extra_logs": "failure-or-critical-runtime-only",
        },
        "last_summary": args.summary,
        "publication_mode": args.publication_mode,
        "commit_policy": "AUTO_LOCAL",
        "baseline_branches": branches,
        "current_branches": dict(branches),
        "commit_evaluations": [],
    }

def new_checkpoint(args: argparse.Namespace) -> int:
    scope = parse_scope(args.scope)
    adopted = parse_scope(args.adopt_baseline or [])
    _require_adopted_inside_scope(scope, adopted)
    task_id = sanitize_task_id(args.task_id)
    with RegistryLock():
        migrate_legacy_checkpoint()
        active_path = active_task_path(task_id)
        _require_free_task_slot(active_path, task_id, args.replace)
        _require_no_scope_conflict(scope, task_id, args.replace)
        data = _initial_checkpoint(args, scope, adopted, utc_now())
        refresh_git_fields(data)
        atomic_write(data, active_path)
    print_summary(data, "INITIALIZED")
    print(f"checkpoint: {active_path}")
    return 0

def _apply_field_updates(args: argparse.Namespace, data: dict[str, Any]) -> None:
    if args.status:
        data["status"] = args.status
    if args.phase:
        data["current_phase"] = args.phase
    if args.next_action is not None:
        data["next_action"] = args.next_action
    if args.summary is not None:
        data["last_summary"] = args.summary
    if args.publication_mode is not None:
        data["publication_mode"] = args.publication_mode

def _apply_timeline_appends(args: argparse.Namespace, data: dict[str, Any]) -> None:
    for value in args.decision or []:
        data["decisions"].append({"timestamp": utc_now(), "text": value})
    for value in args.step or []:
        data["completed_steps"].append({"timestamp": utc_now(), "text": value})
    for value in args.blocker or []:
        data["blockers"].append({"timestamp": utc_now(), "status": "OPEN", "text": value})

def _resolve_blockers(args: argparse.Namespace, data: dict[str, Any]) -> None:
    requested = set(args.resolve_blocker or [])
    for blocker in data["blockers"]:
        if blocker.get("text") in requested:
            blocker["status"] = "RESOLVED"
            blocker["resolved_at_utc"] = utc_now()

def _append_commits(args: argparse.Namespace, data: dict[str, Any]) -> None:
    for value in args.commit or []:
        if value not in data["commits"]:
            data["commits"].append(value)

def update_checkpoint(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    _apply_field_updates(args, data)
    _apply_timeline_appends(args, data)
    _resolve_blockers(args, data)
    _append_commits(args, data)
    refresh_git_fields(data)
    atomic_write(data)
    print_summary(data, "CHECKPOINT")
    return 0

def add_scope(args: argparse.Namespace) -> int:
    additions = parse_scope(args.scope)
    task_id = getattr(args, "task_id", None)
    with RegistryLock():
        data = load_checkpoint(task_id)
        _require_known_scope_repos(data, additions)
        _require_no_scope_conflict(additions, data["task_id"], replace=True)
        _require_clean_scope_addition(additions, args.adopt_existing)
        data["declared_write_scope"] = _append_unique_scope(data["declared_write_scope"], additions)
        if args.adopt_existing:
            data["adopted_baseline_scope"] = _append_unique_scope(data["adopted_baseline_scope"], additions)
        data["completed_steps"].append(
            {
                "timestamp": utc_now(),
                "text": "Updated task scope: "
                + ", ".join(f"{item['repo']}:{item['path']}" for item in additions),
            }
        )
        if args.reason:
            data["decisions"].append({"timestamp": utc_now(), "text": args.reason})
        data["current_phase"] = "scope-updated"
        refresh_git_fields(data)
        atomic_write(data)
    print_summary(data, "SCOPE_UPDATED")
    return 0

def adopt_path(args: argparse.Namespace) -> int:
    additions = parse_scope(args.path)
    data = load_checkpoint(getattr(args, "task_id", None))
    _require_known_scope_repos(data, additions)
    _require_adopted_inside_scope(data["declared_write_scope"], additions)
    data["adopted_baseline_scope"] = _append_unique_scope(data["adopted_baseline_scope"], additions)
    data["completed_steps"].append(
        {
            "timestamp": utc_now(),
            "text": "Adopted baseline path(s): "
            + ", ".join(f"{item['repo']}:{item['path']}" for item in additions),
        }
    )
    if args.reason:
        data["decisions"].append({"timestamp": utc_now(), "text": args.reason})
    data["current_phase"] = "baseline-adopted"
    refresh_git_fields(data)
    atomic_write(data)
    print_summary(data, "ADOPTED")
    return 0

def clear_next(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    data["next_action"] = ""
    data["completed_steps"].append({"timestamp": utc_now(), "text": "Cleared task next_action"})
    data["current_phase"] = "next-cleared"
    refresh_git_fields(data)
    atomic_write(data)
    print_summary(data, "NEXT_CLEARED")
    return 0

def _print_closure(payload: dict[str, Any], issues: list[str], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"CLOSURE: {payload['verdict']}")
    for issue in issues:
        print(f"- {issue}")

def _archive_closed_checkpoint(data: dict[str, Any]) -> Path:
    archive_path = archive_task_path(data["task_id"])
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        backup = archive_path.with_name(f"{archive_path.stem}.closed-{int(time.time())}.json")
        shutil.copy2(archive_path, backup)
    atomic_write(data, archive_path)
    return archive_path

def _write_final_summary(data: dict[str, Any], summary_file: str | None) -> Path:
    final = {
        "task_id": data["task_id"],
        "closed_at_utc": data["updated_at_utc"],
        "commits": data["commits"],
        "gates": [
            {
                "gate_id": gate["gate_id"],
                "repo": gate["repo"],
                "verdict": gate["verdict"],
                "timestamp": gate["timestamp"],
            }
            for gate in data["gates"]
        ],
        "summary": data["last_summary"],
    }
    target = Path(summary_file) if summary_file else summary_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return target

def _finalize_closed_task(data: dict[str, Any], args: argparse.Namespace) -> tuple[Path, Path]:
    data["status"] = "CLOSED"
    data["current_phase"] = "closed"
    data["updated_at_utc"] = utc_now()
    data["last_summary"] = args.summary or "Task closed by package closure validator."
    archive_path = _archive_closed_checkpoint(data)
    delete_ownership_baseline(state_dir(), data.get("ownership_baseline"))
    active_path = active_task_path(data["task_id"])
    if active_path.exists():
        active_path.unlink()
    return archive_path, _write_final_summary(data, args.summary_file)

def close_task(args: argparse.Namespace) -> int:
    task_id = resolve_task_id(getattr(args, "task_id", None))
    active_path = active_task_path(task_id)
    with RegistryLock():
        data = load_checkpoint(task_id)
        issues = closure_issues(data)
        payload = {
            "ok": not issues,
            "verdict": "PASS" if not issues else "FAIL",
            "task_id": data["task_id"],
            "issues": issues,
            "checkpoint": str(active_path),
        }
        if issues:
            _print_closure(payload, issues, args.json)
            atomic_write(data, active_path)
            return 1
        if args.validate_only:
            _print_closure(payload, issues, args.json)
            return 0
        archive_path, target = _finalize_closed_task(data, args)
        if args.json:
            payload["summary_file"] = str(target)
            payload["archived"] = str(archive_path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"summary_file: {target}")
            print(f"archived: {archive_path}")
    return 0

def _print_active_tasks(as_json: bool) -> None:
    migrate_legacy_checkpoint_if_present()
    active_ids = list_active_task_ids()
    if as_json:
        print(json.dumps({"active": active_ids}, ensure_ascii=False, indent=2))
        return
    print(f"active_tasks: {len(active_ids)}")
    for task_id in active_ids:
        print(f"- {task_id}")

def status_task(args: argparse.Namespace) -> int:
    if getattr(args, "all", False):
        _print_active_tasks(args.json)
        return 0
    data = load_checkpoint(getattr(args, "task_id", None))
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_summary(data, "STATUS")
        print(f"checkpoint: {active_task_path(data['task_id'])}")
    return 0

def resume_task(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    refresh_git_fields(data)
    print_summary(data, "RESUME")
    print("--- recovery ---")
    mismatches = git_mismatches(data)
    if mismatches:
        print("action: reconcile git_state_mismatch before commit (re-baseline or sync recorded SHAs)")
        for item in mismatches:
            print(f"  mismatch: {item}")
    dirty_owned = sorted(
        set(data.get("own_unstaged_files", [])) | set(data.get("own_untracked_files", []))
    )
    if dirty_owned:
        print("dirty task-owned paths:")
        for item in dirty_owned[:20]:
            print(f"  {item}")
        if len(dirty_owned) > 20:
            print(f"  ... +{len(dirty_owned) - 20} more")
    else:
        print("dirty task-owned paths: none")
    if data.get("next_action"):
        print(f"resume_hint: {data['next_action']}")
    return 0

def _release_baseline_for(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        delete_ownership_baseline(state_dir(), payload.get("ownership_baseline"))
    except (OSError, json.JSONDecodeError, TypeError):
        pass

def _backup_removed_state(path: Path, task_id: str) -> None:
    backup_dir = state_dir() / "tasks" / "cleanup-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{task_id}-{int(time.time())}.json"
    shutil.copy2(path, backup)
    print(f"archived: {backup}")

def _remove_state_file(path: Path, task_id: str, archive: bool) -> None:
    _release_baseline_for(path)
    if archive:
        _backup_removed_state(path, task_id)
    path.unlink()
    print(f"removed: {path}")

def _remove_task_state(task_id: str, archive: bool) -> bool:
    candidates = (active_task_path(task_id), archive_task_path(task_id), legacy_checkpoint_path())
    existing = [path for path in candidates if path.exists()]
    for path in existing:
        _remove_state_file(path, task_id, archive)
    return bool(existing)

def _remove_legacy_state(archive: bool) -> None:
    legacy = legacy_checkpoint_path()
    if not legacy.exists():
        return
    if archive:
        backup = legacy.with_name(f"{legacy.stem}.closed-{int(time.time())}.json")
        shutil.copy2(legacy, backup)
        print(f"archived: {backup}")
    legacy.unlink()
    print(f"removed: {legacy}")

def remove_state(args: argparse.Namespace) -> int:
    migrate_legacy_checkpoint_if_present()
    if not args.task_id:
        _remove_legacy_state(args.archive)
        return 0
    task_id = sanitize_task_id(args.task_id)
    if not _remove_task_state(task_id, args.archive):
        print(f"no checkpoint found for task {task_id}")
    return 0

def list_tasks_cmd(args: argparse.Namespace) -> int:
    args.all = True
    return status_task(args)
