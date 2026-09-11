"""Promote an isolated task worktree into the canonical desktop checkout."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_os_execution.workspace_mode import PROMOTE_ON_CLOSE_MODES, checkout_is_canonical
from ai_os_execution.worktree import worktree_head
from ai_os_task_errors import TaskError
from ai_os_task_git import run
from ai_os_task_paths import utc_now


def promote_isolated_to_canonical(bundle: dict[str, Any]) -> dict[str, Any]:
    """Fast-forward canonical checkouts to accepted isolated HEADs.

    Does not rewrite history, does not reset, and does not delete worktrees.
    Diverged histories fail closed so both sides remain recoverable.
    """
    workspace_mode = str(bundle.get("workspace_mode") or "")
    execution_mode = str(bundle.get("execution_mode") or "")
    if workspace_mode != "ISOLATED_WORKTREE":
        payload = {"required": False, "status": "NOT_ISOLATED", "results": []}
        bundle["promotion"] = {**payload, "at": utc_now()}
        return payload
    if execution_mode not in PROMOTE_ON_CLOSE_MODES:
        payload = {"required": False, "status": "SKIPPED_NON_PRODUCT_MODE", "results": []}
        bundle["promotion"] = {**payload, "at": utc_now()}
        return payload

    results: list[dict[str, Any]] = []
    for repo, entry in (bundle.get("repos") or {}).items():
        dest = Path(str(entry.get("worktree_path") or ""))
        canonical = Path(str(entry.get("canonical_repo") or ""))
        if not dest.exists() or not canonical.exists():
            raise TaskError(f"PROMOTION_FAILED {repo}: checkout missing")
        if checkout_is_canonical(repo, dest):
            results.append({"repo": repo, "status": "ALREADY_CANONICAL"})
            continue
        wt_head = worktree_head(dest)
        can_head = run(["git", "rev-parse", "--verify", "HEAD"], canonical).stdout.strip()
        if wt_head == can_head:
            results.append({"repo": repo, "status": "ALREADY_EQUAL", "head": wt_head})
            continue
        ancestor = run(
            ["git", "merge-base", "--is-ancestor", can_head, wt_head],
            canonical,
            check=False,
        )
        if ancestor.returncode == 0:
            merged = run(["git", "merge", "--ff-only", wt_head], canonical, check=False)
            if merged.returncode != 0:
                detail = (merged.stderr or merged.stdout or "").strip()
                raise TaskError(f"PROMOTION_FAILED {repo}: fast-forward blocked: {detail}")
            results.append(
                {
                    "repo": repo,
                    "status": "FAST_FORWARD",
                    "from": can_head,
                    "to": wt_head,
                }
            )
            continue
        behind = run(
            ["git", "merge-base", "--is-ancestor", wt_head, can_head],
            canonical,
            check=False,
        )
        if behind.returncode == 0:
            results.append(
                {
                    "repo": repo,
                    "status": "SUPERSEDED_BY_CANONICAL",
                    "canonical": can_head,
                    "worktree": wt_head,
                }
            )
            continue
        raise TaskError(
            f"PROMOTION_DIVERGED {repo}: canonical {can_head[:12]} and worktree "
            f"{wt_head[:12]} are both unique; STOP and resolve semantically"
        )

    payload = {"required": True, "status": "PROMOTED", "results": results}
    bundle["promotion"] = {**payload, "at": utc_now()}
    return payload
