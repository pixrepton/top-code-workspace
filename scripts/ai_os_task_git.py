from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_os_task_constants import PROTECTED_BRANCH_NAMES, WORKSPACE
from ai_os_task_errors import TaskError
from ai_os_task_scope import normalize_rel

def run(args: list[str], cwd: Path, check: bool = True, text: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=str(cwd), text=text, capture_output=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise TaskError(f"command failed ({proc.returncode}): {' '.join(args)}\n{detail}")
    return proc

def canonical_repo_path(repo: str) -> Path:
    """Shared checkout. Execution Bundle worktrees are never this path."""
    if repo in {".", "root", "workspace"}:
        path = WORKSPACE
    else:
        path = WORKSPACE / repo
    if not path.exists():
        raise TaskError(f"repo path does not exist: {path}")
    if not (path / ".git").exists():
        raise TaskError(f"path is not a git repository root: {path}")
    return path.resolve()


def repo_path(repo: str) -> Path:
    """Task runtime path: Execution Bundle worktree when present, else canonical checkout."""
    from ai_os_execution.bundle import configured_worktree_path

    configured = configured_worktree_path(repo)
    if configured is not None:
        path = configured
        if not path.exists():
            raise TaskError(f"execution worktree missing: {path}")
        if not (path / ".git").exists():
            raise TaskError(f"execution worktree is not a git checkout: {path}")
        return path.resolve()
    return canonical_repo_path(repo)

def git_head(repo: str) -> str:
    return run(["git", "rev-parse", "--verify", "HEAD"], repo_path(repo)).stdout.strip()

def git_short_head(repo: str) -> str:
    return git_head(repo)[:7]

def git_branch(repo: str) -> str:
    return run(["git", "branch", "--show-current"], repo_path(repo)).stdout.strip()

def git_default_branch(repo: str) -> str:
    path = repo_path(repo)
    remote = run(["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], path, check=False)
    if remote.returncode == 0 and remote.stdout.strip():
        return remote.stdout.strip().split("/", 1)[-1]
    for candidate in ("main", "master", "trunk"):
        if run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{candidate}"], path, check=False).returncode == 0:
            return candidate
    return ""

def branch_is_protected(repo: str, branch: str) -> bool:
    if not branch:
        return True
    default = git_default_branch(repo)
    return branch in PROTECTED_BRANCH_NAMES or (default and branch == default)

def git_operation_in_progress(repo: str) -> str:
    path = repo_path(repo)
    git_dir_raw = run(["git", "rev-parse", "--git-dir"], path).stdout.strip()
    git_dir = Path(git_dir_raw)
    if not git_dir.is_absolute():
        git_dir = (path / git_dir).resolve()
    checks = {
        "merge": git_dir / "MERGE_HEAD",
        "cherry-pick": git_dir / "CHERRY_PICK_HEAD",
        "revert": git_dir / "REVERT_HEAD",
        "rebase": git_dir / "rebase-merge",
        "rebase-apply": git_dir / "rebase-apply",
    }
    for name, candidate in checks.items():
        if candidate.exists():
            return name
    return ""

def sha256_bytes(parts: list[bytes]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()

def sha256_text(parts: list[str]) -> str:
    return sha256_bytes([part.encode("utf-8", errors="replace") for part in parts])

def git_blob(args: list[str], cwd: Path) -> bytes:
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True)
    if proc.returncode != 0:
        raise TaskError(f"git command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr.decode(errors='replace')}")
    return proc.stdout

def staged_diff_hash(repo: str) -> str:
    path = repo_path(repo)
    return sha256_bytes([git_blob(["git", "diff", "--cached", "--binary"], path)])

def untracked_file_hashes(path: Path, rel_paths: list[str]) -> list[str]:
    status = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *rel_paths], path).stdout.splitlines()
    values: list[str] = []
    for line in status:
        if not line.startswith("?? "):
            continue
        rel = normalize_rel(line[3:])
        full = path / rel
        if full.is_file():
            values.append(f"{rel}:{hashlib.sha256(full.read_bytes()).hexdigest()}")
    return values

def scope_hash(repo: str, rel_paths: list[str]) -> str:
    path = repo_path(repo)
    status = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *rel_paths], path).stdout
    diff = git_blob(["git", "diff", "--binary", "--", *rel_paths], path)
    untracked = "\n".join(sorted(untracked_file_hashes(path, rel_paths)))
    return sha256_bytes([status.encode("utf-8"), diff, untracked.encode("utf-8")])

def config_hash(repo: str, values: list[str]) -> str:
    if not values:
        return sha256_text([""])
    path = repo_path(repo)
    parts: list[bytes] = []
    for raw in values:
        candidate = Path(raw)
        full = candidate if candidate.is_absolute() else path / raw
        if not full.exists():
            parts.append(f"MISSING:{raw}".encode())
        elif full.is_file():
            parts.append(f"FILE:{normalize_rel(raw)}".encode())
            parts.append(full.read_bytes())
        else:
            parts.append(f"DIR:{normalize_rel(raw)}".encode())
    return sha256_bytes(parts)
