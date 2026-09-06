#!/usr/bin/env python3
"""Compact SessionStart summary rendered from an AI-OS checkpoint."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai_os_hook_common import clip  # noqa: E402


SUMMARY_CHAR_LIMIT = 850
CLOSED_BLOCKER_STATUSES = {"RESOLVED", "DEFERRED_WITH_EVIDENCE", "ACCEPTED"}
ROOT = Path(__file__).resolve().parents[1]
TOOLING_PROOF_ROOT = ROOT / ".artifacts" / "tooling-optimization"
TOOLING_PROOF_STALE_HOURS = 24


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


def latest_tooling_proof() -> Path | None:
    if not TOOLING_PROOF_ROOT.exists():
        return None
    candidates = sorted(TOOLING_PROOF_ROOT.glob("*/mcp-proof.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def format_tooling_proof() -> str:
    proof = latest_tooling_proof()
    if proof is None:
        return "missing"
    age_seconds = max(0.0, datetime.now(timezone.utc).timestamp() - proof.stat().st_mtime)
    age_hours = age_seconds / 3600
    status = "stale" if age_hours > TOOLING_PROOF_STALE_HOURS else "fresh"
    rel = proof.relative_to(ROOT).as_posix()
    try:
        summary = json.loads(proof.read_text(encoding="utf-8")).get("summary") or {}
    except (OSError, json.JSONDecodeError):
        summary = {"artifact": "unreadable"}
    rendered = ",".join(f"{key}={value}" for key, value in sorted(summary.items()))
    suffix = f" {rendered}" if rendered else ""
    return f"{status} age_h={age_hours:.1f} path={rel}{suffix}"


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
        f"tooling_proof: {format_tooling_proof()}",
    ]
    return clip("\n".join(lines), SUMMARY_CHAR_LIMIT)
