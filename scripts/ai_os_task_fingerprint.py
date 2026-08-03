"""Content hashes that make gate verdicts reusable only for identical state."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ai_os_task_git import git_blob, repo_path, run
from ai_os_task_scope import normalize_rel


def sha256_bytes(parts: list[bytes]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
        digest.update(b"\0")
    return digest.hexdigest()


def sha256_text(parts: list[str]) -> str:
    return sha256_bytes([part.encode("utf-8", errors="replace") for part in parts])


def _status_lines(path: Path, rel_paths: list[str]) -> str:
    args = ["git", "status", "--porcelain", "--untracked-files=all", "--", *rel_paths]
    return run(args, path).stdout


def staged_diff_hash(repo: str) -> str:
    path = repo_path(repo)
    return sha256_bytes([git_blob(["git", "diff", "--cached", "--binary"], path)])


def _untracked_hash(root: Path, line: str) -> str:
    if not line.startswith("?? "):
        return ""
    rel = normalize_rel(line[3:])
    full = root / rel
    if not full.is_file():
        return ""
    return f"{rel}:{hashlib.sha256(full.read_bytes()).hexdigest()}"


def untracked_file_hashes(path: Path, rel_paths: list[str]) -> list[str]:
    lines = _status_lines(path, rel_paths).splitlines()
    values = (_untracked_hash(path, line) for line in lines)
    return [value for value in values if value]


def scope_hash(repo: str, rel_paths: list[str]) -> str:
    path = repo_path(repo)
    status = _status_lines(path, rel_paths)
    diff = git_blob(["git", "diff", "--binary", "--", *rel_paths], path)
    untracked = "\n".join(sorted(untracked_file_hashes(path, rel_paths)))
    return sha256_bytes([status.encode("utf-8"), diff, untracked.encode("utf-8")])


def _config_parts(repo_root: Path, raw: str) -> list[bytes]:
    candidate = Path(raw)
    full = candidate if candidate.is_absolute() else repo_root / raw
    if not full.exists():
        return [f"MISSING:{raw}".encode()]
    if full.is_file():
        return [f"FILE:{normalize_rel(raw)}".encode(), full.read_bytes()]
    return [f"DIR:{normalize_rel(raw)}".encode()]


def config_hash(repo: str, values: list[str]) -> str:
    if not values:
        return sha256_text([""])
    path = repo_path(repo)
    parts: list[bytes] = []
    for raw in values:
        parts.extend(_config_parts(path, raw))
    return sha256_bytes(parts)
