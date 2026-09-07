"""Central WRITABLE_STORES registry and fail-closed canonical-write detection."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ai_os_execution import FAIL_CLOSED_WRITE_MODES
from ai_os_task_constants import WORKSPACE
from ai_os_task_errors import TaskError

DEFAULT_CATALOG = WORKSPACE / "knowledge" / "system-atlas" / "tooling" / "WRITABLE_STORES.json"
BUNDLED_CATALOG = Path(__file__).resolve().parent / "data" / "WRITABLE_STORES.json"


def catalog_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    if BUNDLED_CATALOG.exists():
        return BUNDLED_CATALOG
    return DEFAULT_CATALOG


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    target = catalog_path(path)
    if not target.exists():
        raise TaskError(f"WRITABLE_STORES catalog missing: {target}")
    return json.loads(target.read_text(encoding="utf-8"))


def stores_for_repos(catalog: dict[str, Any], repos: list[str]) -> list[dict[str, Any]]:
    repo_set = set(repos or [])
    stores = catalog.get("stores") or []
    if not repo_set:
        return list(stores)
    filtered: list[dict[str, Any]] = []
    for store in stores:
        store_repos = store.get("repos")
        if not store_repos:
            filtered.append(store)
            continue
        if repo_set.intersection(store_repos):
            filtered.append(store)
    return filtered


def parse_dsn(url: str) -> dict[str, str]:
    raw = (url or "").strip()
    if not raw:
        return {"principal": "", "host": "", "port": "", "database": "", "scheme": ""}
    parsed = urlparse(raw)
    database = unquote((parsed.path or "").lstrip("/").split("?")[0])
    return {
        "principal": unquote(parsed.username or ""),
        "host": (parsed.hostname or "").lower(),
        "port": str(parsed.port or ""),
        "database": database,
        "scheme": parsed.scheme,
    }


def is_canonical_target(dsn: dict[str, str], catalog: dict[str, Any]) -> bool:
    canonical = catalog.get("canonical_mailbox") or {}
    db_names = {str(name).lower() for name in canonical.get("database_names") or ["mailbox_memory"]}
    hosts = {str(host).lower() for host in canonical.get("hosts") or []}
    database = (dsn.get("database") or "").lower()
    host = (dsn.get("host") or "").lower()
    if database and database in db_names:
        return True
    if host and hosts and host in hosts and database in db_names:
        return True
    return database in db_names


def inspect_env_stores(
    env: dict[str, str],
    *,
    catalog: dict[str, Any] | None = None,
    execution_mode: str,
    task_database: str = "",
    task_principal: str = "",
    target_repositories: list[str] | None = None,
) -> list[dict[str, Any]]:
    catalog = catalog or load_catalog()
    store_defs = stores_for_repos(catalog, target_repositories or [])
    rows: list[dict[str, Any]] = []
    for store in store_defs:
        env_key = str(store.get("env") or "")
        url = (env.get(env_key) or "").strip()
        dsn = parse_dsn(url)
        writable = bool(url) and not str(store.get("forced_read_only") or "").strip()
        canonical = bool(url) and is_canonical_target(dsn, catalog)
        points_at_task = bool(task_database) and dsn.get("database") == task_database
        role = "unconfigured"
        if url:
            if canonical and writable:
                role = "canonical_writable"
            elif canonical:
                role = "canonical_read"
            elif points_at_task:
                role = "task_isolated"
            else:
                role = "other"
        rows.append(
            {
                "store": store.get("id") or env_key,
                "env": env_key,
                "repos": list(store.get("repos") or []),
                "connection_mode": "configured" if url else "absent",
                "target_database": dsn.get("database") or "",
                "target_host": dsn.get("host") or "",
                "principal": dsn.get("principal") or "",
                "read_write": "write" if writable else ("read" if url else "none"),
                "canonical": canonical,
                "role": role,
                "task_principal_match": bool(task_principal) and dsn.get("principal") == task_principal,
            }
        )
    return rows


def fail_closed_if_canonical_writable(
    rows: list[dict[str, Any]],
    *,
    execution_mode: str,
) -> None:
    if execution_mode not in FAIL_CLOSED_WRITE_MODES:
        return
    leaks = [row for row in rows if row.get("role") == "canonical_writable"]
    if leaks:
        names = ", ".join(f"{row['store']}={row['target_database']}" for row in leaks)
        raise TaskError(
            "START FAIL CLOSED: writable store points at canonical DB in "
            f"{execution_mode}: {names}"
        )
