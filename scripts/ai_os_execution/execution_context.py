"""Single Execution Context Compiler — sole source for mediated child environments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_os_execution.bundle import execution_dir, load_bundle
from ai_os_execution.child_env import (
    build_effective_child_env,
    load_declared_public_env,
    load_workload_secrets,
)
from ai_os_execution.generation import current_lease_generation, fencing_token
from ai_os_execution.semantic_clock import semantic_env_from_clock
from ai_os_execution.stores import inspect_env_stores
from ai_os_task_errors import TaskError
from ai_os_task_git import run

OPERATION_KINDS = frozenset(
    {
        "DISCOVERY",
        "TASK_EXEC",
        "GATE",
        "FINAL_HEAD",
        "PROOF",
        "BENCHMARK",
        "IMAGE_BUILD",
    }
)
TRUSTED_OPERATION_KINDS = frozenset(
    {"TASK_EXEC", "GATE", "FINAL_HEAD", "PROOF", "BENCHMARK", "IMAGE_BUILD"}
)
PROOF_OPERATION_KINDS = frozenset({"FINAL_HEAD", "PROOF", "BENCHMARK"})


def operation_kind_for_gate(gate_id: str, *, final_head: bool = False) -> str:
    if gate_id == "FINAL_HEAD_GATE" or final_head:
        return "FINAL_HEAD"
    return "GATE"


def is_trusted_operation(operation_kind: str) -> bool:
    return operation_kind in TRUSTED_OPERATION_KINDS


def _artifact_root(execution_id: str) -> Path:
    root = execution_dir(execution_id) / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _store_bindings(bundle: dict[str, Any], repo: str) -> list[dict[str, str]]:
    execution_id = str(bundle["execution_id"])
    declared = load_declared_public_env(execution_id)
    secrets = load_workload_secrets(execution_id)
    merged = dict(declared)
    merged.update(secrets)
    rows = inspect_env_stores(
        merged,
        execution_mode=str(bundle.get("execution_mode") or "TEST"),
        task_database=str((bundle.get("database") or {}).get("database_name") or ""),
        task_principal=str((bundle.get("database") or {}).get("principal") or ""),
        target_repositories=[repo],
    )
    return [
        {
            "store": str(row.get("store") or ""),
            "role": str(row.get("role") or ""),
            "connection_mode": str(row.get("connection_mode") or ""),
            "read_write": str(row.get("read_write") or ""),
        }
        for row in rows
    ]


def _repo_sha(worktree: Path) -> str:
    if not worktree.exists():
        return ""
    return run(["git", "rev-parse", "--verify", "HEAD"], worktree).stdout.strip()


def compile_execution_context(
    *,
    execution_id: str,
    repo: str,
    operation_kind: str,
    generation: int | None = None,
    fencing_token_value: str | None = None,
) -> dict[str, Any]:
    if operation_kind not in OPERATION_KINDS:
        raise TaskError(f"invalid operation_kind: {operation_kind}")
    bundle = load_bundle(execution_id)
    if bundle.get("status") not in {"ACTIVE", "CLOSED_RETAINED"}:
        raise TaskError(f"execution bundle not active: {bundle.get('status')}")
    active_generation = current_lease_generation(bundle)
    requested_generation = int(generation or active_generation)
    if requested_generation != active_generation:
        raise TaskError(
            f"GENERATION_LOST: requested generation {requested_generation} "
            f"!= bundle lease_generation {active_generation}"
        )
    entry = (bundle.get("repos") or {}).get(repo) or {}
    if str(entry.get("worktree_status") or "ACTIVE") != "ACTIVE":
        raise TaskError(f"repo {repo} worktree is not ACTIVE for generation {active_generation}")
    cwd = Path(str(entry.get("worktree_path") or ""))
    if not cwd.exists():
        raise TaskError(f"worktree missing for {repo}: {cwd}")

    expected_fencing = fencing_token(str(bundle["execution_id"]), active_generation)
    token = str(fencing_token_value or bundle.get("fencing_token") or expected_fencing)
    if token != expected_fencing:
        raise TaskError("fencing token mismatch for active generation")

    semantic_clock = dict(bundle.get("semantic_clock") or {})
    capabilities = dict(bundle.get("capabilities") or {})
    runtime = dict(bundle.get("runtime") or {})
    hermetic = dict(bundle.get("hermetic") or {})
    extra_declared = {
        "AI_OS_LEASE_GENERATION": str(active_generation),
        "AI_OS_FENCING_TOKEN": token,
        "AI_OS_OPERATION_KIND": operation_kind,
        "AI_OS_MEDIATED_EXECUTION": "1",
    }
    extra_declared.update(semantic_env_from_clock(semantic_clock))
    synthesized_env = build_effective_child_env(
        bundle,
        cwd=cwd,
        extra_declared=extra_declared,
        include_execution_ids=True,
    )
    public_env_keys = sorted(
        key
        for key, value in synthesized_env.items()
        if "://" not in str(value) and "PASSWORD" not in key.upper() and "SECRET" not in key.upper()
    )
    artifact_root = _artifact_root(execution_id)
    context = {
        "execution_id": execution_id,
        "task_id": str(bundle.get("task_id") or ""),
        "generation": active_generation,
        "repo": repo,
        "operation_kind": operation_kind,
        "trusted": is_trusted_operation(operation_kind),
        "cwd": str(cwd),
        "synthesized_env": synthesized_env,
        "public_env_keys": public_env_keys,
        "hermetic": hermetic,
        "store_bindings": _store_bindings(bundle, repo),
        "capabilities": capabilities,
        "semantic_clock": semantic_clock,
        "runtime_namespace": str(runtime.get("namespace") or ""),
        "fencing_token": token,
        "environment_manifest_hash": str(bundle.get("environment_manifest_hash") or ""),
        "artifact_root": str(artifact_root),
        "repo_sha": _repo_sha(cwd),
    }
    context["execution_context_hash"] = execution_context_hash(context)
    return context


def execution_context_hash(context: dict[str, Any]) -> str:
    payload = {
        "execution_id": context.get("execution_id"),
        "generation": context.get("generation"),
        "repo": context.get("repo"),
        "operation_kind": context.get("operation_kind"),
        "cwd": context.get("cwd"),
        "environment_manifest_hash": context.get("environment_manifest_hash"),
        "fencing_token": context.get("fencing_token"),
        "capabilities_matrix_key": (context.get("capabilities") or {}).get("matrix_key"),
        "semantic_clock_status": (context.get("semantic_clock") or {}).get("status"),
        "runtime_namespace": context.get("runtime_namespace"),
        "public_env_keys": context.get("public_env_keys") or [],
        "store_bindings": context.get("store_bindings") or [],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
