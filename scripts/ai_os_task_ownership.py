"""Baseline-aware ownership support for the AI-OS task checkpoint."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


OWNERSHIP_BASELINE_VERSION = 1

STATE_CATEGORIES = ("staged", "unstaged", "untracked")

DESCRIPTOR_SLOTS = ("head", "index", "worktree")

SUPPORTED_STATE_KINDS = {"file", "symlink", "missing"}


class OwnershipError(RuntimeError):
    pass


State = tuple[str, bytes | None]


def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def qualified(repo: str, path: str) -> str:
    return f"{repo}:{normalize_rel(path)}"


def path_matches(path: str, rule: str) -> bool:
    path = normalize_rel(path)
    rule = normalize_rel(rule)
    if rule in {"", "."}:
        return True
    return path == rule or path.startswith(rule + "/")


def scope_contains(scope: list[dict[str, str]], candidate: dict[str, str]) -> bool:
    return any(
        item["repo"] == candidate["repo"] and path_matches(candidate["path"], item["path"])
        for item in scope
    )


def is_adopted(repo: str, path: str, adopted: list[dict[str, str]]) -> bool:
    return any(item["repo"] == repo and path_matches(path, item["path"]) for item in adopted)


def _run_bytes(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True)
    if check and proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise OwnershipError(f"command failed ({proc.returncode}): {' '.join(args)}\n{detail}")
    return proc


def _git_names(repo_path: Path, args: list[str], scopes: list[str]) -> set[str]:
    proc = _run_bytes(["git", *args, "-z", "--", *scopes], repo_path)
    return {
        normalize_rel(raw.decode("utf-8", errors="surrogateescape"))
        for raw in proc.stdout.split(b"\0")
        if raw
    }


def collect_raw_git_state(repo_path: Path, scopes: list[str]) -> dict[str, set[str]]:
    return {
        "staged": _git_names(repo_path, ["diff", "--cached", "--name-only"], scopes),
        "unstaged": _git_names(repo_path, ["diff", "--name-only"], scopes),
        "untracked": _git_names(repo_path, ["ls-files", "--others", "--exclude-standard"], scopes),
    }


def _scopes_for_repo(scope: list[dict[str, str]], repo: str) -> list[str]:
    return [item["path"] for item in scope if item["repo"] == repo]


def create_baseline_storage(state_root: Path) -> Path:
    state_root.mkdir(parents=True, exist_ok=True)
    target = state_root / f"ownership-baseline-{time.time_ns()}-{os.getpid()}"
    target.mkdir()
    return target


def _write_snapshot(storage: Path, data: bytes) -> dict[str, Any]:
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


def _missing_descriptor() -> dict[str, Any]:
    return {"kind": "missing", "sha256": "", "size": 0, "snapshot": ""}


def _canonical_worktree_bytes(data: bytes) -> bytes:
    # Compare text in Git's LF form; raw CRLF would make every Windows line look changed.
    return data if b"\0" in data else data.replace(b"\r\n", b"\n")


def _descriptor_from_git(repo_path: Path, revision: str, path: str, storage: Path) -> dict[str, Any]:
    spec = f"{revision}:{path}"
    exists = _run_bytes(["git", "cat-file", "-e", spec], repo_path, check=False)
    if exists.returncode != 0:
        return _missing_descriptor()
    return _write_snapshot(storage, _run_bytes(["git", "show", spec], repo_path).stdout)


def _descriptor_from_worktree(repo_path: Path, path: str, storage: Path) -> dict[str, Any]:
    full = repo_path / path
    if not os.path.lexists(full):
        return _missing_descriptor()
    if full.is_symlink():
        descriptor = _write_snapshot(storage, os.readlink(full).encode("utf-8", errors="surrogateescape"))
        descriptor["kind"] = "symlink"
        return descriptor
    if not full.is_file():
        return {"kind": "unsupported", "sha256": "", "size": 0, "snapshot": ""}
    return _write_snapshot(storage, _canonical_worktree_bytes(full.read_bytes()))


@dataclass(frozen=True)
class _CaptureContext:
    repo_paths: dict[str, Path]
    scope: list[dict[str, str]]
    baseline_shas: dict[str, str]
    adopted: list[dict[str, str]]
    storage: Path


def _entry_status(path: str, raw: dict[str, set[str]]) -> list[str]:
    return [name for name in STATE_CATEGORIES if path in raw[name]]


def _entry_snapshot_bytes(entry: dict[str, Any]) -> int:
    return sum(int(entry.get(slot, {}).get("size", 0)) for slot in DESCRIPTOR_SLOTS)


def _baseline_entry(repo: str, path: str, status: list[str], ctx: _CaptureContext) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "repo": repo,
        "path": path,
        "baseline_status": status,
        "adopted": is_adopted(repo, path, ctx.adopted),
    }
    if entry["adopted"]:
        return entry
    repo_root = ctx.repo_paths[repo]
    entry["head"] = _descriptor_from_git(repo_root, ctx.baseline_shas[repo], path, ctx.storage)
    entry["index"] = _descriptor_from_git(repo_root, "", path, ctx.storage)
    entry["worktree"] = _descriptor_from_worktree(repo_root, path, ctx.storage)
    return entry


def _repo_baseline_entries(repo: str, ctx: _CaptureContext) -> list[dict[str, Any]]:
    repo_scopes = _scopes_for_repo(ctx.scope, repo)
    if not repo_scopes:
        return []
    raw = collect_raw_git_state(ctx.repo_paths[repo], repo_scopes)
    paths = sorted(raw["staged"] | raw["unstaged"] | raw["untracked"])
    return [_baseline_entry(repo, path, _entry_status(path, raw), ctx) for path in paths]


def capture_ownership_baseline(
    repo_paths: dict[str, Path],
    scope: list[dict[str, str]],
    baseline_shas: dict[str, str],
    adopted: list[dict[str, str]],
    state_root: Path,
    captured_at_utc: str,
) -> dict[str, Any]:
    storage = create_baseline_storage(state_root)
    ctx = _CaptureContext(repo_paths, scope, baseline_shas, adopted, storage)
    try:
        entries = [entry for repo in repo_paths for entry in _repo_baseline_entries(repo, ctx)]
    except Exception:
        shutil.rmtree(storage, ignore_errors=True)
        raise
    return {
        "version": OWNERSHIP_BASELINE_VERSION,
        "captured_at_utc": captured_at_utc,
        "snapshot_directory": storage.name,
        "snapshot_bytes": sum(_entry_snapshot_bytes(entry) for entry in entries),
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


def _is_safe_snapshot_name(name: str) -> bool:
    if name in {"", ".", ".."}:
        return False
    return "/" not in name and "\\" not in name


def _is_baseline_snapshot_dir(target: Path) -> bool:
    return target.is_dir() and target.name.startswith("ownership-baseline-")


def delete_ownership_baseline(state_root: Path, baseline: dict[str, Any] | None) -> None:
    """Remove ownership snapshot directory referenced by a checkpoint baseline."""
    if not baseline:
        return
    name = str(baseline.get("snapshot_directory") or "").strip()
    if not _is_safe_snapshot_name(name):
        return
    target = state_root / name
    if _is_baseline_snapshot_dir(target):
        shutil.rmtree(target, ignore_errors=True)


def _require_supported_baseline(baseline: dict[str, Any]) -> None:
    if baseline.get("version") != OWNERSHIP_BASELINE_VERSION:
        raise OwnershipError(f"unsupported ownership baseline version: {baseline.get('version')}")


def _verified_snapshot_bytes(target: Path, descriptor: dict[str, Any]) -> bytes:
    if not target.is_file():
        raise OwnershipError(f"ownership baseline snapshot is missing: {target}")
    data = target.read_bytes()
    if hashlib.sha256(data).hexdigest() != descriptor.get("sha256"):
        raise OwnershipError(f"ownership baseline snapshot hash mismatch: {target}")
    return data


def _state_from_descriptor(descriptor: dict[str, Any], state_root: Path, snapshot_directory: str) -> State:
    kind = descriptor.get("kind", "unsupported")
    if kind == "missing":
        return ("missing", None)
    if kind not in {"file", "symlink"}:
        return (kind, None)
    target = state_root / snapshot_directory / descriptor["snapshot"]
    return (kind, _verified_snapshot_bytes(target, descriptor))


def _state_from_git(repo_path: Path, revision: str, path: str) -> State:
    spec = f"{revision}:{path}"
    exists = _run_bytes(["git", "cat-file", "-e", spec], repo_path, check=False)
    if exists.returncode != 0:
        return ("missing", None)
    return ("file", _run_bytes(["git", "show", spec], repo_path).stdout)


def _state_from_worktree(repo_path: Path, path: str) -> State:
    full = repo_path / path
    if not os.path.lexists(full):
        return ("missing", None)
    if full.is_symlink():
        return ("symlink", os.readlink(full).encode("utf-8", errors="surrogateescape"))
    if not full.is_file():
        return ("unsupported", None)
    return ("file", _canonical_worktree_bytes(full.read_bytes()))


def _canonical_state(state: State) -> State:
    kind, data = state
    if data is None:
        return state
    if kind != "file":
        return state
    return (kind, _canonical_worktree_bytes(data))


def _git_merge_file(mine: State, ancestor: State, other: State, prefix: str) -> subprocess.CompletedProcess[bytes]:
    # Git for Windows can fail to open merge inputs when a pytest/state path nears MAX_PATH.
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp_raw:
        tmp = Path(tmp_raw)
        inputs = []
        for name, state in (("mine", mine), ("ancestor", ancestor), ("other", other)):
            target = tmp / name
            target.write_bytes(state[1] or b"")
            inputs.append(str(target))
        return subprocess.run(["git", "merge-file", "-p", *inputs], capture_output=True)


def _all_mergeable_files(states: tuple[State, ...]) -> bool:
    return all(state[0] == "file" for state in states)


def _any_binary(states: tuple[State, ...]) -> bool:
    return any(b"\0" in (state[1] or b"") for state in states)


def _merge_blocker(states: tuple[State, ...]) -> str:
    if not _all_mergeable_files(states):
        return "non-file baseline delta cannot be merged safely"
    if _any_binary(states):
        return "binary baseline delta overlaps a task change"
    return ""


def _merge_with_missing_base(current: State, foreign: State) -> tuple[State | None, str]:
    if foreign[0] == "missing":
        return current, ""
    if current[0] == "missing":
        return foreign, ""
    return None, "task committed or staged a path that was foreign and untracked at task start"


def _merge_after_foreign_deletion(current: State, base: State, foreign: State) -> tuple[State | None, str]:
    if current == base:
        return foreign, ""
    return None, "task overlapped or committed a pre-existing foreign deletion"


def _merge_after_task_deletion(current: State, base: State, foreign: State) -> tuple[State | None, str]:
    if foreign == base:
        return current, ""
    return None, "task deleted a path carrying a pre-existing foreign delta"


def _three_way_merge(current: State, base: State, foreign: State) -> tuple[State | None, str]:
    blocker = _merge_blocker((current, base, foreign))
    if blocker:
        return None, blocker
    proc = _git_merge_file(current, base, foreign, "ai-os-ownership-")
    if proc.returncode == 0:
        if proc.stdout == (current[1] or b""):
            return None, "task state absorbed a pre-existing foreign delta"
        return ("file", proc.stdout), ""
    if proc.returncode == 1:
        return None, "task change overlaps a pre-existing foreign hunk"
    detail = proc.stderr.decode(errors="replace").strip()
    return None, f"three-way ownership merge failed: {detail or proc.returncode}"


def _merge_expected(current: State, base: State, foreign: State) -> tuple[State | None, str]:
    """Reconstruct the state expected when the task delta and the foreign delta both apply."""
    if base[0] == "missing":
        return _merge_with_missing_base(current, foreign)
    if foreign[0] == "missing":
        return _merge_after_foreign_deletion(current, base, foreign)
    if current[0] == "missing":
        return _merge_after_task_deletion(current, base, foreign)
    if foreign == base:
        return current, ""
    if current == base:
        return foreign, ""
    if current == foreign:
        return None, "task state absorbed a pre-existing foreign delta"
    return _three_way_merge(current, base, foreign)


def _subtract_blocker(states: tuple[State, ...]) -> str:
    if not _all_mergeable_files(states):
        return "non-file baseline delta cannot be subtracted safely"
    if _any_binary(states):
        return "binary baseline delta cannot be subtracted safely"
    return ""


def _three_way_subtraction(combined: State, base: State, foreign: State) -> tuple[State | None, str]:
    blocker = _subtract_blocker((combined, base, foreign))
    if blocker:
        return None, blocker
    proc = _git_merge_file(combined, foreign, base, "ai-os-ownership-subtract-")
    if proc.returncode == 0:
        return ("file", proc.stdout), ""
    if proc.returncode == 1:
        return None, "task change overlaps a pre-existing foreign hunk"
    detail = proc.stderr.decode(errors="replace").strip()
    return None, f"three-way ownership subtraction failed: {detail or proc.returncode}"


def _remove_foreign_delta(combined: State, base: State, foreign: State) -> tuple[State | None, str]:
    """Derive task-only state by removing the task-start foreign delta from combined state."""
    if foreign == base:
        return combined, ""
    if base[0] == "missing":
        return None, "cannot isolate task changes from a file that was foreign and untracked at task start"
    if foreign[0] == "missing":
        return None, "cannot isolate task changes across a pre-existing foreign deletion"
    if combined[0] == "missing":
        return None, "cannot preserve a pre-existing foreign delta when the task deletes the path"
    if combined == foreign:
        return base, ""
    return _three_way_subtraction(combined, base, foreign)


def _collect_own_state(repo_paths: dict[str, Path], scope: list[dict[str, str]]) -> dict[str, set[str]]:
    own: dict[str, set[str]] = {category: set() for category in STATE_CATEGORIES}
    for repo, repo_root in repo_paths.items():
        repo_scopes = _scopes_for_repo(scope, repo)
        if repo_scopes:
            _add_repo_state(own, repo, collect_raw_git_state(repo_root, repo_scopes))
    return own


def _add_repo_state(own: dict[str, set[str]], repo: str, raw: dict[str, set[str]]) -> None:
    for category in STATE_CATEGORIES:
        own[category].update(qualified(repo, path) for path in raw[category])


def _discard_keys(own: dict[str, set[str]], keys: set[str]) -> None:
    for category in STATE_CATEGORIES:
        own[category] -= keys


def _entry_is_foreign(entry: dict[str, Any], adopted: list[dict[str, str]]) -> bool:
    if entry.get("adopted"):
        return False
    return not is_adopted(entry["repo"], entry["path"], adopted)


def _foreign_entries(baseline: dict[str, Any], adopted: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [entry for entry in baseline.get("entries", []) if _entry_is_foreign(entry, adopted)]


def _baseline_states(entry: dict[str, Any], state_root: Path, snapshot_directory: str) -> tuple[State, State, State]:
    return (
        _state_from_descriptor(entry["head"], state_root, snapshot_directory),
        _state_from_descriptor(entry["index"], state_root, snapshot_directory),
        _state_from_descriptor(entry["worktree"], state_root, snapshot_directory),
    )


def _baseline_entry_conflict(
    entry: dict[str, Any],
    repo_root: Path,
    state_root: Path,
    snapshot_directory: str,
) -> str:
    path = entry["path"]
    base, baseline_index, baseline_worktree = _baseline_states(entry, state_root, snapshot_directory)
    current_head = _state_from_git(repo_root, "HEAD", path)
    current = (_state_from_git(repo_root, "", path), _state_from_worktree(repo_root, path))
    expected_index, index_error = _merge_expected(current_head, base, baseline_index)
    expected_worktree, worktree_error = _merge_expected(current_head, base, baseline_worktree)
    reason = index_error or worktree_error
    if reason:
        return f"OWNERSHIP_CONFLICT: {reason}"
    if current != (expected_index, expected_worktree):
        return "OWNERSHIP_CONFLICT_OR_RESIDUE: current state diverges from preserved baseline delta"
    return ""


def _baseline_conflicts(
    repo_paths: dict[str, Path],
    baseline: dict[str, Any],
    adopted: list[dict[str, str]],
    state_root: Path,
) -> tuple[list[str], set[str]]:
    """Conflict messages plus the keys whose current state matches the preserved baseline delta."""
    snapshot_directory = baseline.get("snapshot_directory", "")
    conflicts: list[str] = []
    preserved: set[str] = set()
    for entry in _foreign_entries(baseline, adopted):
        key = qualified(entry["repo"], entry["path"])
        conflict = _baseline_entry_conflict(entry, repo_paths[entry["repo"]], state_root, snapshot_directory)
        if conflict:
            conflicts.append(f"{key}: {conflict}")
        else:
            preserved.add(key)
    return conflicts, preserved


def assess_ownership(
    repo_paths: dict[str, Path],
    scope: list[dict[str, str]],
    baseline: dict[str, Any],
    adopted: list[dict[str, str]],
    state_root: Path,
) -> dict[str, list[str]]:
    _require_supported_baseline(baseline)
    own = _collect_own_state(repo_paths, scope)
    conflicts, preserved = _baseline_conflicts(repo_paths, baseline, adopted, state_root)
    _discard_keys(own, preserved)
    return {
        "staged": sorted(own["staged"]),
        "unstaged": sorted(own["unstaged"]),
        "untracked": sorted(own["untracked"]),
        "conflicts": sorted(set(conflicts)),
    }


@dataclass(frozen=True)
class _PrepareContext:
    repo_name: str
    repo_root: Path
    state_root: Path
    snapshot_directory: str
    adopted: list[dict[str, str]]


def _entries_by_path(baseline: dict[str, Any], repo_name: str) -> dict[str, dict[str, Any]]:
    return {
        normalize_rel(entry["path"]): entry
        for entry in baseline.get("entries", [])
        if entry.get("repo") == repo_name
    }


def _is_wholly_task_owned(entry: dict[str, Any] | None, path: str, ctx: _PrepareContext) -> bool:
    if entry is None:
        return True
    if entry.get("adopted"):
        return True
    return is_adopted(ctx.repo_name, path, ctx.adopted)


def _require_index_agrees_with_worktree(path: str, combined: State, ctx: _PrepareContext) -> None:
    """Guard staged != worktree only when there is no foreign baseline to isolate.

    Shared-file foreign hunks intentionally leave index != worktree.
    """
    index_state = _canonical_state(_state_from_git(ctx.repo_root, "", path))
    head_state = _canonical_state(_state_from_git(ctx.repo_root, "HEAD", path))
    if index_state in {head_state, _canonical_state(combined)}:
        return
    raise OwnershipError(
        f"{qualified(ctx.repo_name, path)}: staged index differs from worktree; "
        "stage or discard so index and worktree agree before task-commit"
    )


def _task_only_states(entry: dict[str, Any], path: str, combined: State, ctx: _PrepareContext) -> tuple[State, State]:
    base, foreign_index, foreign_worktree = _baseline_states(entry, ctx.state_root, ctx.snapshot_directory)
    label = qualified(ctx.repo_name, path)
    commit_state, subtract_error = _remove_foreign_delta(combined, base, foreign_worktree)
    if commit_state is None:
        raise OwnershipError(f"{label}: {subtract_error}")
    post_index_state, index_error = _merge_expected(commit_state, base, foreign_index)
    if post_index_state is None:
        raise OwnershipError(f"{label}: cannot preserve staged baseline: {index_error}")
    return commit_state, post_index_state


def _require_supported_state(path: str, label: str, state: State, ctx: _PrepareContext) -> None:
    if state[0] not in SUPPORTED_STATE_KINDS:
        raise OwnershipError(f"{qualified(ctx.repo_name, path)}: unsupported {label} {state[0]}")


def _path_commit_states(entry: dict[str, Any] | None, path: str, ctx: _PrepareContext) -> dict[str, State]:
    combined = _state_from_worktree(ctx.repo_root, path)
    if _is_wholly_task_owned(entry, path, ctx):
        _require_index_agrees_with_worktree(path, combined, ctx)
        commit_state, post_index_state = combined, combined
    else:
        commit_state, post_index_state = _task_only_states(entry, path, combined, ctx)
    _require_supported_state(path, "commit state", commit_state, ctx)
    _require_supported_state(path, "post-index state", post_index_state, ctx)
    return {"commit": commit_state, "post_index": post_index_state}


def prepare_owned_commit_states(
    repo_name: str,
    repo_root: Path,
    owned_paths: list[str],
    baseline: dict[str, Any],
    adopted: list[dict[str, str]],
    state_root: Path,
) -> dict[str, dict[str, State]]:
    """Build task-only commit states and post-commit real-index states per path.

    The returned commit state excludes pre-existing dirty work captured at task
    start. The post_index state reapplies any pre-existing staged delta on top
    of the new task commit, so the user's index remains semantically unchanged.
    """
    _require_supported_baseline(baseline)
    ctx = _PrepareContext(
        repo_name, repo_root, state_root, baseline.get("snapshot_directory", ""), adopted
    )
    entries = _entries_by_path(baseline, repo_name)
    result: dict[str, dict[str, State]] = {}
    for raw_path in sorted(set(owned_paths)):
        path = normalize_rel(raw_path)
        result[path] = _path_commit_states(entries.get(path), path, ctx)
    return result
