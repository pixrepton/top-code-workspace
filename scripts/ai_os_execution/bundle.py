"""Task Execution Bundle schema, persistence, and active-worktree resolution."""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

from ai_os_execution import (
    EXECUTION_BUNDLE_VERSION,
    EXECUTION_MODES,
    EXECUTION_PROTOCOL_VERSION,
    LIFECYCLE_STATES,
    MUTATION_MODES,
    SUPPORTED_EXECUTION_PROTOCOL_VERSIONS,
)
from ai_os_task_errors import TaskError
from ai_os_task_paths import list_active_task_ids, state_dir, utc_now


def atomic_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(tmp, path)

_EXEC_ID_RE = re.compile(r"^exec_[A-Za-z0-9]+_[A-Za-z0-9]+$")


def executions_root() -> Path:
    return state_dir() / "executions"


def execution_dir(execution_id: str) -> Path:
    return executions_root() / sanitize_execution_id(execution_id)


def bundle_path(execution_id: str) -> Path:
    return execution_dir(execution_id) / "TASK_EXECUTION_BUNDLE.json"


def index_path() -> Path:
    return executions_root() / "index.json"


def sanitize_execution_id(execution_id: str) -> str:
    value = (execution_id or "").strip()
    if not _EXEC_ID_RE.fullmatch(value):
        raise TaskError(f"invalid execution_id: {execution_id}")
    return value


def new_execution_id(now: str | None = None) -> str:
    stamp = (now or utc_now()).replace("-", "").replace(":", "")
    return f"exec_{stamp}_{secrets.token_hex(3)}"


