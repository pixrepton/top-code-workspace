"""Write leases for task-owned paths. Read is always allowed; mutation requires a lease."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai_os_execution import LEASE_TTL_SECONDS
from ai_os_execution.bundle import atomic_json
from ai_os_task_errors import TaskError
from ai_os_task_paths import state_dir, utc_now
from ai_os_task_scope import scope_entries_overlap


def leases_path() -> Path:
    return state_dir() / "write-leases.json"


def load_leases() -> list[dict[str, Any]]:
    path = leases_path()
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("leases") or [])


def save_leases(leases: list[dict[str, Any]]) -> None:
    atomic_json({"leases": leases}, leases_path())


def _parse_ts(value: str) -> datetime:
    raw = value.replace("Z", "+00:00")
    return datetime.fromisoformat(raw)


def lease_status(lease: dict[str, Any], *, now: str | None = None) -> str:
    stamp = now or utc_now()
    if lease.get("status") in {"RELEASED", "RECOVERED"}:
        return str(lease["status"])
    expires = str(lease.get("expires_at") or "")
    if not expires:
        return "ACTIVE"
    if _parse_ts(expires) <= _parse_ts(stamp):
        return "STALE_LEASE"
    return "ACTIVE"


def _as_scope(values: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw in values:
        repo, _, path = raw.partition(":")
        items.append({"repo": repo, "path": path or "."})
    return items


def _paths_overlap(left: list[str], right: list[str]) -> bool:
    left_scope = _as_scope(left)
    right_scope = _as_scope(right)
    for left_item in left_scope:
        for right_item in right_scope:
            if scope_entries_overlap(left_item, right_item):
                return True
    return False


def overlapping_active_leases(
    repo: str,
    owned_paths: list[str],
    *,
    exclude_execution_id: str = "",
    now: str | None = None,
) -> list[dict[str, Any]]:
    qualified = [path if ":" in path else f"{repo}:{path}" for path in owned_paths]
    hits: list[dict[str, Any]] = []
    for lease in load_leases():
        if exclude_execution_id and lease.get("execution_id") == exclude_execution_id:
            continue
        if lease_status(lease, now=now) != "ACTIVE":
            continue
        if _paths_overlap(qualified, list(lease.get("owned_paths") or [])):
            hits.append(lease)
    return hits


def acquire_lease(
    *,
    task_id: str,
    execution_id: str,
    repo: str,
    owned_paths: list[str],
    ttl_seconds: int = LEASE_TTL_SECONDS,
    now: str | None = None,
    takeover: bool = False,
) -> dict[str, Any]:
    stamp = now or utc_now()
    qualified = [path if ":" in path else f"{repo}:{path}" for path in owned_paths]
    conflicts = overlapping_active_leases(repo, qualified, exclude_execution_id=execution_id, now=stamp)
    if conflicts and not takeover:
        first = conflicts[0]
        raise TaskError(
            "write lease conflict with "
            f"{first.get('task_id')}:{first.get('execution_id')} on {', '.join(first.get('owned_paths') or [])}"
        )
    recovered_from = []
    leases = load_leases()
    if takeover:
        for lease in leases:
            if lease in conflicts or (
                lease_status(lease, now=stamp) == "STALE_LEASE"
                and _paths_overlap(qualified, list(lease.get("owned_paths") or []))
            ):
                lease["status"] = "RECOVERED"
                lease["recovered_at"] = stamp
                lease["recovered_by"] = execution_id
                recovered_from.append(lease.get("lease_id"))
    expires = (_parse_ts(stamp) + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
    lease_id = "lease_" + hashlib.sha256(f"{execution_id}:{repo}:{stamp}".encode()).hexdigest()[:12]
    record = {
        "lease_id": lease_id,
        "task_id": task_id,
        "execution_id": execution_id,
        "repo": repo,
        "owned_paths": qualified,
        "acquired_at": stamp,
        "expires_at": expires,
        "heartbeat_at": stamp,
        "status": "ACTIVE",
        "recovered_from": recovered_from,
    }
    leases.append(record)
    save_leases(leases)
    return record


def heartbeat_lease(execution_id: str, *, now: str | None = None, ttl_seconds: int = LEASE_TTL_SECONDS) -> int:
    stamp = now or utc_now()
    expires = (_parse_ts(stamp) + timedelta(seconds=ttl_seconds)).isoformat().replace("+00:00", "Z")
    updated = 0
    leases = load_leases()
    for lease in leases:
        if lease.get("execution_id") != execution_id:
            continue
        if lease_status(lease, now=stamp) == "RELEASED":
            continue
        lease["heartbeat_at"] = stamp
        lease["expires_at"] = expires
        lease["status"] = "ACTIVE"
        updated += 1
    save_leases(leases)
    return updated


def recover_stale_leases(*, now: str | None = None) -> list[dict[str, Any]]:
    """Mark expired leases STALE_LEASE. Does not auto-takeover."""
    stamp = now or utc_now()
    changed: list[dict[str, Any]] = []
    leases = load_leases()
    for lease in leases:
        if lease.get("status") == "ACTIVE" and lease_status(lease, now=stamp) == "STALE_LEASE":
            lease["status"] = "STALE_LEASE"
            lease["stale_marked_at"] = stamp
            changed.append(dict(lease))
    save_leases(leases)
    return changed


def release_leases(execution_id: str, *, now: str | None = None) -> int:
    stamp = now or utc_now()
    released = 0
    leases = load_leases()
    for lease in leases:
        if lease.get("execution_id") == execution_id and lease.get("status") not in {"RELEASED", "RECOVERED"}:
            lease["status"] = "RELEASED"
            lease["released_at"] = stamp
            released += 1
    save_leases(leases)
    return released


def assert_scope_leases_free(scope: list[dict[str, str]], *, exclude_execution_id: str = "") -> None:
    for item in scope:
        owned = [f"{item['repo']}:{item['path']}"]
        conflicts = overlapping_active_leases(item["repo"], owned, exclude_execution_id=exclude_execution_id)
        if conflicts:
            first = conflicts[0]
            raise TaskError(
                "write lease conflict with "
                f"{first.get('task_id')}:{first.get('execution_id')} on {item['repo']}:{item['path']}"
            )
