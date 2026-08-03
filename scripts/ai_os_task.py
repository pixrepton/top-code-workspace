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

from ai_os_task_ownership import (
    OWNERSHIP_BASELINE_VERSION,
    OwnershipError,
    assess_ownership,
    capture_ownership_baseline,
    collect_raw_git_state,
    delete_ownership_baseline,
    empty_ownership_baseline,
    prepare_owned_commit_states,
    scope_contains,
)


WORKSPACE = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 3
LEGACY_SCHEMA_VERSIONS = {1, 2}
ALLOWED_STATUSES = {
    "INITIALIZED",
    "IN_PROGRESS",
    "BLOCKED",
    "READY_TO_CLOSE",
    "CLOSED",
    "ABORTED_WITH_EVIDENCE",
}
ALLOWED_CLASSES = {"SMALL", "MEDIUM", "CRITICAL"}
ALLOWED_PUBLICATION_MODES = {"LOCAL_ONLY", "PUBLISH", "SHIP"}
ACTIVE_TASK_STATUSES = {"INITIALIZED", "IN_PROGRESS", "BLOCKED", "READY_TO_CLOSE"}
PROTECTED_BRANCH_NAMES = {"main", "master", "trunk"}
PASSING_GATE_VERDICTS = {"PASS", "DEDUPLICATED"}
REGISTRY_LOCK_NAME = "registry.lock"
REGISTRY_LOCK_STALE_SECONDS = 30
REGISTRY_LOCK_TIMEOUT_SECONDS = 10
REPO_COMMIT_LOCK_TIMEOUT_SECONDS = 10
TASK_CHECKPOINT_LOCK_TIMEOUT_SECONDS = 10
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_HELD_FILE_LOCKS: set[str] = set()
FROZEN_PATHS = {
    "knowledge": {
        "system-atlas/workflows/WORKFLOW_REGISTRY.yaml",
        "system-atlas/workflows/WORKFLOW_EVIDENCE.jsonl",
    }
}
SECRET_PATH_PATTERNS = (
    re.compile(r"(^|/)(?:\.env(?:\..+)?|credentials(?:\..+)?|id_(?:rsa|dsa|ecdsa|ed25519)|[^/]+\.(?:pem|p12|pfx|key))$", re.I),
)
SECRET_CONTENT_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("OpenAI-style secret", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Anthropic secret", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
)

FORBIDDEN_COMMAND_MARKERS = (
    "git push",
    "git reset",
    "git clean",
    "ssh ",
    "scp ",
    "deploy",
    "kubectl ",
)


class TaskError(RuntimeError):
    pass


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


def checkpoint_path() -> Path:
    """Backward-compatible path hint; prefer active_task_path(task_id)."""
    active = list_active_task_ids()
    if len(active) == 1:
        return active_task_path(active[0])
    return legacy_checkpoint_path()


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


def normalize_scope_path(path: str) -> str:
    raw = path.replace("\\", "/").strip()
    if raw in {"", ".", "*"}:
        return "*"
    parts: list[str] = []
    for segment in raw.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts) if parts else "*"


def scope_entries_overlap(left: dict[str, str], right: dict[str, str]) -> bool:
    if left["repo"] != right["repo"]:
        return False
    left_path = normalize_scope_path(left["path"])
    right_path = normalize_scope_path(right["path"])
    if left_path == "*" or right_path == "*":
        return True
    if left_path == right_path:
        return True
    return left_path.startswith(right_path + "/") or right_path.startswith(left_path + "/")


def scopes_conflict(left: list[dict[str, str]], right: list[dict[str, str]]) -> list[tuple[dict[str, str], dict[str, str]]]:
    pairs: list[tuple[dict[str, str], dict[str, str]]] = []
    for left_item in left:
        for right_item in right:
            if scope_entries_overlap(left_item, right_item):
                pairs.append((left_item, right_item))
    return pairs


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
                return False
            return int(exit_code.value) == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_lock_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("pid="):
            raw = line.split("=", 1)[1].strip().split()[0]
            try:
                return int(raw)
            except ValueError:
                return None
    return None


class FilePidLock:
    """Exclusive file lock with PID liveness checks (reentrant in-process)."""

    def __init__(
        self,
        path: Path,
        *,
        label: str,
        timeout_seconds: float,
        allow_wait: bool = True,
    ) -> None:
        self.path = path
        self.label = label
        self.timeout_seconds = timeout_seconds
        self.allow_wait = allow_wait
        self.fd: int | None = None
        self._nested = False
        self._key = ""

    def __enter__(self) -> FilePidLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = str(self.path.resolve())
        if self._key in _HELD_FILE_LOCKS:
            self._nested = True
            return self
        deadline = time.time() + self.timeout_seconds
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"pid={os.getpid()} time={utc_now()}\n".encode())
                _HELD_FILE_LOCKS.add(self._key)
                return self
            except FileExistsError as exc:
                owner_pid = _read_lock_pid(self.path)
                if owner_pid is not None and not _pid_is_alive(owner_pid):
                    try:
                        self.path.unlink()
                        continue
                    except FileNotFoundError:
                        continue
                if not self.allow_wait:
                    age = time.time() - self.path.stat().st_mtime if self.path.exists() else 0.0
                    raise TaskError(
                        f"{self.label} already exists: {self.path} "
                        f"(pid={owner_pid if owner_pid is not None else '?'} age {age:.0f}s)"
                    ) from exc
                if time.time() >= deadline:
                    raise TaskError(f"{self.label} timeout: {self.path}") from exc
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._nested:
            return
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        _HELD_FILE_LOCKS.discard(self._key)


