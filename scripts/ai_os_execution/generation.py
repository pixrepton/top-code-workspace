"""Lease generation + fencing for generation-isolated worktrees."""

from __future__ import annotations

import hashlib
from typing import Any

from ai_os_task_paths import utc_now


def fencing_token(execution_id: str, lease_generation: int) -> str:
    return hashlib.sha256(f"{execution_id}:{lease_generation}".encode()).hexdigest()[:16]


def current_lease_generation(bundle: dict[str, Any]) -> int:
    return int(bundle.get("lease_generation") or 1)


def bump_lease_generation(bundle: dict[str, Any]) -> int:
    generation = current_lease_generation(bundle) + 1
    bundle["lease_generation"] = generation
    bundle["fencing_token"] = fencing_token(str(bundle["execution_id"]), generation)
    ownership = bundle.setdefault("ownership", {})
    ownership["lease_generation"] = generation
    ownership["fencing_token"] = bundle["fencing_token"]
    return generation


def mark_repo_revoked(entry: dict[str, Any], *, generation: int, now: str | None = None) -> dict[str, Any]:
    stamp = now or utc_now()
    revoked = dict(entry)
    revoked["worktree_status"] = "REVOKED"
    revoked["lease_generation"] = generation
    revoked["revoked_at"] = stamp
    return revoked


def active_repo_entries(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    repos = bundle.get("repos") or {}
    active: dict[str, dict[str, Any]] = {}
    for name, entry in repos.items():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("worktree_status") or "ACTIVE") == "ACTIVE":
            active[name] = entry
    return active


def append_worktree_history(bundle: dict[str, Any], repo: str, entry: dict[str, Any]) -> None:
    history = bundle.setdefault("worktree_history", [])
    history.append(
        {
            "repo": repo,
            "generation": entry.get("lease_generation"),
            "worktree_path": entry.get("worktree_path"),
            "worktree_status": entry.get("worktree_status"),
            "current_sha": entry.get("current_sha"),
            "revoked_at": entry.get("revoked_at", ""),
        }
    )
