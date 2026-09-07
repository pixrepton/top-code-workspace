"""Whitelist public serialization for execution bundles (no secrets by construction)."""

from __future__ import annotations

import copy
from typing import Any

_PUBLIC_DATABASE_KEYS = frozenset(
    {
        "isolation_mode",
        "database_name",
        "database_host",
        "principal",
        "seed_identity",
        "seed_hash",
        "seed_origin",
        "canonical_database",
        "created_at",
        "control_plane_fingerprint",
    }
)

_PUBLIC_REPO_ENTRY_KEYS = frozenset(
    {
        "canonical_repo",
        "worktree_path",
        "base_sha",
        "current_sha",
        "branch",
        "mutation_mode",
        "lease_generation",
        "worktree_status",
    }
)


def public_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "execution_bundle_version": bundle.get("execution_bundle_version"),
        "execution_id": bundle.get("execution_id"),
        "task_id": bundle.get("task_id"),
        "campaign_id": bundle.get("campaign_id"),
        "created_at": bundle.get("created_at"),
        "status": bundle.get("status"),
        "execution_mode": bundle.get("execution_mode"),
        "seed_origin": bundle.get("seed_origin"),
        "capability_profile": bundle.get("capability_profile"),
        "scratch_path": bundle.get("scratch_path"),
        "environment_manifest_hash": bundle.get("environment_manifest_hash"),
        "commit_dependencies": copy.deepcopy(bundle.get("commit_dependencies") or []),
    }
    db = bundle.get("database") or {}
    out["database"] = {k: db[k] for k in _PUBLIC_DATABASE_KEYS if k in db}
    repos = bundle.get("repos") or {}
    out["repos"] = {
        name: {k: entry[k] for k in _PUBLIC_REPO_ENTRY_KEYS if k in entry}
        for name, entry in repos.items()
        if isinstance(entry, dict)
    }
    for section in ("runtime", "benchmark", "tooling", "ownership", "proof", "final_head", "hermetic", "capabilities"):
        if section in bundle:
            out[section] = copy.deepcopy(bundle[section])
    return out
