#!/usr/bin/env python3
"""Compact SessionStart summary rendered from an AI-OS checkpoint."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_hook_common import clip  # noqa: E402


SUMMARY_CHAR_LIMIT = 700
CLOSED_BLOCKER_STATUSES = {"RESOLVED", "DEFERRED_WITH_EVIDENCE", "ACCEPTED"}


def format_scope(data: dict[str, Any]) -> str:
    scope = data.get("declared_write_scope") or []
    rendered = [f"{item['repo']}:{item['path']}" for item in scope[:3] if "repo" in item and "path" in item]
    if len(scope) > 3:
        rendered.append(f"+{len(scope) - 3} more")
    return ", ".join(rendered) if rendered else "<none>"


def format_last_gate(data: dict[str, Any]) -> str:
    gates = data.get("gates") or []
    if not gates:
        return "<none>"
    gate = gates[-1]
    return f"{gate.get('gate_id', '?')} {gate.get('verdict', '?')}"


def format_last_commit(data: dict[str, Any]) -> str:
    commits = data.get("commits") or []
    if not commits:
        return "<none>"
    return str(commits[-1]).split(":")[-1][:7]


def format_blockers(data: dict[str, Any]) -> str:
    blockers = data.get("blockers") or []
    open_count = sum(1 for blocker in blockers if blocker.get("status") not in CLOSED_BLOCKER_STATUSES)
    return str(open_count)


def build_session_summary(data: dict[str, Any]) -> str:
    lines = [
        f"task: {data.get('task_id', '<unknown>')}",
        f"status: {data.get('status', '<unknown>')}",
        f"phase: {data.get('current_phase', '<unknown>')}",
        f"commit: {format_last_commit(data)}",
        f"scope: {format_scope(data)}",
        f"gate: {format_last_gate(data)}",
        f"next: {clip(str(data.get('next_action') or '<none>'), 160)}",
        f"blockers_open: {format_blockers(data)}",
    ]
    return clip("\n".join(lines), SUMMARY_CHAR_LIMIT)