def docker_namespace(execution_id: str) -> str:
    compact = sanitize_execution_id(execution_id).lower().replace("_", "")
    return f"aios{compact[-20:]}"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TaskError(f"execution bundle missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise TaskError(f"execution bundle corrupt: {path}: {exc}") from exc


def load_index() -> dict[str, str]:
    path = index_path()
    if not path.exists():
        return {}
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _write_index(mapping: dict[str, str]) -> None:
    atomic_json(mapping, index_path())


def save_bundle(bundle: dict[str, Any]) -> Path:
    validate_bundle(bundle)
    path = bundle_path(bundle["execution_id"])
    atomic_json(bundle, path)
    mapping = load_index()
    mapping[bundle["task_id"]] = bundle["execution_id"]
    _write_index(mapping)
    return path


def load_bundle(execution_id: str) -> dict[str, Any]:
    bundle = _read_json(bundle_path(execution_id))
    validate_bundle(bundle)
    return bundle


def load_bundle_for_task(task_id: str) -> dict[str, Any] | None:
    execution_id = load_index().get(task_id)
    if not execution_id:
        return None
    path = bundle_path(execution_id)
    if not path.exists():
        return None
    return load_bundle(execution_id)


def load_active_bundle() -> dict[str, Any] | None:
    explicit = os.environ.get("AI_OS_EXECUTION_ID", "").strip()
    if explicit:
        return load_bundle(explicit)
    task_id = os.environ.get("AI_OS_TASK_ID", "").strip()
    if task_id:
        return load_bundle_for_task(task_id)
    active = list_active_task_ids()
    if len(active) != 1:
        return None
    return load_bundle_for_task(active[0])


def configured_worktree_path(repo: str) -> Path | None:
    override = os.environ.get("AI_OS_REPO_PATH", "").strip()
    repo_override = os.environ.get(f"AI_OS_REPO_PATH_{repo.replace('-', '_').upper()}", "").strip()
    chosen = repo_override or override
    if chosen:
        return Path(chosen)
    bundle = load_active_bundle()
    if not bundle:
        return None
    entry = bundle.get("repos", {}).get(repo) or {}
    worktree = str(entry.get("worktree_path") or "").strip()
    if not worktree:
        return None
    return Path(worktree)


def validate_bundle(bundle: dict[str, Any]) -> None:
    if not isinstance(bundle, dict):
        raise TaskError("execution bundle must be an object")
    if int(bundle.get("execution_bundle_version") or 0) != EXECUTION_BUNDLE_VERSION:
        raise TaskError("unsupported execution_bundle_version")
    protocol = str(bundle.get("execution_protocol_version") or "").strip()
    if protocol and protocol not in SUPPORTED_EXECUTION_PROTOCOL_VERSIONS:
        raise TaskError(f"unsupported execution_protocol_version: {protocol}")
    for key in ("execution_id", "task_id", "created_at", "status", "repos"):
        if key not in bundle:
            raise TaskError(f"execution bundle missing {key}")
    sanitize_execution_id(str(bundle["execution_id"]))
    if bundle.get("status") not in LIFECYCLE_STATES:
        raise TaskError(f"invalid execution status: {bundle.get('status')}")
    mode = str(bundle.get("execution_mode") or "MUTATE")
    if mode not in EXECUTION_MODES:
        raise TaskError(f"invalid execution_mode: {mode}")
    workspace_mode = str(bundle.get("workspace_mode") or "").strip()
    if workspace_mode and workspace_mode not in {"DIRECT_CANONICAL", "ISOLATED_WORKTREE"}:
        raise TaskError(f"invalid workspace_mode: {workspace_mode}")
    repos = bundle.get("repos")
    if not isinstance(repos, dict) or not repos:
        raise TaskError("execution bundle requires repos")
    for name, entry in repos.items():
        if not isinstance(entry, dict):
            raise TaskError(f"repo entry invalid: {name}")
        mutation = entry.get("mutation_mode") or "MUTATE"
        if mutation not in MUTATION_MODES:
            raise TaskError(f"invalid mutation_mode for {name}: {mutation}")


def empty_repo_entry(
    *,
    canonical_repo: str,
    worktree_path: str,
    base_sha: str,
    current_sha: str,
    branch: str,
    mutation_mode: str,
    lease_generation: int = 1,
    worktree_status: str = "ACTIVE",
) -> dict[str, Any]:
    return {
        "canonical_repo": canonical_repo,
        "worktree_path": worktree_path,
        "base_sha": base_sha,
        "current_sha": current_sha,
        "branch": branch,
        "mutation_mode": mutation_mode,
        "lease_generation": lease_generation,
        "worktree_status": worktree_status,
    }


def new_bundle(
    *,
    execution_id: str,
    task_id: str,
    campaign_id: str,
    repos: dict[str, dict[str, Any]],
    execution_mode: str = "TEST",
    now: str | None = None,
) -> dict[str, Any]:
    stamp = now or utc_now()
    return {
        "execution_bundle_version": EXECUTION_BUNDLE_VERSION,
        "execution_protocol_version": EXECUTION_PROTOCOL_VERSION,
        "execution_id": execution_id,
        "task_id": task_id,
        "campaign_id": campaign_id,
        "created_at": stamp,
        "status": "ACTIVE",
        "execution_mode": execution_mode,
        "repos": repos,
        "scratch_path": "",
        "runtime": {
            "namespace": docker_namespace(execution_id),
            "compose_project": docker_namespace(execution_id),
            "profile": "host",
            "image_digests": {},
        },
        "database": {
            "isolation_mode": "NONE",
            "database_name": "",
            "database_host": {"host": "", "container": ""},
            "principal": "",
            "seed_identity": "",
            "seed_hash": "",
            "seed_origin": "EMPTY",
        },
        "benchmark": {
            "manifest_hash": "",
            "scorer_hash": "",
            "cohort_hash": "",
        },
        "tooling": {
            "preflight_manifest": "",
            "graph_freshness": {},
        },
        "ownership": {
            "lease_id": "",
            "owned_paths": [],
            "expires_at": "",
            "lease_generation": 1,
            "fencing_token": "",
        },
        "proof": {
            "latest_proof_bundle": "",
        },
        "commit_dependencies": [],
        "final_head": {
            "required": True,
            "valid": False,
            "gate_id": "FINAL_HEAD_GATE",
            "invalidated_reason": "",
        },
        "environment_manifest_hash": "",
        "lease_generation": 1,
        "fencing_token": "",
        "worktree_history": [],
    }
