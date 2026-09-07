"""Isolated Git worktrees for mutated repos in an Execution Bundle."""

from __future__ import annotations

import re
from pathlib import Path

from ai_os_task_errors import TaskError
from ai_os_task_git import canonical_repo_path, run

_BRANCH_SAFE = re.compile(r"[^A-Za-z0-9._/-]+")


def task_branch_name(task_id: str, execution_id: str, repo: str) -> str:
    short = execution_id.split("_")[-1][:8]
    raw = f"task/{task_id}/{repo}/{short}"
    cleaned = _BRANCH_SAFE.sub("-", raw).strip("-")
    return cleaned[:200]


def add_repo_worktree(
    *,
    repo: str,
    dest: Path,
    branch: str,
    base_sha: str,
) -> dict[str, str]:
    canonical = canonical_repo_path(repo)
    dest = dest.resolve()
    if dest.exists():
        raise TaskError(f"worktree destination already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    exists = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], canonical, check=False)
    if exists.returncode == 0:
        raise TaskError(f"task branch already exists in canonical repo: {branch}")
    run(["git", "worktree", "add", "-b", branch, str(dest), base_sha], canonical)
    head = run(["git", "rev-parse", "--verify", "HEAD"], dest).stdout.strip()
    current_branch = run(["git", "branch", "--show-current"], dest).stdout.strip()
    return {
        "canonical_repo": str(canonical),
        "worktree_path": str(dest),
        "base_sha": base_sha,
        "current_sha": head,
        "branch": current_branch or branch,
    }


def remove_repo_worktree(repo: str, dest: Path, *, force: bool = False) -> None:
    canonical = canonical_repo_path(repo)
    dest = dest.resolve()
    args = ["git", "worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(dest))
    proc = run(args, canonical, check=False)
    if proc.returncode != 0 and dest.exists():
        raise TaskError((proc.stderr or proc.stdout or f"worktree remove failed: {dest}").strip())


def worktree_head(worktree: Path) -> str:
    return run(["git", "rev-parse", "--verify", "HEAD"], worktree).stdout.strip()
