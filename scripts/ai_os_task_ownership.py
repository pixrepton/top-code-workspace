"""Baseline-aware ownership support for the AI-OS task checkpoint."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


OWNERSHIP_BASELINE_VERSION = 1


class OwnershipError(RuntimeError):
    pass


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


def capture_ownership_baseline(
    repo_paths: dict[str, Path],
    scope: list[dict[str, str]],
    baseline_shas: dict[str, str],
    adopted: list[dict[str, str]],
    state_root: Path,
    captured_at_utc: str,
) -> dict[str, Any]:
    storage = create_baseline_storage(state_root)
    entries: list[dict[str, Any]] = []
    snapshot_bytes = 0
    try:
        for repo, repo_root in repo_paths.items():
            repo_scopes = [item["path"] for item in scope if item["repo"] == repo]
            if not repo_scopes:
                continue
            raw = collect_raw_git_state(repo_root, repo_scopes)
            paths = sorted(raw["staged"] | raw["unstaged"] | raw["untracked"])
            for path in paths:
                status = [name for name in ("staged", "unstaged", "untracked") if path in raw[name]]
                entry: dict[str, Any] = {
                    "repo": repo,
                    "path": path,
                    "baseline_status": status,
                    "adopted": is_adopted(repo, path, adopted),
                }
                if not entry["adopted"]:
                    entry["head"] = _descriptor_from_git(repo_root, baseline_shas[repo], path, storage)
                    entry["index"] = _descriptor_from_git(repo_root, "", path, storage)
                    entry["worktree"] = _descriptor_from_worktree(repo_root, path, storage)
                    snapshot_bytes += sum(
                        state.get("size", 0) for state in (entry["head"], entry["index"], entry["worktree"])
                    )
                entries.append(entry)
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


State = tuple[str, bytes | None]


def _state_from_descriptor(descriptor: dict[str, Any], state_root: Path, snapshot_directory: str) -> State:
    kind = descriptor.get("kind", "unsupported")
    if kind == "missing":
        return ("missing", None)
    if kind not in {"file", "symlink"}:
        return (kind, None)
    target = state_root / snapshot_directory / descriptor["snapshot"]
    if not target.is_file():
        raise OwnershipError(f"ownership baseline snapshot is missing: {target}")
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != descriptor.get("sha256"):
        raise OwnershipError(f"ownership baseline snapshot hash mismatch: {target}")
    return (kind, data)


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


def _merge_expected(current: State, base: State, foreign: State) -> tuple[State | None, str]:
    if base[0] == "missing":
        if foreign[0] == "missing":
            return current, ""
        if current[0] == "missing":
            return foreign, ""
        return None, "task committed or staged a path that was foreign and untracked at task start"
    if foreign[0] == "missing":
        if current == base:
            return foreign, ""
        return None, "task overlapped or committed a pre-existing foreign deletion"
    if current[0] == "missing":
        if foreign == base:
            return current, ""
        return None, "task deleted a path carrying a pre-existing foreign delta"
    if foreign == base:
        return current, ""
    if current == base:
        return foreign, ""
    if current == foreign:
        return None, "task state absorbed a pre-existing foreign delta"
    if not all(state[0] == "file" for state in (current, base, foreign)):
        return None, "non-file baseline delta cannot be merged safely"
    if any(b"\0" in (state[1] or b"") for state in (current, base, foreign)):
        return None, "binary baseline delta overlaps a task change"
    # Git for Windows can fail to open merge inputs when a pytest/state path nears MAX_PATH.
    with tempfile.TemporaryDirectory(prefix="ai-os-ownership-") as tmp_raw:
        tmp = Path(tmp_raw)
        current_file = tmp / "current"
        base_file = tmp / "base"
        foreign_file = tmp / "foreign"
        current_file.write_bytes(current[1] or b"")
        base_file.write_bytes(base[1] or b"")
        foreign_file.write_bytes(foreign[1] or b"")
        proc = subprocess.run(
            ["git", "merge-file", "-p", str(current_file), str(base_file), str(foreign_file)],
            capture_output=True,
        )
    if proc.returncode == 0:
        if proc.stdout == (current[1] or b""):
            return None, "task state absorbed a pre-existing foreign delta"
        return ("file", proc.stdout), ""
    if proc.returncode == 1:
        return None, "task change overlaps a pre-existing foreign hunk"
    detail = proc.stderr.decode(errors="replace").strip()
    return None, f"three-way ownership merge failed: {detail or proc.returncode}"


def assess_ownership(
    repo_paths: dict[str, Path],
    scope: list[dict[str, str]],
    baseline: dict[str, Any],
    adopted: list[dict[str, str]],
    state_root: Path,
) -> dict[str, list[str]]:
    if baseline.get("version") != OWNERSHIP_BASELINE_VERSION:
        raise OwnershipError(f"unsupported ownership baseline version: {baseline.get('version')}")
    snapshot_directory = baseline.get("snapshot_directory", "")
    raw_by_repo: dict[str, dict[str, set[str]]] = {}
    own = {"staged": set(), "unstaged": set(), "untracked": set()}
    for repo, repo_root in repo_paths.items():
        repo_scopes = [item["path"] for item in scope if item["repo"] == repo]
        if not repo_scopes:
            continue
        raw = collect_raw_git_state(repo_root, repo_scopes)
        raw_by_repo[repo] = raw
        for category in own:
            own[category].update(qualified(repo, path) for path in raw[category])

    conflicts: list[str] = []
    for entry in baseline.get("entries", []):
        repo = entry["repo"]
        path = entry["path"]
        key = qualified(repo, path)
        if entry.get("adopted") or is_adopted(repo, path, adopted):
            continue
        repo_root = repo_paths[repo]
        base = _state_from_descriptor(entry["head"], state_root, snapshot_directory)
        baseline_index = _state_from_descriptor(entry["index"], state_root, snapshot_directory)
        baseline_worktree = _state_from_descriptor(entry["worktree"], state_root, snapshot_directory)
        current_head = _state_from_git(repo_root, "HEAD", path)
        current_index = _state_from_git(repo_root, "", path)
        current_worktree = _state_from_worktree(repo_root, path)
        expected_index, index_error = _merge_expected(current_head, base, baseline_index)
        expected_worktree, worktree_error = _merge_expected(current_head, base, baseline_worktree)
        if index_error or worktree_error:
            reason = index_error or worktree_error
            conflicts.append(f"{key}: OWNERSHIP_CONFLICT: {reason}")
            continue
        if current_index != expected_index or current_worktree != expected_worktree:
            conflicts.append(f"{key}: OWNERSHIP_CONFLICT_OR_RESIDUE: current state diverges from preserved baseline delta")
            continue
        for category in own:
            own[category].discard(key)

    return {
        "staged": sorted(own["staged"]),
        "unstaged": sorted(own["unstaged"]),
        "untracked": sorted(own["untracked"]),
        "conflicts": sorted(set(conflicts)),
    }
