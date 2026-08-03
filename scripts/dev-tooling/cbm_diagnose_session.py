#!/usr/bin/env python3
"""Timed probe of one CBM MCP session plus its report summary."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cbm_mcp_stdio import McpStdioSession, cbm_session  # noqa: E402

CLIENT_NAME = "cbm-diagnose"
POLL_INTERVAL_S = 0.02
SHUTDOWN_TIMEOUT_S = 3.0
HANDSHAKE_TIMEOUT_S = 60.0
TOOL_TIMEOUT_S = 120.0

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


def _elapsed_step(name: str, start: float, ok: bool, detail: str = "") -> StepTiming:
    return StepTiming(name, time.perf_counter() - start, ok, detail)


def _step_initialize(session: McpStdioSession, report: RunReport) -> None:
    start = time.perf_counter()
    result = session.initialize(CLIENT_NAME, HANDSHAKE_TIMEOUT_S).get("result", {})
    detail = json.dumps(result.get("serverInfo", {}))
    report.steps.append(_elapsed_step("initialize", start, "serverInfo" in result, detail))
    session.notify_initialized()


def _step_list_tools(session: McpStdioSession, report: RunReport) -> None:
    start = time.perf_counter()
    tools = session.list_tools(HANDSHAKE_TIMEOUT_S).get("result", {}).get("tools", [])
    report.steps.append(_elapsed_step("tools/list", start, bool(tools), f"count={len(tools)}"))


def _tool_outcome(resp: dict[str, Any]) -> tuple[bool, str]:
    if "error" not in resp:
        return True, "ok"
    return False, (resp.get("error", {}) or {}).get("message", "ok")


def _step_call_tool(session: McpStdioSession, report: RunReport, tool: str, arguments: dict[str, Any]) -> None:
    start = time.perf_counter()
    ok, detail = _tool_outcome(session.call_tool(tool, arguments, TOOL_TIMEOUT_S))
    report.steps.append(_elapsed_step(tool, start, ok, detail))


def _run_probes(session: McpStdioSession, report: RunReport, project: str) -> None:
    _step_initialize(session, report)
    _step_list_tools(session, report)
    _step_call_tool(session, report, "get_graph_schema", {"project": project})
    _step_call_tool(session, report, "search_graph", {"project": project, "query": "task", "limit": 1})
    _step_call_tool(session, report, "query_graph", {"project": project, "query": "RETURN 1 AS ok LIMIT 1"})


def timed_session(project: str, label: str, run_index: int) -> RunReport:
    report = RunReport(label=label, project=project, run_index=run_index)
    start = time.perf_counter()
    with cbm_session(poll_interval=POLL_INTERVAL_S, shutdown_timeout=SHUTDOWN_TIMEOUT_S) as session:
        report.steps.append(_elapsed_step("process_start", start, True))
        try:
            _run_probes(session, report, project)
        except Exception as exc:
            report.error = str(exc)
    return report


def _seconds(report: RunReport, name: str) -> float:
    for step in report.steps:
        if step.name == name:
            return step.seconds
    return 0.0


def summarize_report(report: RunReport) -> dict[str, Any]:
    schema_s = _seconds(report, "get_graph_schema")
    query_s = max(_seconds(report, "search_graph"), _seconds(report, "query_graph"))
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
