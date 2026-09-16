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
from typing import Any, Callable

from ai_os_task_constants import (
    ACTIVE_TASK_STATUSES, ALLOWED_CLASSES, ALLOWED_PUBLICATION_MODES, ALLOWED_STATUSES,
    LEGACY_SCHEMA_VERSIONS, SCHEMA_VERSION, WORKSPACE,
)
from ai_os_task_errors import TaskError
from ai_os_task_git import git_branch, git_head, repo_path
from ai_os_task_locks import RegistryLock, TaskCheckpointLock
from ai_os_task_paths import (
    active_task_path, archive_task_path, legacy_checkpoint_path, list_active_task_ids,
    sanitize_task_id, state_dir, summary_path, tasks_active_dir, utc_now,
)
from ai_os_task_scope import scopes_conflict
from ai_os_task_ownership import (
    OWNERSHIP_BASELINE_VERSION, OwnershipError, assess_ownership, empty_ownership_baseline,
)

def migrate_legacy_checkpoint() -> None:
    legacy = legacy_checkpoint_path()
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskError(f"legacy checkpoint is corrupt JSON: {legacy}: {exc}") from exc
    if data.get("schema_version") in LEGACY_SCHEMA_VERSIONS:
        data = migrate_checkpoint(data)
    validate_checkpoint(data)
    task_id = sanitize_task_id(str(data["task_id"]))
    active_path = active_task_path(task_id)
    archive_path = archive_task_path(task_id)
    if data.get("status") == "CLOSED":
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if archive_path.exists():
            backup = archive_path.with_name(f"{archive_path.stem}.legacy-{int(time.time())}.json")
            shutil.copy2(archive_path, backup)
        shutil.move(str(legacy), str(archive_path))
        return
    active_path.parent.mkdir(parents=True, exist_ok=True)
    if active_path.exists():
        backup = active_path.with_name(f"{active_path.stem}.legacy-{int(time.time())}.json")
        shutil.copy2(active_path, backup)
    shutil.move(str(legacy), str(active_path))

def resolve_task_id(explicit: str | None = None) -> str:
    if explicit:
        return sanitize_task_id(explicit)
    env_id = os.environ.get("AI_OS_TASK_ID", "").strip()
    if env_id:
        return sanitize_task_id(env_id)
    active = list_active_task_ids()
    if len(active) == 1:
        return active[0]
    if not active:
        raise TaskError("no active task; run task-start or pass --task-id / AI_OS_TASK_ID")
    raise TaskError(
        f"multiple active tasks ({len(active)}): {', '.join(active)}; pass --task-id or AI_OS_TASK_ID"
    )

def migrate_legacy_checkpoint_if_present() -> None:
    if legacy_checkpoint_path().exists():
        with RegistryLock():
            migrate_legacy_checkpoint()

def _active_checkpoint_path(resolved: str) -> Path:
    path = active_task_path(resolved)
    if path.exists():
        return path
    archived = archive_task_path(resolved)
    if archived.exists():
        raise TaskError(f"task {resolved} is archived; start a new task or recover from {archived}")
    raise TaskError(f"active checkpoint not found for task {resolved}: {path}")

def _read_checkpoint_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskError(f"checkpoint is corrupt JSON: {path}: {exc}") from exc

def _require_active_identity(data: dict[str, Any], resolved: str) -> None:
    if data["task_id"] != resolved:
        raise TaskError(f"checkpoint task_id mismatch: file={data['task_id']} requested={resolved}")
    if data["status"] not in ACTIVE_TASK_STATUSES:
        raise TaskError(f"task {resolved} is not active (status={data['status']})")

def load_checkpoint(task_id: str | None = None) -> dict[str, Any]:
    migrate_legacy_checkpoint_if_present()
    resolved = resolve_task_id(task_id)
    path = _active_checkpoint_path(resolved)
    data = _read_checkpoint_json(path)
    if data.get("schema_version") in LEGACY_SCHEMA_VERSIONS:
        data = migrate_checkpoint(data)
        atomic_write(data, path)
    validate_checkpoint(data)
    _require_active_identity(data, resolved)
    return data

def load_all_active_checkpoints(*, exclude: str | None = None) -> list[dict[str, Any]]:
    migrate_legacy_checkpoint_if_present()
    excluded = sanitize_task_id(exclude) if exclude else None
    checkpoints: list[dict[str, Any]] = []
    for task_id in list_active_task_ids():
        if excluded and task_id == excluded:
            continue
        checkpoints.append(load_checkpoint(task_id))
    return checkpoints