class RegistryLock(FilePidLock):
    def __init__(self) -> None:
        super().__init__(
            state_dir() / "locks" / REGISTRY_LOCK_NAME,
            label="registry lock",
            timeout_seconds=REGISTRY_LOCK_TIMEOUT_SECONDS,
            allow_wait=True,
        )


class TaskCheckpointLock(FilePidLock):
    def __init__(self, task_id: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)
        super().__init__(
            state_dir() / "locks" / f"task-{safe}.lock",
            label="task checkpoint lock",
            timeout_seconds=TASK_CHECKPOINT_LOCK_TIMEOUT_SECONDS,
            allow_wait=True,
        )


def list_active_task_ids() -> list[str]:
    directory = tasks_active_dir()
    if not directory.exists():
        return []
    return sorted(
        path.stem
        for path in directory.glob("*.json")
        if TASK_ID_PATTERN.fullmatch(path.stem)
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


def load_checkpoint(task_id: str | None = None) -> dict[str, Any]:
    if legacy_checkpoint_path().exists():
        with RegistryLock():
            migrate_legacy_checkpoint()
    resolved = resolve_task_id(task_id)
    path = active_task_path(resolved)
    if not path.exists():
        archived = archive_task_path(resolved)
        if archived.exists():
            raise TaskError(f"task {resolved} is archived; start a new task or recover from {archived}")
        raise TaskError(f"active checkpoint not found for task {resolved}: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskError(f"checkpoint is corrupt JSON: {path}: {exc}") from exc
    if data.get("schema_version") in LEGACY_SCHEMA_VERSIONS:
        data = migrate_checkpoint(data)
        atomic_write(data, path)
    validate_checkpoint(data)
    if data["task_id"] != resolved:
        raise TaskError(f"checkpoint task_id mismatch: file={data['task_id']} requested={resolved}")
    if data["status"] not in ACTIVE_TASK_STATUSES:
        raise TaskError(f"task {resolved} is not active (status={data['status']})")
    return data


def load_all_active_checkpoints(*, exclude: str | None = None) -> list[dict[str, Any]]:
    if legacy_checkpoint_path().exists():
        with RegistryLock():
            migrate_legacy_checkpoint()
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


def run(args: list[str], cwd: Path, check: bool = True, text: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=str(cwd), text=text, capture_output=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise TaskError(f"command failed ({proc.returncode}): {' '.join(args)}\n{detail}")
    return proc


def repo_path(repo: str) -> Path:
    if repo in {".", "root", "workspace"}:
        path = WORKSPACE
    else:
        path = WORKSPACE / repo
    if not path.exists():
        raise TaskError(f"repo path does not exist: {path}")
    if not (path / ".git").exists():
        raise TaskError(f"path is not a git repository root: {path}")
    return path.resolve()


def git_head(repo: str) -> str:
    return run(["git", "rev-parse", "--verify", "HEAD"], repo_path(repo)).stdout.strip()


def git_short_head(repo: str) -> str:
    return git_head(repo)[:7]


def git_branch(repo: str) -> str:
    return run(["git", "branch", "--show-current"], repo_path(repo)).stdout.strip()


def git_default_branch(repo: str) -> str:
    path = repo_path(repo)
    remote = run(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], path, check=False)
    if remote.returncode == 0 and remote.stdout.strip():
        return remote.stdout.strip().split("/", 1)[-1]
    for candidate in ("main", "master", "trunk"):
        if run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"], path, check=False).returncode == 0:
            return candidate
    return ""


def branch_is_protected(repo: str, branch: str) -> bool:
    if not branch:
        return True
    default = git_default_branch(repo)
    return branch in PROTECTED_BRANCH_NAMES or (default and branch == default)


def git_operation_in_progress(repo: str) -> str:
    path = repo_path(repo)
    git_dir_raw = run(["git", "rev-parse", "--git-dir"], path).stdout.strip()
    git_dir = Path(git_dir_raw)
    if not git_dir.is_absolute():
        git_dir = (path / git_dir).resolve()
    checks = {
        "merge": git_dir / "MERGE_HEAD",
        "cherry-pick": git_dir / "CHERRY_PICK_HEAD",
        "revert": git_dir / "REVERT_HEAD",
        "rebase": git_dir / "rebase-merge",
        "rebase-apply": git_dir / "rebase-apply",
    }
    for name, candidate in checks.items():
        if candidate.exists():
            return name
    return ""


def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def parse_scope(values: list[str]) -> list[dict[str, str]]:
    scope: list[dict[str, str]] = []
    for raw in values:
        if ":" not in raw:
            raise TaskError(f"scope must use repo:path form: {raw}")
        repo, rel = raw.split(":", 1)
        repo = repo.strip()
        rel = normalize_rel(rel)
        if not repo or not rel:
            raise TaskError(f"invalid scope: {raw}")
        scope.append({"repo": repo, "path": rel})
    return scope


def scopes_for_repo(scope: list[dict[str, str]], repo: str) -> list[str]:
    paths = [item["path"] for item in scope if item["repo"] == repo]
    return paths or ["."]


def sha256_bytes(parts: list[bytes]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()


def sha256_text(parts: list[str]) -> str:
    return sha256_bytes([part.encode("utf-8", errors="replace") for part in parts])


def git_blob(args: list[str], cwd: Path) -> bytes:
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True)
    if proc.returncode != 0:
        raise TaskError(f"git command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr.decode(errors='replace')}")
    return proc.stdout


def staged_diff_hash(repo: str) -> str:
    path = repo_path(repo)
    return sha256_bytes([git_blob(["git", "diff", "--cached", "--binary"], path)])


def untracked_file_hashes(path: Path, rel_paths: list[str]) -> list[str]:
    status = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *rel_paths], path).stdout.splitlines()
    values: list[str] = []
    for line in status:
        if not line.startswith("?? "):
            continue
        rel = normalize_rel(line[3:])
        full = path / rel
        if full.is_file():
            values.append(f"{rel}:{hashlib.sha256(full.read_bytes()).hexdigest()}")
    return values


