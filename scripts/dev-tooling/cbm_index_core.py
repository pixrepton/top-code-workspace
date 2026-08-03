#!/usr/bin/env python3
"""Indexing primitives for the CBM MCP index_repository tool."""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cbm_mcp_stdio import CBM_ENV, cbm_session  # noqa: E402

CLIENT_NAME = "cbm-index"
HANDSHAKE_TIMEOUT_S = 120.0
INDEX_TIMEOUT_S = 3600.0
SHUTDOWN_TIMEOUT_S = 5.0

NESTED_REPOS = (
    "gmail-agent",
    "kalk-top",
    "daszek",
    "cieplo-orchestrator",
    "rag-chat-asystent",
    "rag-widget",
    "top-instal-generator",
    "fast-kalk",
    "knowledge",
    "wp-bridges",
)
WORKSPACE_ROOT_ALIASES = {"workspace-root", "workspace"}


@contextmanager
def index_lock(timeout: float = 60.0) -> Iterator[None]:
    cache = Path(CBM_ENV["CBM_CACHE_DIR"])
    cache.mkdir(parents=True, exist_ok=True)
    lock_path = cache / ".index.lock"
    _acquire_lock(lock_path, timeout)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _acquire_lock(lock_path: Path, timeout: float) -> None:
    start = time.perf_counter()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            if time.perf_counter() - start > timeout:
                raise TimeoutError(f"index lock held: {lock_path}") from None
            time.sleep(0.5)


def index_repo(repo_path: Path, *, mode: str | None = None, timeout: float = INDEX_TIMEOUT_S) -> dict[str, Any]:
    with cbm_session(shutdown_timeout=SHUTDOWN_TIMEOUT_S) as session:
        session.initialize(CLIENT_NAME, HANDSHAKE_TIMEOUT_S)
        session.notify_initialized()
        payload: dict[str, Any] = {
            "repo_path": str(repo_path).replace("\\", "/"),
            "mode": mode or "full",
        }
        return session.call_tool("index_repository", payload, timeout)


def wants_workspace_root(only: set[str]) -> bool:
    if not only:
        return True
    return bool(only & WORKSPACE_ROOT_ALIASES)


def resolve_targets(workspace: Path, only: set[str]) -> list[tuple[str, Path]]:
    targets: list[tuple[str, Path]] = []
    if wants_workspace_root(only):
        targets.append(("workspace-root", workspace))
    for name in NESTED_REPOS:
        if only and name not in only:
            continue
        path = workspace / name
        if path.exists():
            targets.append((name, path))
        else:
            print(f"SKIP missing: {path}", flush=True)
    return targets


def index_target(label: str, path: Path) -> tuple[dict[str, Any], bool]:
    """Index one repository. Returns (result entry, failed)."""
    print(f"INDEX {label}: {path}", flush=True)
    start = time.perf_counter()
    try:
        with index_lock():
            resp = index_repo(path)
    except Exception as exc:
        print(f"ERROR {label}: {exc}", flush=True)
        return {"label": label, "path": str(path), "error": str(exc)}, True
    entry = {
        "label": label,
        "path": str(path),
        "seconds": round(time.perf_counter() - start, 1),
        "response": resp,
    }
    print(json.dumps(entry, ensure_ascii=False)[:2000], flush=True)
    return entry, bool(resp.get("result", {}).get("isError"))
