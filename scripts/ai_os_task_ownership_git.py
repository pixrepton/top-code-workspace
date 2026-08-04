"""Path/scope helpers and raw git name collection for ownership."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ai_os_task_errors import OwnershipError

__all__ = [
    "OwnershipError",
    "collect_raw_git_state",
    "is_adopted",
    "normalize_rel",
    "path_matches",
    "qualified",
    "run_git_bytes",
    "scope_contains",
]


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


def run_git_bytes(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True)
    if check and proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise OwnershipError(f"command failed ({proc.returncode}): {' '.join(args)}\n{detail}")
    return proc


def _git_names(repo_path: Path, args: list[str], scopes: list[str]) -> set[str]:
    proc = run_git_bytes(["git", *args, "-z", "--", *scopes], repo_path)
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
