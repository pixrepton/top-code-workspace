"""Task-start ownership baseline: capture, storage and read-back."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_os_task_errors import OwnershipError
from ai_os_task_ownership_git import (
    MISSING_STATE,
    RAW_STATE_CATEGORIES,
    OwnershipContext,
    State,
    canonical_worktree_bytes,
    collect_raw_git_state,
    git_object_exists,
    is_adopted,
    read_git_object,
    scoped_repos,
)
from ai_os_task_scope import ScopeEntry


OWNERSHIP_BASELINE_VERSION = 1
SNAPSHOT_DIRECTORY_PREFIX = "ownership-baseline-"
DESCRIPTOR_SLOTS = ("head", "index", "worktree")


def require_baseline_version(baseline: dict[str, Any]) -> None:
    if baseline.get("version") != OWNERSHIP_BASELINE_VERSION:
        raise OwnershipError(f"unsupported ownership baseline version: {baseline.get('version')}")


def create_baseline_storage(state_root: Path) -> Path:
    state_root.mkdir(parents=True, exist_ok=True)
    target = state_root / f"{SNAPSHOT_DIRECTORY_PREFIX}{time.time_ns()}-{os.getpid()}"
    target.mkdir()
    return target


def missing_descriptor() -> dict[str, Any]:
    return {"kind": "missing", "sha256": "", "size": 0, "snapshot": ""}


def _unsupported_descriptor() -> dict[str, Any]:
    return {"kind": "unsupported", "sha256": "", "size": 0, "snapshot": ""}


def write_snapshot(storage: Path, data: bytes) -> dict[str, Any]:
    digest = hashlib.sha256(data).hexdigest()
    target = storage / f"{digest}.bin"
    if not target.exists():
        tmp = storage / f".{digest}.{os.getpid()}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, target)
    return {
        "kind": "file",
        "sha256": digest,
        "size": len(data),
        "snapshot": target.name,
    }


def descriptor_from_git(repo_root: Path, revision: str, path: str, storage: Path) -> dict[str, Any]:
    spec = f"{revision}:{path}"
    if not git_object_exists(repo_root, spec):
        return missing_descriptor()
    return write_snapshot(storage, read_git_object(repo_root, spec))


def descriptor_from_worktree(repo_root: Path, path: str, storage: Path) -> dict[str, Any]:
    full = repo_root / path
    if not os.path.lexists(full):
        return missing_descriptor()
    if full.is_symlink():
        link = os.readlink(full).encode("utf-8", errors="surrogateescape")
        descriptor = write_snapshot(storage, link)
        descriptor["kind"] = "symlink"
        return descriptor
    if not full.is_file():
        return _unsupported_descriptor()
    return write_snapshot(storage, canonical_worktree_bytes(full.read_bytes()))


@dataclass(frozen=True)
class SnapshotStore:
    """Reads baseline states back out of one checkpoint's snapshot directory."""

    state_root: Path
    snapshot_directory: str

    def state(self, descriptor: dict[str, Any]) -> State:
        kind = descriptor.get("kind", "unsupported")
        if kind == "missing":
            return MISSING_STATE
        if kind not in {"file", "symlink"}:
            return (kind, None)
        return (kind, self._verified_bytes(descriptor))

    def _verified_bytes(self, descriptor: dict[str, Any]) -> bytes:
        target = self.state_root / self.snapshot_directory / descriptor["snapshot"]
        if not target.is_file():
            raise OwnershipError(f"ownership baseline snapshot is missing: {target}")
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != descriptor.get("sha256"):
            raise OwnershipError(f"ownership baseline snapshot hash mismatch: {target}")
        return data


def snapshot_store(state_root: Path, baseline: dict[str, Any]) -> SnapshotStore:
    return SnapshotStore(state_root, baseline.get("snapshot_directory", ""))


@dataclass(frozen=True)
class _RepoBaselineSpec:
    repo: str
    repo_root: Path
    scopes: list[str]
    revision: str
    adopted: list[ScopeEntry]
    storage: Path


def _baseline_statuses(raw: dict[str, set[str]], path: str) -> list[str]:
    return [name for name in RAW_STATE_CATEGORIES if path in raw[name]]


