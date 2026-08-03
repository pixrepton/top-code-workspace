#!/usr/bin/env python3
"""Timed CBM MCP diagnostics outside Cursor (cold/warm, per-project)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CBM_ENV = {
    "CBM_ALLOWED_ROOT": "C:/Users/compg/Desktop/top-code workspace",
    "CBM_CACHE_DIR": "C:/ai-os-codebase-memory",
}
CBM_EXE = Path.home() / ".local" / "bin" / "codebase-memory-mcp.exe"
CBM_UVX_ARGS = ["--from", "codebase-memory-mcp==0.9.0", "codebase-memory-mcp"]

THRESHOLD_SCHEMA_S = 10.0
THRESHOLD_QUERY_S = 30.0


@dataclass
class StepTiming:
    name: str
    seconds: float
    ok: bool
    detail: str = ""


@dataclass
class RunReport:
    label: str
    project: str
    run_index: int
    steps: list[StepTiming] = field(default_factory=list)
    error: str = ""


def resolve_cbm_launch() -> tuple[str, list[str]]:
    if CBM_EXE.exists():
        return str(CBM_EXE), []
    return "uvx", CBM_UVX_ARGS


def send(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def read_json_line(proc: subprocess.Popen[str], timeout: float) -> dict[str, Any]:
    assert proc.stdout is not None
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.02)
            continue
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
    raise TimeoutError(f"no JSON line within {timeout}s")


def call_tool(proc: subprocess.Popen[str], tool: str, arguments: dict[str, Any], req_id: int, timeout: float) -> dict[str, Any]:
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    return read_json_line(proc, timeout)


def timed_session(project: str, label: str, run_index: int) -> RunReport:
    report = RunReport(label=label, project=project, run_index=run_index)
    command, args = resolve_cbm_launch()
    env = os.environ.copy()
    env.update(CBM_ENV)

    t0 = time.perf_counter()
    executable = command
    if not Path(executable).exists() and not shutil.which(executable):
        if os.name == "nt":
            executable = shutil.which(f"{command}.cmd") or executable
    proc = subprocess.Popen(
        [executable, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    report.steps.append(StepTiming("process_start", time.perf_counter() - t0, True))

    try:
        t1 = time.perf_counter()
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cbm-diagnose", "version": "1.0"},
                },
            },
        )
        init_resp = read_json_line(proc, 60.0)
        report.steps.append(
            StepTiming(
                "initialize",
                time.perf_counter() - t1,
                "serverInfo" in init_resp.get("result", {}),
                json.dumps(init_resp.get("result", {}).get("serverInfo", {})),
            )
        )
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        t2 = time.perf_counter()
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_resp = read_json_line(proc, 60.0)
        tools = tools_resp.get("result", {}).get("tools", [])
        report.steps.append(StepTiming("tools/list", time.perf_counter() - t2, bool(tools), f"count={len(tools)}"))

        t3 = time.perf_counter()
        schema_resp = call_tool(proc, "get_graph_schema", {"project": project}, 3, 120.0)
        schema_ok = "error" not in schema_resp
        report.steps.append(
            StepTiming(
                "get_graph_schema",
                time.perf_counter() - t3,
                schema_ok,
                (schema_resp.get("error", {}) or {}).get("message", "ok") if not schema_ok else "ok",
            )
        )

        t4 = time.perf_counter()
        search_resp = call_tool(
            proc,
            "search_graph",
            {"project": project, "query": "task", "limit": 1},
            4,
            120.0,
        )
        search_ok = "error" not in search_resp
        report.steps.append(
            StepTiming(
                "search_graph",
                time.perf_counter() - t4,
                search_ok,
                (search_resp.get("error", {}) or {}).get("message", "ok") if not search_ok else "ok",
            )
        )

        t5 = time.perf_counter()
        query_resp = call_tool(
            proc,
            "query_graph",
            {"project": project, "query": "RETURN 1 AS ok LIMIT 1"},
            5,
            120.0,
        )
        query_ok = "error" not in query_resp
        report.steps.append(
            StepTiming(
                "query_graph",
                time.perf_counter() - t5,
                query_ok,
                (query_resp.get("error", {}) or {}).get("message", "ok") if not query_ok else "ok",
            )
        )
    except Exception as exc:
        report.error = str(exc)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    return report


def list_index_files() -> list[dict[str, Any]]:
    cache = Path(CBM_ENV["CBM_CACHE_DIR"])
    rows: list[dict[str, Any]] = []
    if not cache.exists():
        return rows
    for path in sorted(cache.glob("*.db")):
        if path.name.endswith(("-shm", "-wal")):
            continue
        rows.append(
            {
                "name": path.name,
                "mb": round(path.stat().st_size / (1024 * 1024), 2),
                "mtime": path.stat().st_mtime,
            }
        )
    return sorted(rows, key=lambda row: row["mb"], reverse=True)


def discover_projects() -> list[str]:
    command, args = resolve_cbm_launch()
    env = os.environ.copy()
    env.update(CBM_ENV)
    proc = subprocess.Popen(
        [command, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    projects: list[str] = []
    try:
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "cbm-diagnose", "version": "1.0"},
                },
            },
        )
        read_json_line(proc, 30.0)
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        # list_projects is not always exposed; infer from cache + known ids
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

    for row in list_index_files():
        name = row["name"]
        if name.endswith(".db"):
            projects.append(name[:-3])
    known = ["gmail-audit", "C-Users-compg-Desktop-top-code-workspace-gmail-agent"]
    for item in known:
        if item not in projects:
            projects.append(item)
    return projects


def summarize_report(report: RunReport) -> dict[str, Any]:
    by_name = {step.name: step for step in report.steps}
    schema_s = by_name.get("get_graph_schema", StepTiming("get_graph_schema", 0, False)).seconds
    query_s = max(
        by_name.get("search_graph", StepTiming("search_graph", 0, False)).seconds,
        by_name.get("query_graph", StepTiming("query_graph", 0, False)).seconds,
    )
    return {
        "label": report.label,
        "project": report.project,
        "run": report.run_index,
        "error": report.error,
        "steps": [
            {"name": s.name, "seconds": round(s.seconds, 3), "ok": s.ok, "detail": s.detail}
            for s in report.steps
        ],
        "schema_seconds": round(schema_s, 3),
        "query_seconds": round(query_s, 3),
        "schema_within_10s": schema_s <= THRESHOLD_SCHEMA_S,
        "query_within_30s": query_s <= THRESHOLD_QUERY_S,
    }


def main() -> int:
    projects = [
        ("gmail-audit", "smallest-known"),
        ("C-Users-compg-Desktop-top-code-workspace-gmail-agent", "full-gmail-agent"),
    ]
    # pick smallest db-backed project if gmail-audit missing from cache names
    index_rows = list_index_files()
    smallest = min(index_rows, key=lambda r: r["mb"]) if index_rows else None
    if smallest:
        smallest_id = smallest["name"][:-3]
        if smallest_id not in {p[0] for p in projects}:
            projects.insert(0, (smallest_id, "smallest-db"))

    payload: dict[str, Any] = {
        "cbm_launch": {"command": resolve_cbm_launch()[0], "args": resolve_cbm_launch()[1]},
        "indexes": index_rows[:25],
        "runs": [],
    }

    for project, label in projects:
        for run_index in (1, 2):
            report = timed_session(project, label, run_index)
            payload["runs"].append(summarize_report(report))

    print(json.dumps(payload, ensure_ascii=False, indent=2))

    failing = [
        run
        for run in payload["runs"]
        if run.get("error")
        or not run.get("schema_within_10s")
        or not run.get("query_within_30s")
    ]
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
