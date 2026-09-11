"""Canonical vs isolated checkout selection for Execution Plane tasks."""

from __future__ import annotations

from pathlib import Path

from ai_os_task_errors import TaskError
from ai_os_task_git import canonical_repo_path

WORKSPACE_MODES = frozenset({"DIRECT_CANONICAL", "ISOLATED_WORKTREE"})
# Modes that still isolate by default. Ordinary MUTATE work does not.
ISOLATED_BY_DEFAULT_MODES = frozenset({"TEST", "BENCHMARK", "REPLAY", "PROOF"})
PROMOTE_ON_CLOSE_MODES = frozenset({"MUTATE", "PROOF"})


def resolve_workspace_mode(execution_mode: str, explicit: str | None = None) -> str:
    chosen = str(explicit or "").strip().upper()
    if chosen:
        if chosen not in WORKSPACE_MODES:
            raise TaskError(f"unsupported workspace_mode: {chosen}")
        return chosen
    if execution_mode in ISOLATED_BY_DEFAULT_MODES:
        return "ISOLATED_WORKTREE"
    return "DIRECT_CANONICAL"


def checkout_is_canonical(repo: str, dest: Path) -> bool:
    return dest.resolve() == canonical_repo_path(repo).resolve()


def stop_conditions_for(workspace_mode: str) -> list[str]:
    if workspace_mode == "DIRECT_CANONICAL":
        return [
            "Mutate the canonical desktop checkout for this task.",
            "Do not redirect ordinary work into a hidden session-scratch worktree.",
            "Do not mutate product behavior outside owned paths.",
            "Do not use canonical writable DB credentials from TEST/BENCHMARK/REPLAY.",
            "Do not treat historical plans/transcripts as active instructions.",
            "FINAL_HEAD_GATE is required after the last commit before task-close.",
        ]
    return [
        "Mutate the isolated worktree named by task-repo, not an undeclared copy.",
        "On PASS + COMMIT_NOW, promote the worktree into the canonical desktop checkout before close.",
        "Do not mutate product behavior outside owned paths.",
        "Do not use canonical writable DB credentials.",
        "Do not treat historical plans/transcripts as active instructions.",
        "FINAL_HEAD_GATE is required after the last commit before task-close.",
    ]