def _descriptor_triple(spec: _RepoBaselineSpec, path: str) -> dict[str, Any]:
    return {
        "head": descriptor_from_git(spec.repo_root, spec.revision, path, spec.storage),
        "index": descriptor_from_git(spec.repo_root, "", path, spec.storage),
        "worktree": descriptor_from_worktree(spec.repo_root, path, spec.storage),
    }


def _descriptor_bytes(triple: dict[str, Any]) -> int:
    return sum(int(triple[slot].get("size", 0)) for slot in DESCRIPTOR_SLOTS)


def _baseline_entry(spec: _RepoBaselineSpec, path: str, statuses: list[str]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "repo": spec.repo,
        "path": path,
        "baseline_status": statuses,
        "adopted": is_adopted(spec.repo, path, spec.adopted),
    }
    if not entry["adopted"]:
        entry.update(_descriptor_triple(spec, path))
    return entry


def _repo_baseline_entries(spec: _RepoBaselineSpec) -> tuple[list[dict[str, Any]], int]:
    raw = collect_raw_git_state(spec.repo_root, spec.scopes)
    paths = sorted(raw["staged"] | raw["unstaged"] | raw["untracked"])
    entries: list[dict[str, Any]] = []
    snapshot_bytes = 0
    for path in paths:
        entry = _baseline_entry(spec, path, _baseline_statuses(raw, path))
        if not entry["adopted"]:
            snapshot_bytes += _descriptor_bytes(entry)
        entries.append(entry)
    return entries, snapshot_bytes


def _repo_specs(
    context: OwnershipContext,
    baseline_shas: dict[str, str],
    storage: Path,
) -> list[_RepoBaselineSpec]:
    return [
        _RepoBaselineSpec(
            repo=repo,
            repo_root=repo_root,
            scopes=scopes,
            revision=baseline_shas[repo],
            adopted=context.adopted,
            storage=storage,
        )
        for repo, repo_root, scopes in scoped_repos(context)
    ]


def _collect_baseline_entries(
    context: OwnershipContext,
    baseline_shas: dict[str, str],
    storage: Path,
) -> tuple[list[dict[str, Any]], int]:
    entries: list[dict[str, Any]] = []
    snapshot_bytes = 0
    for spec in _repo_specs(context, baseline_shas, storage):
        repo_entries, repo_bytes = _repo_baseline_entries(spec)
        entries.extend(repo_entries)
        snapshot_bytes += repo_bytes
    return entries, snapshot_bytes


def capture_ownership_baseline(
    context: OwnershipContext,
    baseline_shas: dict[str, str],
    captured_at_utc: str,
) -> dict[str, Any]:
    """Snapshot every pre-existing dirty path inside the declared scope."""
    storage = create_baseline_storage(context.state_root)
    try:
        entries, snapshot_bytes = _collect_baseline_entries(context, baseline_shas, storage)
    except Exception:
        shutil.rmtree(storage, ignore_errors=True)
        raise
    return {
        "version": OWNERSHIP_BASELINE_VERSION,
        "captured_at_utc": captured_at_utc,
        "snapshot_directory": storage.name,
        "snapshot_bytes": snapshot_bytes,
        "entries": entries,
    }


def empty_ownership_baseline(captured_at_utc: str) -> dict[str, Any]:
    return {
        "version": OWNERSHIP_BASELINE_VERSION,
        "captured_at_utc": captured_at_utc,
        "snapshot_directory": "",
        "snapshot_bytes": 0,
        "entries": [],
    }


def _is_unsafe_snapshot_name(name: str) -> bool:
    if not name:
        return True
    if name in {".", ".."}:
        return True
    return any(separator in name for separator in ("/", "\\"))


def delete_ownership_baseline(state_root: Path, baseline: dict[str, Any] | None) -> None:
    """Remove ownership snapshot directory referenced by a checkpoint baseline."""
    if not baseline:
        return
    name = str(baseline.get("snapshot_directory") or "").strip()
    if _is_unsafe_snapshot_name(name):
        return
    target = state_root / name
    if not target.is_dir():
        return
    if target.name.startswith(SNAPSHOT_DIRECTORY_PREFIX):
        shutil.rmtree(target, ignore_errors=True)
