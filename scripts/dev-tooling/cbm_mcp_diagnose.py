#!/usr/bin/env python3
"""Timed CBM MCP diagnostics outside Cursor (cold/warm, per-project)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cbm_diagnose_session import (  # noqa: E402
    RunReport,
    StepTiming,
    THRESHOLD_QUERY_S,
    THRESHOLD_SCHEMA_S,
    summarize_report,
    timed_session,
)
from cbm_mcp_stdio import (  # noqa: E402
    CBM_ENV,
    ROOT,
    cbm_session,
    list_index_files,
    resolve_cbm_launch,
)

__all__ = [
    "CBM_ENV",
    "ROOT",
    "RunReport",
    "StepTiming",
    "THRESHOLD_QUERY_S",
    "THRESHOLD_SCHEMA_S",
    "discover_projects",
    "list_index_files",
    "main",
    "resolve_cbm_launch",
    "summarize_report",
    "timed_session",
]

KNOWN_PROJECTS = ("gmail-audit", "C-Users-compg-Desktop-top-code-workspace-gmail-agent")
DEFAULT_PROBES = (
    ("gmail-audit", "smallest-known"),
    ("C-Users-compg-Desktop-top-code-workspace-gmail-agent", "full-gmail-agent"),
)


def discover_projects() -> list[str]:
    with cbm_session(shutdown_timeout=2.0) as session:
        # list_projects is not always exposed; infer from cache + known ids
        session.initialize("cbm-diagnose", 30.0)
        session.notify_initialized()

    projects = [row["name"][:-3] for row in list_index_files() if row["name"].endswith(".db")]
    for item in KNOWN_PROJECTS:
        if item not in projects:
            projects.append(item)
    return projects


def projects_to_probe(index_rows: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Prepend the smallest db-backed project when it is not already probed."""
    projects = list(DEFAULT_PROBES)
    if not index_rows:
        return projects
    smallest_id = min(index_rows, key=lambda row: row["mb"])["name"][:-3]
    if smallest_id not in {project for project, _label in projects}:
        projects.insert(0, (smallest_id, "smallest-db"))
    return projects


def run_failed(run: dict[str, Any]) -> bool:
    if run.get("error"):
        return True
    if not run.get("schema_within_10s"):
        return True
    return not run.get("query_within_30s")


def collect_runs(probes: list[tuple[str, str]]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for project, label in probes:
        for run_index in (1, 2):
            runs.append(summarize_report(timed_session(project, label, run_index)))
    return runs


def main() -> int:
    index_rows = list_index_files()
    command, args = resolve_cbm_launch()
    payload: dict[str, Any] = {
        "cbm_launch": {"command": command, "args": args},
        "indexes": index_rows[:25],
        "runs": collect_runs(projects_to_probe(index_rows)),
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if any(run_failed(run) for run in payload["runs"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