def find_scope_conflicts(
    scope: list[dict[str, str]],
    *,
    exclude_task_id: str | None = None,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for existing in load_all_active_checkpoints(exclude=exclude_task_id):
        overlapping = scopes_conflict(scope, existing["declared_write_scope"])
        if overlapping:
            left, right = overlapping[0]
            conflicts.append(
                {
                    "task_id": existing["task_id"],
                    "existing_scope": f"{right['repo']}:{right['path']}",
                    "requested_scope": f"{left['repo']}:{left['path']}",
                }
            )
    return conflicts

REQUIRED_CHECKPOINT_FIELDS: dict[str, type] = {
    "schema_version": int,
    "task_id": str,
    "task_title": str,
    "task_class": str,
    "workspace_path": str,
    "started_at_utc": str,
    "updated_at_utc": str,
    "status": str,
    "current_phase": str,
    "target_repositories": list,
    "baseline_shas": dict,
    "current_shas": dict,
    "declared_write_scope": list,
    "own_staged_files": list,
    "own_unstaged_files": list,
    "own_untracked_files": list,
    "ownership_baseline": dict,
    "adopted_baseline_scope": list,
    "ownership_conflicts": list,
    "decisions": list,
    "completed_steps": list,
    "gates": list,
    "commits": list,
    "blockers": list,
    "next_action": str,
    "proof_limits": dict,
    "last_summary": str,
    "publication_mode": str,
    "commit_policy": str,
    "baseline_branches": dict,
    "current_branches": dict,
    "commit_evaluations": list,
}

ENUM_CHECKPOINT_FIELDS: tuple[tuple[str, set[str], str], ...] = (
    ("status", ALLOWED_STATUSES, "invalid status"),
    ("task_class", ALLOWED_CLASSES, "invalid task_class"),
    ("publication_mode", ALLOWED_PUBLICATION_MODES, "invalid publication_mode"),
)

def _validate_field_types(data: dict[str, Any]) -> None:
    for key, expected in REQUIRED_CHECKPOINT_FIELDS.items():
        if key not in data:
            raise TaskError(f"checkpoint missing key: {key}")
        if not isinstance(data[key], expected):
            raise TaskError(f"checkpoint key has wrong type: {key}")

def _validate_enum_fields(data: dict[str, Any]) -> None:
    for key, allowed, label in ENUM_CHECKPOINT_FIELDS:
        if data[key] not in allowed:
            raise TaskError(f"{label}: {data[key]}")

def validate_checkpoint(data: dict[str, Any]) -> None:
    _validate_field_types(data)
    if data["schema_version"] != SCHEMA_VERSION:
        raise TaskError(f"unsupported checkpoint schema_version: {data['schema_version']}")
    _validate_enum_fields(data)
    if data["commit_policy"] != "AUTO_LOCAL":
        raise TaskError(f"unsupported commit_policy: {data['commit_policy']}")
    if data["ownership_baseline"].get("version") != OWNERSHIP_BASELINE_VERSION:
        raise TaskError("unsupported ownership_baseline version")

V1_ACTIVITY_KEYS = (
    "own_staged_files",
    "own_unstaged_files",
    "own_untracked_files",
    "decisions",
    "completed_steps",
    "gates",
    "commits",
    "blockers",
)

def _is_pristine_v1(data: dict[str, Any]) -> bool:
    return (
        data.get("status") == "INITIALIZED"
        and data.get("current_phase") == "task-start"
        and data.get("current_shas") == data.get("baseline_shas")
        and all(not data.get(key) for key in V1_ACTIVITY_KEYS)
    )

def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    if not _is_pristine_v1(data):
        raise TaskError(
            "legacy checkpoint schema_version 1 has no ownership baseline; "
            "start a new checkpoint (historical state was not modified)"
        )
    migrated = dict(data)
    migrated["ownership_baseline"] = empty_ownership_baseline(migrated["started_at_utc"])
    migrated["adopted_baseline_scope"] = []
    migrated["ownership_conflicts"] = []
    return migrated

def _migrate_v2_to_current(data: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(data)
    repos = migrated.get("target_repositories", [])
    migrated["schema_version"] = SCHEMA_VERSION
    migrated["publication_mode"] = "PUBLISH"
    migrated["commit_policy"] = "AUTO_LOCAL"
    migrated["baseline_branches"] = {repo: git_branch(repo) for repo in repos}
    migrated["current_branches"] = dict(migrated["baseline_branches"])
    migrated["commit_evaluations"] = []
    return migrated

def migrate_checkpoint(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("schema_version")
    if version == 1:
        data = _migrate_v1_to_v2(data)
        version = 2
    if version == 2:
        return _migrate_v2_to_current(data)
    raise TaskError(f"unsupported checkpoint schema_version: {version}")


def _write_checkpoint_file(data: dict[str, Any], target: Path) -> None:
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    loaded = json.loads(tmp.read_text(encoding="utf-8"))
    validate_checkpoint(loaded)
    os.replace(tmp, target)

def atomic_write(data: dict[str, Any], path: Path | None = None) -> None:
    validate_checkpoint(data)
    target = path or active_task_path(data["task_id"])
    target.parent.mkdir(parents=True, exist_ok=True)

    # Serialize RMW on active checkpoint files; archive/summary writes stay unlocked.
    if target.parent == tasks_active_dir():
        with TaskCheckpointLock(str(data["task_id"])):
            _write_checkpoint_file(data, target)
    else:
        _write_checkpoint_file(data, target)


def mutate_active_checkpoint(
    task_id: str | None,
    mutate: Callable[[dict[str, Any]], None],
    *,
    refresh: bool = True,
) -> dict[str, Any]:
    migrate_legacy_checkpoint_if_present()
    resolved = resolve_task_id(task_id)
    path = _active_checkpoint_path(resolved)
    with TaskCheckpointLock(resolved):
        data = _read_checkpoint_json(path)
        if data.get("schema_version") in LEGACY_SCHEMA_VERSIONS:
            data = migrate_checkpoint(data)
        validate_checkpoint(data)
        _require_active_identity(data, resolved)
        mutate(data)
        if refresh:
            refresh_git_fields(data)
        validate_checkpoint(data)
        _write_checkpoint_file(data, path)
    return data

def refresh_git_fields(data: dict[str, Any]) -> None:
    data["current_shas"] = {repo: git_head(repo) for repo in data["target_repositories"]}
    data["current_branches"] = {repo: git_branch(repo) for repo in data["target_repositories"]}
    try:
        ownership = assess_ownership(
            {repo: repo_path(repo) for repo in data["target_repositories"]},
            data["declared_write_scope"],
            data["ownership_baseline"],
            data["adopted_baseline_scope"],
            state_dir(),
        )
    except OwnershipError as exc:
        raise TaskError(str(exc)) from exc
    data["own_staged_files"] = ownership["staged"]
    data["own_unstaged_files"] = ownership["unstaged"]
    data["own_untracked_files"] = ownership["untracked"]
    data["ownership_conflicts"] = ownership["conflicts"]
    data["updated_at_utc"] = utc_now()

def git_mismatches(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for repo, recorded in data["current_shas"].items():
        current = git_head(repo)
        if current != recorded:
            issues.append(f"{repo}: recorded {recorded[:7]}, current {current[:7]}")
    return issues

def print_summary(data: dict[str, Any], prefix: str = "TASK") -> None:
    gates = data["gates"]
    last_gate = gates[-1] if gates else None
    print(f"{prefix}: {data['task_id']} [{data['status']}] {data['current_phase']}")
    print(f"title: {data['task_title']}")
    print(f"class: {data['task_class']}")
    print(f"repos: {', '.join(data['target_repositories'])}")
    print(f"scope: {', '.join(f'{s['repo']}:{s['path']}' for s in data['declared_write_scope'])}")
    print(f"publication: {data['publication_mode']}")
    for repo in data["target_repositories"]:
        branch = data.get("current_branches", {}).get(repo, "")
        print(f"branch[{repo}]: {branch or "<detached>"}")
    if data["commits"]:
        print(f"last_commit: {data['commits'][-1]}")
    if last_gate:
        print(f"last_gate: {last_gate['gate_id']} {last_gate['verdict']}")
    print(f"next: {data['next_action'] or '<none>'}")
    if data["blockers"]:
        print(f"blockers: {len(data['blockers'])}")
    if data["ownership_conflicts"]:
        print(f"ownership_conflicts: {len(data['ownership_conflicts'])}")
    mismatches = git_mismatches(data)
    if mismatches:
        print("git_state_mismatch: " + "; ".join(mismatches))