def scope_hash(repo: str, rel_paths: list[str]) -> str:
    path = repo_path(repo)
    status = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *rel_paths], path).stdout
    diff = git_blob(["git", "diff", "--binary", "--", *rel_paths], path)
    untracked = "\n".join(sorted(untracked_file_hashes(path, rel_paths)))
    return sha256_bytes([status.encode("utf-8"), diff, untracked.encode("utf-8")])


def config_hash(repo: str, values: list[str]) -> str:
    if not values:
        return sha256_text([""])
    path = repo_path(repo)
    parts: list[bytes] = []
    for raw in values:
        candidate = Path(raw)
        full = candidate if candidate.is_absolute() else path / raw
        if not full.exists():
            parts.append(f"MISSING:{raw}".encode())
        elif full.is_file():
            parts.append(f"FILE:{normalize_rel(raw)}".encode())
            parts.append(full.read_bytes())
        else:
            parts.append(f"DIR:{normalize_rel(raw)}".encode())
    return sha256_bytes(parts)


def validate_checkpoint(data: dict[str, Any]) -> None:
    required = {
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
    for key, expected in required.items():
        if key not in data:
            raise TaskError(f"checkpoint missing key: {key}")
        if not isinstance(data[key], expected):
            raise TaskError(f"checkpoint key has wrong type: {key}")
    if data["schema_version"] != SCHEMA_VERSION:
        raise TaskError(f"unsupported checkpoint schema_version: {data['schema_version']}")
    if data["status"] not in ALLOWED_STATUSES:
        raise TaskError(f"invalid status: {data['status']}")
    if data["task_class"] not in ALLOWED_CLASSES:
        raise TaskError(f"invalid task_class: {data['task_class']}")
    if data["publication_mode"] not in ALLOWED_PUBLICATION_MODES:
        raise TaskError(f"invalid publication_mode: {data['publication_mode']}")
    if data["commit_policy"] != "AUTO_LOCAL":
        raise TaskError(f"unsupported commit_policy: {data['commit_policy']}")
    if data["ownership_baseline"].get("version") != OWNERSHIP_BASELINE_VERSION:
        raise TaskError("unsupported ownership_baseline version")


def migrate_checkpoint(data: dict[str, Any]) -> dict[str, Any]:
    version = data.get("schema_version")
    if version == 1:
        activity_keys = (
            "own_staged_files",
            "own_unstaged_files",
            "own_untracked_files",
            "decisions",
            "completed_steps",
            "gates",
            "commits",
            "blockers",
        )
        pristine = (
            data.get("status") == "INITIALIZED"
            and data.get("current_phase") == "task-start"
            and data.get("current_shas") == data.get("baseline_shas")
            and all(not data.get(key) for key in activity_keys)
        )
        if not pristine:
            raise TaskError(
                "legacy checkpoint schema_version 1 has no ownership baseline; "
                "start a new checkpoint (historical state was not modified)"
            )
        data = dict(data)
        data["ownership_baseline"] = empty_ownership_baseline(data["started_at_utc"])
        data["adopted_baseline_scope"] = []
        data["ownership_conflicts"] = []
        version = 2
    if version == 2:
        migrated = dict(data)
        repos = migrated.get("target_repositories", [])
        migrated["schema_version"] = SCHEMA_VERSION
        migrated["publication_mode"] = "LOCAL_ONLY"
        migrated["commit_policy"] = "AUTO_LOCAL"
        migrated["baseline_branches"] = {repo: git_branch(repo) for repo in repos}
        migrated["current_branches"] = dict(migrated["baseline_branches"])
        migrated["commit_evaluations"] = []
        return migrated
    raise TaskError(f"unsupported checkpoint schema_version: {version}")


def atomic_write(data: dict[str, Any], path: Path | None = None) -> None:
    validate_checkpoint(data)
    target = path or active_task_path(data["task_id"])
    target.parent.mkdir(parents=True, exist_ok=True)

    def _write() -> None:
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        loaded = json.loads(tmp.read_text(encoding="utf-8"))
        validate_checkpoint(loaded)
        os.replace(tmp, target)

    # Serialize RMW on active checkpoint files; archive/summary writes stay unlocked.
    if target.parent == tasks_active_dir():
        with TaskCheckpointLock(str(data["task_id"])):
            _write()
    else:
        _write()


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


def new_checkpoint(args: argparse.Namespace) -> int:
    scope = parse_scope(args.scope)
    adopted = parse_scope(args.adopt_baseline or [])
    for item in adopted:
        if not scope_contains(scope, item):
            raise TaskError(f"adopted baseline path must be inside declared scope: {item['repo']}:{item['path']}")
    task_id = sanitize_task_id(args.task_id)
    with RegistryLock():
        migrate_legacy_checkpoint()
        active_path = active_task_path(task_id)
        if active_path.exists() and not args.replace:
            raise TaskError(
                f"active task already exists for {task_id}; use task-status/task-resume or --replace: {active_path}"
            )
        if active_path.exists() and args.replace:
            try:
                previous = json.loads(active_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = None
            if previous:
                delete_ownership_baseline(state_dir(), previous.get("ownership_baseline"))
        conflicts = find_scope_conflicts(scope, exclude_task_id=task_id if args.replace else None)
        if conflicts:
            first = conflicts[0]
            raise TaskError(
                "scope conflict with active task "
                f"{first['task_id']}: requested {first['requested_scope']} overlaps {first['existing_scope']}"
            )
        repos = args.repo or sorted({item["repo"] for item in scope})
        baseline = {repo: git_head(repo) for repo in repos}
        now = utc_now()
        try:
            ownership_baseline = capture_ownership_baseline(
                {repo: repo_path(repo) for repo in repos},
                scope,
                baseline,
                adopted,
                state_dir(),
                now,
            )
        except OwnershipError as exc:
            raise TaskError(str(exc)) from exc
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
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
            "baseline_branches": {repo: git_branch(repo) for repo in repos},
            "current_branches": {repo: git_branch(repo) for repo in repos},
            "commit_evaluations": [],
        }
        refresh_git_fields(data)
        atomic_write(data, active_path)
    print_summary(data, "INITIALIZED")
    print(f"checkpoint: {active_path}")
    return 0


def update_checkpoint(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
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
    for value in args.decision or []:
        data["decisions"].append({"timestamp": utc_now(), "text": value})
    for value in args.step or []:
        data["completed_steps"].append({"timestamp": utc_now(), "text": value})
    for value in args.blocker or []:
        data["blockers"].append({"timestamp": utc_now(), "status": "OPEN", "text": value})
    for value in args.resolve_blocker or []:
        for blocker in data["blockers"]:
            if blocker.get("text") == value:
                blocker["status"] = "RESOLVED"
                blocker["resolved_at_utc"] = utc_now()
    for value in args.commit or []:
        if value not in data["commits"]:
            data["commits"].append(value)
    refresh_git_fields(data)
    atomic_write(data)
    print_summary(data, "CHECKPOINT")
    return 0


def gate_fingerprint(args: argparse.Namespace, data: dict[str, Any]) -> dict[str, Any]:
    repo = args.repo
    rel_paths = args.scope or scopes_for_repo(data["declared_write_scope"], repo)
    runtime_identity = args.runtime_id or ""
    if args.runtime_command:
        proc = run(args.runtime_command, repo_path(repo), check=False)
        runtime_identity = (proc.stdout or proc.stderr).strip()
    return {
        "head_sha": git_head(repo),
        "staged_diff_hash": staged_diff_hash(repo),
        "scope_hash": scope_hash(repo, rel_paths),
        "config_hash": config_hash(repo, args.config_path or []),
        "config_paths": [normalize_rel(path) for path in (args.config_path or [])],
        "runtime_identity": runtime_identity,
        "scope": [normalize_rel(p) for p in rel_paths],
    }


def previous_matching_pass(data: dict[str, Any], gate_id: str, repo: str, fingerprint: dict[str, Any]) -> dict[str, Any] | None:
    for entry in reversed(data["gates"]):
        if entry.get("gate_id") != gate_id or entry.get("repo") != repo:
            continue
        if entry.get("verdict") != "PASS":
            continue
        if entry.get("fingerprint") == fingerprint:
            return entry
    return None


def command_contains_forbidden(command: list[str]) -> list[str]:
    rendered = " ".join(command).lower()
    return [marker for marker in FORBIDDEN_COMMAND_MARKERS if marker in rendered]


def run_gate(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    if args.repo not in data["target_repositories"]:
        raise TaskError(f"gate repo is not in checkpoint target_repositories: {args.repo}")
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise TaskError("task-gate requires a command after --")
    forbidden = command_contains_forbidden(command)
    if forbidden:
        raise TaskError(f"refusing forbidden command marker(s): {', '.join(forbidden)}")
    fingerprint = gate_fingerprint(args, data)
    previous = None if args.always_fresh else previous_matching_pass(data, args.gate_id, args.repo, fingerprint)
    start = time.time()
    if previous:
        entry = {
            "gate_id": args.gate_id,
            "repo": args.repo,
            "command": " ".join(command),
            "working_directory": str(repo_path(args.repo)),
            "timestamp": utc_now(),
            "exit_code": 0,
            "verdict": "DEDUPLICATED",
            "duration_seconds": 0.0,
            "fingerprint": fingerprint,
            "log_path": "",
            "short_result": f"deduplicated from {previous['timestamp']}",
            "limitations": "Skipped because previous PASS has identical HEAD, staged diff, scope, config, and runtime identity.",
            "deduplicated_from": previous["timestamp"],
        }
        data["gates"].append(entry)
        data["current_phase"] = "gate-deduplicated"
        data["last_summary"] = f"{args.gate_id}: DEDUPLICATED"
        refresh_git_fields(data)
        atomic_write(data)
        print(f"GATE {args.gate_id}: DEDUPLICATED")
        print(entry["short_result"])
        return 0

    print(f"GATE {args.gate_id}: RUN")
    print("command: " + " ".join(command))
    proc = subprocess.run(command, cwd=str(repo_path(args.repo)), text=True, capture_output=True)
    duration = round(time.time() - start, 3)
    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    verdict = "PASS" if proc.returncode == 0 else "FAIL"
    short = args.summary or summarize_output(output, verdict)
    log_path = ""
    if args.log_path:
        target = Path(args.log_path)
        if not target.is_absolute():
            target = state_dir() / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8", newline="\n")
        log_path = str(target)
    entry = {
        "gate_id": args.gate_id,
        "repo": args.repo,
        "command": " ".join(command),
        "working_directory": str(repo_path(args.repo)),
        "timestamp": utc_now(),
        "exit_code": proc.returncode,
        "verdict": verdict,
        "duration_seconds": duration,
        "fingerprint": fingerprint,
        "log_path": log_path,
        "short_result": short,
        "limitations": args.limitations or "",
    }
    data["gates"].append(entry)
    data["current_phase"] = "gate-pass" if verdict == "PASS" else "gate-fail"
    data["last_summary"] = f"{args.gate_id}: {verdict} - {short}"
    refresh_git_fields(data)
    atomic_write(data)
    print(f"GATE {args.gate_id}: {verdict} ({duration}s)")
    print(f"summary: {short}")
    if proc.returncode != 0:
        tail = "\n".join(output.splitlines()[-40:])
        if tail:
            print(tail)
    return proc.returncode


def summarize_output(output: str, verdict: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return verdict
    return lines[-1][:500]



def open_blockers(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        blocker
        for blocker in data["blockers"]
        if blocker.get("status") not in {"RESOLVED", "DEFERRED_WITH_EVIDENCE", "ACCEPTED"}
    ]


def owned_paths_for_repo(data: dict[str, Any], repo: str) -> list[str]:
    prefix = f"{repo}:"
    values: set[str] = set()
    for key in ("own_staged_files", "own_unstaged_files", "own_untracked_files"):
        for item in data.get(key, []):
            if item.startswith(prefix):
                values.add(normalize_rel(item[len(prefix) :]))
    return sorted(values)


def latest_current_passing_gate(data: dict[str, Any], repo: str) -> dict[str, Any] | None:
    for gate in reversed(data.get("gates", [])):
        if gate.get("repo") != repo or gate.get("verdict") not in PASSING_GATE_VERDICTS:
            continue
        try:
            if recompute_gate_fingerprint_from_entry(gate) == gate.get("fingerprint"):
                return gate
        except TaskError:
            continue
    return None


def _secret_path_issue(path: str) -> str:
    normalized = normalize_rel(path)
    if normalized.lower().endswith((".env.example", ".env.sample", ".env.template")):
        return ""
    for pattern in SECRET_PATH_PATTERNS:
        if pattern.search(normalized):
            return f"sensitive path: {normalized}"
    return ""


def scan_commit_states_for_secrets(states: dict[str, dict[str, tuple[str, bytes | None]]]) -> list[str]:
    issues: list[str] = []
    for path, payload in states.items():
        path_issue = _secret_path_issue(path)
        if path_issue:
            issues.append(path_issue)
        kind, content = payload["commit"]
        if kind not in {"file", "symlink"} or content is None:
            continue
        for label, pattern in SECRET_CONTENT_PATTERNS:
            if pattern.search(content):
                issues.append(f"{path}: detected {label}")
    return sorted(set(issues))


def commit_plan_payload(data: dict[str, Any], repo: str) -> dict[str, Any]:
    if repo not in data["target_repositories"]:
        raise TaskError(f"commit repo is not in checkpoint target_repositories: {repo}")
    refresh_git_fields(data)
    reasons: list[str] = []
    warnings: list[str] = []
    branch = data["current_branches"].get(repo, "")
    operation = git_operation_in_progress(repo)
    if operation:
        reasons.append(f"git operation in progress: {operation}")
    if not branch:
        reasons.append("detached HEAD is not allowed for task commits")
    elif branch_is_protected(repo, branch):
        reasons.append(f"current branch is protected/default: {branch}; run task-branch first")
    if data["status"] == "BLOCKED":
        reasons.append("task status is BLOCKED")
    blockers = open_blockers(data)
    if blockers:
        reasons.append(f"open blockers remain: {len(blockers)}")
    owned_paths = owned_paths_for_repo(data, repo)
    if not owned_paths and not reasons:
        verdict = "NO_COMMIT"
        states: dict[str, dict[str, tuple[str, bytes | None]]] = {}
    else:
        gate = latest_current_passing_gate(data, repo)
        if owned_paths and gate is None:
            reasons.append("no current PASS/DEDUPLICATED gate matches the present repo state")
        try:
            states = prepare_owned_commit_states(
                repo,
                repo_path(repo),
                owned_paths,
                data["ownership_baseline"],
                data["adopted_baseline_scope"],
                state_dir(),
            )
        except OwnershipError as exc:
            states = {}
            reasons.append(str(exc))
        owned_keys = {f"{repo}:{path}" for path in owned_paths}
        for conflict in data["ownership_conflicts"]:
            key = conflict.split(": OWNERSHIP_", 1)[0]
            if key in owned_keys and states:
                warnings.append(
                    f"mixed baseline state isolated by commit wrapper (soft ownership conflict; "
                    f"commit proceeds with task-only delta): {key}"
                )
            else:
                reasons.append(conflict)
        secret_issues = scan_commit_states_for_secrets(states)
        reasons.extend(secret_issues)
        all_staged = collect_raw_git_state(repo_path(repo), ["."])["staged"]
        owned_staged = {
            normalize_rel(item.split(":", 1)[1])
            for item in data.get("own_staged_files", [])
            if item.startswith(f"{repo}:")
        }
        foreign_staged = sorted(all_staged - owned_staged)
        if foreign_staged:
            warnings.append(
                "foreign staged paths will be preserved through an isolated temporary index: "
                + ", ".join(foreign_staged)
            )
        verdict = "BLOCKED" if reasons else "COMMIT_READY"
    payload = {
        "verdict": verdict,
        "task_id": data["task_id"],
        "repo": repo,
        "branch": branch,
        "publication_mode": data["publication_mode"],
        "owned_paths": owned_paths,
        "reasons": reasons,
        "warnings": warnings,
        "suggested_message": f"chore({data['task_id']}): {data['task_title']}"[:100],
    }
    data["commit_evaluations"].append({"timestamp": utc_now(), **payload})
    data["commit_evaluations"] = data["commit_evaluations"][-20:]
    data["last_summary"] = f"commit-plan {repo}: {verdict}"
    atomic_write(data)
    return payload


def print_commit_plan(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"COMMIT PLAN: {payload['verdict']}")
    print(f"repo: {payload['repo']}")
    print(f"branch: {payload['branch'] or '<detached>'}")
    print(f"publication: {payload['publication_mode']}")
    if payload["owned_paths"]:
        print("paths: " + ", ".join(payload["owned_paths"]))
    for warning in payload["warnings"]:
        print(f"warning: {warning}")
    for reason in payload["reasons"]:
        print(f"blocked: {reason}")
    if payload["verdict"] == "COMMIT_READY":
        print(f"suggested_message: {payload['suggested_message']}")


def plan_commit(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    payload = commit_plan_payload(data, args.repo)
    print_commit_plan(payload, args.json)
    return 0 if payload["verdict"] in {"NO_COMMIT", "COMMIT_READY"} else 1


def _validate_commit_message(message: str) -> str:
    message = message.strip()
    if not message:
        raise TaskError("commit message is empty")
    subject = message.splitlines()[0].strip()
    if len(subject) > 100:
        raise TaskError("commit subject exceeds 100 characters")
    if subject.endswith("."):
        raise TaskError("commit subject should not end with a period")
    return message


def _git_env_with_index(index_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index_path)
    env["GIT_EDITOR"] = "true"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _run_git_env(repo_root: Path, args: list[str], env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(["git", *args], cwd=str(repo_root), env=env, capture_output=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode(errors="replace").strip()
        raise TaskError(f"git command failed ({proc.returncode}): git {' '.join(args)}\n{detail}")
    return proc


def _mode_for_state(repo_root: Path, path: str, state: tuple[str, bytes | None]) -> str:
    kind, _content = state
    if kind == "symlink":
        return "120000"
    existing = run(["git", "ls-tree", "HEAD", "--", path], repo_root, check=False).stdout.strip()
    if existing:
        return existing.split()[0]
    full = repo_root / path
    if full.exists() and os.access(full, os.X_OK):
        return "100755"
    return "100644"


def _write_state_blob(repo_root: Path, path: str, state: tuple[str, bytes | None]) -> tuple[str, str] | None:
    kind, content = state
    if kind == "missing":
        return None
    if content is None:
        raise TaskError(f"missing content for {path}")
    args = ["git", "hash-object", "-w", "--stdin"]
    if kind == "file":
        args = ["git", "hash-object", "-w", f"--path={path}", "--stdin"]
    proc = subprocess.run(args, cwd=str(repo_root), input=content, capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise TaskError(f"cannot write git blob for {path}: {detail}")
    return _mode_for_state(repo_root, path, state), proc.stdout.decode().strip()


def _set_index_state(
    repo_root: Path,
    path: str,
    state: tuple[str, bytes | None],
    *,
    env: dict[str, str] | None = None,
) -> None:
    effective = env or os.environ.copy()
    blob = _write_state_blob(repo_root, path, state)
    if blob is None:
        _run_git_env(repo_root, ["update-index", "--force-remove", "--", path], effective)
        return
    mode, oid = blob
    _run_git_env(repo_root, ["update-index", "--add", "--cacheinfo", mode, oid, path], effective)


class RepoCommitLock(FilePidLock):
    def __init__(self, repo: str):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", repo)
        super().__init__(
            state_dir() / "locks" / f"git-{safe}.lock",
            label="git commit lock",
            timeout_seconds=REPO_COMMIT_LOCK_TIMEOUT_SECONDS,
            # Live owner: fail fast. Dead PID: steal inside FilePidLock.
            allow_wait=False,
        )

def commit_task(args: argparse.Namespace) -> int:
    message = _validate_commit_message(args.message)
    task_id = resolve_task_id(getattr(args, "task_id", None))
    with RepoCommitLock(args.repo):
        data = load_checkpoint(task_id)
        payload = commit_plan_payload(data, args.repo)
        if payload["verdict"] == "NO_COMMIT":
            print_commit_plan(payload, args.json)
            return 0
        if payload["verdict"] != "COMMIT_READY":
            print_commit_plan(payload, args.json)
            return 1
        repo_root = repo_path(args.repo)
        owned_paths = payload["owned_paths"]
        try:
            states = prepare_owned_commit_states(
                args.repo,
                repo_root,
                owned_paths,
                data["ownership_baseline"],
                data["adopted_baseline_scope"],
                state_dir(),
            )
        except OwnershipError as exc:
            raise TaskError(str(exc)) from exc
        with tempfile.TemporaryDirectory(prefix="ai-os-commit-", dir=str(state_dir())) as temp_raw:
            temp = Path(temp_raw)
            index_path = temp / "index"
            env = _git_env_with_index(index_path)
            _run_git_env(repo_root, ["read-tree", "HEAD"], env)
            for path, path_states in states.items():
                _set_index_state(repo_root, path, path_states["commit"], env=env)
            tree = _run_git_env(repo_root, ["write-tree"], env).stdout.decode().strip()
            head_tree = run(["git", "rev-parse", "HEAD^{tree}"], repo_root).stdout.strip()
            if tree == head_tree:
                raise TaskError("isolated commit tree is identical to HEAD")
            message_file = temp / "message.txt"
            message_file.write_text(message + "\n", encoding="utf-8", newline="\n")
            proc = _run_git_env(repo_root, ["commit", "-F", str(message_file)], env, check=False)
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout).decode(errors="replace").strip()
                raise TaskError(f"git commit failed: {detail}")
        sha = git_head(args.repo)
        record = f"{args.repo}:{sha}"
        restore_errors: list[str] = []
        try:
            # Record SHA before index restore so a later failure still leaves an audit trail.
            data = load_checkpoint(task_id)
            if record not in data["commits"]:
                data["commits"].append(record)
            data["completed_steps"].append(
                {
                    "timestamp": utc_now(),
                    "text": f"Created scoped local commit {record} on {git_branch(args.repo)}",
                }
            )
            data["current_phase"] = "commit-created"
            data["last_summary"] = f"scoped local commit {record}"
            refresh_git_fields(data)
            atomic_write(data)
        finally:
            for path, path_states in states.items():
                try:
                    _set_index_state(repo_root, path, path_states["post_index"])
                except Exception as exc:  # noqa: BLE001 - collect residue, do not hide commit
                    restore_errors.append(f"{path}: {exc}")
        if restore_errors:
            raise TaskError(
                f"commit {record} was created but index restore left residue: "
                + "; ".join(restore_errors)
            )
        changed = {
            normalize_rel(line)
            for line in run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha], repo_root
            ).stdout.splitlines()
            if line.strip()
        }
        unexpected = sorted(changed - set(owned_paths))
        if unexpected:
            raise TaskError(
                "commit was created but contains paths outside owned scope; do not rewrite history automatically: "
                + ", ".join(unexpected)
            )
        data = load_checkpoint(task_id)
        result = {
            "verdict": "COMMITTED",
            "repo": args.repo,
            "branch": git_branch(args.repo),
            "sha": sha,
            "subject": message.splitlines()[0],
            "paths": sorted(changed),
            "publication_mode": data["publication_mode"],
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"COMMITTED: {args.repo}:{sha}")
            print(f"branch: {result['branch']}")
            print("paths: " + ", ".join(result["paths"]))
            print(f"publication: {result['publication_mode']} (no push performed)")
        return 0


def create_task_branch(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    if args.repo not in data["target_repositories"]:
        raise TaskError(f"branch repo is not in checkpoint target_repositories: {args.repo}")
    refresh_git_fields(data)
    if data["ownership_conflicts"]:
        raise TaskError("cannot change branch while ownership conflicts exist")
    if owned_paths_for_repo(data, args.repo):
        raise TaskError("create/switch the task branch before making task-owned changes")
    operation = git_operation_in_progress(args.repo)
    if operation:
        raise TaskError(f"cannot change branch during {operation}")
    current = git_branch(args.repo)
    if current == args.name:
        print(f"BRANCH: already on {current}")
        return 0
    if current and not branch_is_protected(args.repo, current):
        raise TaskError(f"already on non-protected branch {current}; refusing implicit branch switch")
    check = run(["git", "check-ref-format", "--branch", args.name], repo_path(args.repo), check=False)
    if check.returncode != 0:
        raise TaskError(f"invalid branch name: {args.name}")
    exists = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{args.name}"], repo_path(args.repo), check=False)
    if exists.returncode == 0:
        raise TaskError(f"branch already exists: {args.name}")
    with RepoCommitLock(args.repo):
        run(["git", "switch", "-c", args.name], repo_path(args.repo))
    data["decisions"].append({"timestamp": utc_now(), "text": f"Created task branch {args.repo}:{args.name}"})
    data["current_phase"] = "task-branch"
    refresh_git_fields(data)
    atomic_write(data)
    print(f"BRANCH: {args.repo}:{args.name}")
    return 0


def guard_write(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    raw = Path(args.path).expanduser()
    candidate = raw if raw.is_absolute() else (Path.cwd() / raw)
    candidate = candidate.resolve(strict=False)
    matched_repo = ""
    matched_rel = ""
    for repo in data["target_repositories"]:
        root = repo_path(repo)
        try:
            rel = candidate.relative_to(root)
        except ValueError:
            continue
        matched_repo = repo
        matched_rel = normalize_rel(str(rel))
        break
    if not matched_repo:
        raise TaskError(f"write path is outside checkpoint target repositories: {candidate}")
    if not scope_contains(data["declared_write_scope"], {"repo": matched_repo, "path": matched_rel}):
        raise TaskError(f"write path is outside declared scope: {matched_repo}:{matched_rel}")
    operation = git_operation_in_progress(matched_repo)
    if operation:
        raise TaskError(f"write blocked while git operation is in progress: {operation}")
    branch = git_branch(matched_repo)
    if branch_is_protected(matched_repo, branch):
        raise TaskError(
            f"write blocked on protected/default branch {branch or '<detached>'}; "
            f"run task-branch --repo {matched_repo} --name <task-branch>"
        )
    print(json.dumps({"ok": True, "repo": matched_repo, "path": matched_rel, "branch": branch}))
    return 0

def closure_issues(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if data["status"] != "READY_TO_CLOSE":
        issues.append(f"status must be READY_TO_CLOSE, got {data['status']}")
    if not data["declared_write_scope"]:
        issues.append("declared_write_scope is empty")
    refresh_git_fields(data)
    if data["own_staged_files"]:
        issues.append("own staged files remain: " + ", ".join(data["own_staged_files"]))
    if data["own_unstaged_files"]:
        issues.append("own unstaged files remain: " + ", ".join(data["own_unstaged_files"]))
    if data["own_untracked_files"]:
        issues.append("own untracked files remain: " + ", ".join(data["own_untracked_files"]))
    if data["ownership_conflicts"]:
        issues.extend(data["ownership_conflicts"])
    if not data["commits"]:
        issues.append("no created commits recorded")
    for commit in data["commits"]:
        repo = commit.split(":", 1)[0] if ":" in commit else data["target_repositories"][0]
        sha = commit.split(":", 1)[1] if ":" in commit else commit
        proc = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(repo_path(repo)), capture_output=True)
        if proc.returncode != 0:
            issues.append(f"declared commit does not exist: {commit}")
    if not data["gates"]:
        issues.append("no gates recorded")
    latest_by_gate: dict[str, dict[str, Any]] = {}
    for gate in data["gates"]:
        latest_by_gate[gate["gate_id"]] = gate
        command = str(gate.get("command", "")).lower()
        for marker in FORBIDDEN_COMMAND_MARKERS:
            if marker in command:
                issues.append(f"forbidden operation marker recorded in gate {gate['gate_id']}: {marker}")
    for gate_id, gate in latest_by_gate.items():
        if gate["verdict"] not in PASSING_GATE_VERDICTS:
            issues.append(f"latest gate is not PASS/DEDUPLICATED: {gate_id}={gate['verdict']}")
            continue
        current_fp = recompute_gate_fingerprint_from_entry(gate)
        if current_fp != gate.get("fingerprint"):
            issues.append(f"gate fingerprint is stale: {gate_id}")
    open_blockers = [b for b in data["blockers"] if b.get("status") not in {"RESOLVED", "DEFERRED_WITH_EVIDENCE", "ACCEPTED"}]
    if open_blockers:
        issues.append(f"open blockers remain: {len(open_blockers)}")
    if data["next_action"]:
        issues.append("next_action must be empty for full close")
    for repo, frozen in FROZEN_PATHS.items():
        if repo not in data["target_repositories"]:
            continue
        changed = run(["git", "status", "--porcelain", "--", *sorted(frozen)], repo_path(repo)).stdout.strip()
        if changed:
            issues.append(f"frozen paths changed in {repo}")
    return issues


def recompute_gate_fingerprint_from_entry(gate: dict[str, Any]) -> dict[str, Any]:
    fp = gate["fingerprint"]
    repo = gate["repo"]
    return {
        "head_sha": git_head(repo),
        "staged_diff_hash": staged_diff_hash(repo),
        "scope_hash": scope_hash(repo, fp.get("scope") or ["."]),
        "config_hash": config_hash(repo, fp.get("config_paths") or []),
        "config_paths": fp.get("config_paths") or [],
        "runtime_identity": fp.get("runtime_identity", ""),
        "scope": fp.get("scope") or ["."],
    }


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
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"CLOSURE: {payload['verdict']}")
                for issue in issues:
                    print(f"- {issue}")
            atomic_write(data, active_path)
            return 1
        if args.validate_only:
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(f"CLOSURE: {payload['verdict']}")
            return 0
        data["status"] = "CLOSED"
        data["current_phase"] = "closed"
        data["updated_at_utc"] = utc_now()
        data["last_summary"] = args.summary or "Task closed by package closure validator."
        archive_path = archive_task_path(data["task_id"])
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if archive_path.exists():
            backup = archive_path.with_name(f"{archive_path.stem}.closed-{int(time.time())}.json")
            shutil.copy2(archive_path, backup)
        atomic_write(data, archive_path)
        delete_ownership_baseline(state_dir(), data.get("ownership_baseline"))
        if active_path.exists():
            active_path.unlink()
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
        target = Path(args.summary_file) if args.summary_file else summary_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        if args.json:
            payload["summary_file"] = str(target)
            payload["archived"] = str(archive_path)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"summary_file: {target}")
            print(f"archived: {archive_path}")
    return 0


def status_task(args: argparse.Namespace) -> int:
    if getattr(args, "all", False):
        if legacy_checkpoint_path().exists():
            with RegistryLock():
                migrate_legacy_checkpoint()
        active_ids = list_active_task_ids()
        if args.json:
            print(json.dumps({"active": active_ids}, ensure_ascii=False, indent=2))
        else:
            print(f"active_tasks: {len(active_ids)}")
            for task_id in active_ids:
                print(f"- {task_id}")
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
    print_summary(data, "RESUME")
    return 0


def remove_state(args: argparse.Namespace) -> int:
    if legacy_checkpoint_path().exists():
        with RegistryLock():
            migrate_legacy_checkpoint()
    if args.task_id:
        task_id = sanitize_task_id(args.task_id)
        removed = False
        for path in (active_task_path(task_id), archive_task_path(task_id), legacy_checkpoint_path()):
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    delete_ownership_baseline(state_dir(), payload.get("ownership_baseline"))
                except (OSError, json.JSONDecodeError, TypeError):
                    pass
                if args.archive:
                    backup_dir = state_dir() / "tasks" / "cleanup-backups"
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup = backup_dir / f"{task_id}-{int(time.time())}.json"
                    shutil.copy2(path, backup)
                    print(f"archived: {backup}")
                path.unlink()
                print(f"removed: {path}")
                removed = True
        if not removed:
            print(f"no checkpoint found for task {task_id}")
        return 0
    legacy = legacy_checkpoint_path()
    if legacy.exists():
        if args.archive:
            backup = legacy.with_name(f"{legacy.stem}.closed-{int(time.time())}.json")
            shutil.copy2(legacy, backup)
            print(f"archived: {backup}")
        legacy.unlink()
        print(f"removed: {legacy}")
    return 0


def add_task_id_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task-id", help="Explicit task id (default: AI_OS_TASK_ID or single active task)")


def list_tasks_cmd(args: argparse.Namespace) -> int:
    args.all = True
    return status_task(args)


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
