"""Isolated Git worktrees for mutated repos in an Execution Bundle."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ai_os_task_errors import TaskError
from ai_os_task_git import canonical_repo_path, run

_BRANCH_SAFE = re.compile(r"[^A-Za-z0-9._/-]+")


def generation_worktree_dest(execution_root: Path, repo: str, generation: int) -> Path:
    if generation <= 1:
        return execution_root / "worktrees" / repo
    return execution_root / "worktrees" / repo / f"g{generation}"


def task_branch_name(task_id: str, execution_id: str, repo: str, *, generation: int = 1) -> str:
    short = execution_id.split("_")[-1][:6]
    # Keep every execution branch as a single ref leaf below ``task/``.
    # A legacy/user branch such as ``task/<task-id>`` is a file in the loose
    # refs store, so attempting to create ``task/<task-id>/<repo>/...`` fails
    # with a file-versus-directory collision.
    task_slug = _BRANCH_SAFE.sub("-", task_id.replace("/", "-")).strip("-") or "task"
    identity = f"{task_id}\0{repo}\0{generation}\0{execution_id}".encode("utf-8")
    digest = hashlib.sha256(identity).hexdigest()[:10]
    raw = f"task/{task_slug[:16]}-{digest}-g{generation}-{short}"
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
    run(
        ["git", "-c", "core.longpaths=true", "worktree", "add", "-b", branch, str(dest), base_sha],
        canonical,
    )
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
