"""Shared Execution Plane start helpers for harness tests.

Mutating isolation tests must provision a plane (`start --no-db-isolation`)
and pass `--execution-mode TEST` (or `--workspace-mode ISOLATED_WORKTREE`).
Ordinary MUTATE starts bind to the canonical checkout. `--legacy` is only for
explicit SMALL + DOCS/STATIC compatibility coverage — never as a workaround
for plane DB isolation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

STORE_KEYS = (
    "MAILBOX_MEMORY_DATABASE_URL",
    "MAILBOX_MEMORY_ASOF_DATABASE_URL",
    "DATABASE_URL",
    "AI_OS_EXECUTION_ID",
    "AI_OS_TASK_ID",
    "AI_OS_REPO_PATH",
    "AI_OS_GRAPH_INDEX_SHA",
    "AI_OS_DB_HOST",
    "AI_OS_DB_CONTAINER_HOST",
)


def child_env(env: dict[str, str] | None = None) -> dict[str, str]:
    merged = os.environ.copy()
    for key in STORE_KEYS:
        merged.pop(key, None)
    if env:
        merged.update(env)
    return merged


def plane_start_args(
    *,
    task_id: str,
    title: str,
    repo: str,
    scope: str,
    task_class: str = "SMALL",
    extra: list[str] | None = None,
) -> list[str]:
    args = [
        "start",
        "--task-id",
        task_id,
        "--title",
        title,
        "--class",
        task_class,
        "--repo",
        repo,
        "--scope",
        scope,
        "--no-db-isolation",
        "--execution-mode",
        "TEST",
    ]
    if extra:
        args.extend(extra)
    return args


def parse_json_stdout(text: str) -> Any:
    """Parse the first JSON object from CLI stdout that may include gate banners."""
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("Expecting object", text, 0)
    obj, _end = json.JSONDecoder().raw_decode(text[start:])
    return obj


def worktree_path(
    run_cmd: Callable[..., Any],
    env: dict[str, str],
    repo: str,
    task_id: str | None = None,
) -> Path:
    args = ["task-repo", "--repo", repo]
    if task_id:
        args.extend(["--task-id", task_id])
    payload = parse_json_stdout(run_cmd(args, env=env).stdout)
    return Path(payload["path"])
