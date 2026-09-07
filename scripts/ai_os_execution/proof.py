"""Proof Bundle + Gate Fingerprint V2 + image provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_os_execution import PROOF_BUNDLE_VERSION
from ai_os_execution.bundle import atomic_json, execution_dir, load_active_bundle, load_bundle_for_task
from ai_os_task_errors import TaskError
from ai_os_task_git import git_head, scope_hash, staged_diff_hash
from ai_os_task_paths import utc_now
from ai_os_task_scope import normalize_rel


def owned_tree_hash(repo: str, rel_paths: list[str]) -> str:
    return scope_hash(repo, rel_paths or ["."])


def repo_sha_set(repos: list[str]) -> dict[str, str]:
    return {name: git_head(name) for name in repos}


def build_fingerprint_v2(
    *,
    task_id: str,
    repo: str,
    command: list[str],
    rel_paths: list[str],
    config_hash_value: str,
    config_paths: list[str],
    runtime_identity: str,
    staged: str,
    execution_id: str = "",
    environment_manifest_hash: str = "",
    image_digest: str = "",
    db_seed_identity: str = "",
    db_seed_hash: str = "",
    benchmark_manifest_hash: str = "",
    scorer_hash: str = "",
    gate_class: str = "DEVELOPMENT",
    target_repositories: list[str] | None = None,
) -> dict[str, Any]:
    repos = list(target_repositories or [repo])
    sha_set = repo_sha_set(repos)
    return {
        "fingerprint_version": 2,
        "task_id": task_id,
        "execution_id": execution_id,
        "gate_class": gate_class,
        "gate_command": " ".join(command),
        "head_sha": sha_set.get(repo, ""),
        "repo_sha_set": sha_set,
        "staged_diff_hash": staged,
        "scope_hash": owned_tree_hash(repo, rel_paths),
        "owned_tree_hash": owned_tree_hash(repo, rel_paths),
        "config_hash": config_hash_value,
        "config_paths": [normalize_rel(path) for path in config_paths],
        "runtime_identity": runtime_identity,
        "scope": [normalize_rel(path) for path in rel_paths],
        "environment_manifest_hash": environment_manifest_hash,
        "image_digest": image_digest,
        "db_seed_identity": db_seed_identity,
        "db_seed_hash": db_seed_hash,
        "benchmark_manifest_hash": benchmark_manifest_hash,
        "scorer_hash": scorer_hash,
    }


def fingerprint_v1(
    *,
    head_sha: str,
    staged: str,
    scope_hash_value: str,
    config_hash_value: str,
    config_paths: list[str],
    runtime_identity: str,
    rel_paths: list[str],
) -> dict[str, Any]:
    return {
        "head_sha": head_sha,
        "staged_diff_hash": staged,
        "scope_hash": scope_hash_value,
        "config_hash": config_hash_value,
        "config_paths": [normalize_rel(path) for path in config_paths],
        "runtime_identity": runtime_identity,
        "scope": [normalize_rel(path) for path in rel_paths],
    }


def image_record(*, repo: str, source_sha: str, digest: str, worktree_path: str) -> dict[str, Any]:
    return {
        "repo": repo,
        "source_sha": source_sha,
        "digest": digest,
        "worktree_path": worktree_path,
        "recorded_at": utc_now(),
    }


def validate_image_provenance(bundle: dict[str, Any], repo: str, digest: str) -> None:
    recorded = (bundle.get("runtime") or {}).get("image_digests") or {}
    entry = recorded.get(repo) or {}
    if isinstance(entry, str):
        entry = {"digest": entry}
    current_sha = ((bundle.get("repos") or {}).get(repo) or {}).get("current_sha") or ""
    source_sha = str(entry.get("source_sha") or "")
    stored_digest = str(entry.get("digest") or "")
    if not stored_digest:
        raise TaskError(f"no image digest recorded for {repo}")
    if digest and digest != stored_digest:
        raise TaskError(f"image digest mismatch for {repo}")
    if source_sha and current_sha and source_sha != current_sha:
        raise TaskError(
            f"image source SHA {source_sha} does not match bundle SHA {current_sha}; "
            "runtime proof rejected"
        )


def write_proof_bundle(
    *,
    task_id: str,
    execution_id: str,
    repos: dict[str, str],
    gate: dict[str, Any],
    verdict: str,
    source_tree_hashes: dict[str, str] | None = None,
    runtime: dict[str, Any] | None = None,
    database: dict[str, Any] | None = None,
    benchmark: dict[str, Any] | None = None,
    environment_manifest_hash: str = "",
    artifacts: dict[str, str] | None = None,
) -> Path:
    root = execution_dir(execution_id)
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "proof_bundle_version": PROOF_BUNDLE_VERSION,
        "task_id": task_id,
        "execution_id": execution_id,
        "timestamp": utc_now(),
        "repos": repos,
        "source_tree_hashes": source_tree_hashes or {},
        "gate": {
            "command": gate.get("command"),
            "exit_code": gate.get("exit_code"),
            "results": gate.get("short_result") or gate.get("verdict"),
            "gate_id": gate.get("gate_id"),
            "fingerprint": gate.get("fingerprint"),
        },
        "runtime": runtime or {},
        "database": database or {},
        "benchmark": benchmark or {},
        "environment_manifest_hash": environment_manifest_hash,
        "artifacts": artifacts or {},
        "verdict": verdict,
    }
    path = root / "PROOF_BUNDLE.json"
    atomic_json(payload, path)
    return path


def load_latest_proof(execution_id: str) -> dict[str, Any] | None:
    path = execution_dir(execution_id) / "PROOF_BUNDLE.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
