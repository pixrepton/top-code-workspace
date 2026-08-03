from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_os_task_constants import FORBIDDEN_COMMAND_MARKERS, PASSING_GATE_VERDICTS
from ai_os_task_errors import TaskError
from ai_os_task_git import config_hash, git_head, repo_path, run, scope_hash, staged_diff_hash
from ai_os_task_paths import state_dir, utc_now
from ai_os_task_scope import normalize_rel, scopes_for_repo
from ai_os_task_state import atomic_write, load_checkpoint, refresh_git_fields

def _runtime_identity(args: argparse.Namespace) -> str:
    if not args.runtime_command:
        return args.runtime_id or ""
    proc = run(args.runtime_command, repo_path(args.repo), check=False)
    return (proc.stdout or proc.stderr).strip()

def gate_fingerprint(args: argparse.Namespace, data: dict[str, Any]) -> dict[str, Any]:
    repo = args.repo
    rel_paths = args.scope or scopes_for_repo(data["declared_write_scope"], repo)
    config_paths = args.config_path or []
    runtime_identity = _runtime_identity(args)
    return {
        "head_sha": git_head(repo),
        "staged_diff_hash": staged_diff_hash(repo),
        "scope_hash": scope_hash(repo, rel_paths),
        "config_hash": config_hash(repo, config_paths),
        "config_paths": [normalize_rel(path) for path in config_paths],
        "runtime_identity": runtime_identity,
        "scope": [normalize_rel(p) for p in rel_paths],
    }

def previous_matching_pass(data: dict[str, Any], gate_id: str, repo: str, fingerprint: dict[str, Any]) -> dict[str, Any] | None:
    for entry in reversed(data["gates"]):
        if entry.get("gate_id") != gate_id or entry.get("repo") != repo:
            continue
        if entry.get("verdict") != "PASS":
            continue
        if entry.get("fingerprint") == fingerprint:
            return entry
    return None

def command_contains_forbidden(command: list[str]) -> list[str]:
    rendered = " ".join(command).lower()
    return [marker for marker in FORBIDDEN_COMMAND_MARKERS if marker in rendered]

def _resolve_gate_command(args: argparse.Namespace) -> list[str]:
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise TaskError("task-gate requires a command after --")
    forbidden = command_contains_forbidden(command)
    if forbidden:
        raise TaskError(f"refusing forbidden command marker(s): {', '.join(forbidden)}")
    return command

def _record_gate(data: dict[str, Any], entry: dict[str, Any], phase: str, summary: str) -> None:
    data["gates"].append(entry)
    data["current_phase"] = phase
    data["last_summary"] = summary
    refresh_git_fields(data)
    atomic_write(data)

def _deduplicated_entry(
    args: argparse.Namespace,
    command: list[str],
    fingerprint: dict[str, Any],
    previous: dict[str, Any],
) -> dict[str, Any]:
    return {
        "gate_id": args.gate_id,
        "repo": args.repo,
        "command": " ".join(command),
        "working_directory": str(repo_path(args.repo)),
        "timestamp": utc_now(),
        "exit_code": 0,
        "verdict": "DEDUPLICATED",
        "duration_seconds": 0.0,
        "fingerprint": fingerprint,
        "log_path": "",
        "short_result": f"deduplicated from {previous['timestamp']}",
        "limitations": "Skipped because previous PASS has identical HEAD, staged diff, scope, config, and runtime identity.",
        "deduplicated_from": previous["timestamp"],
    }

def _write_gate_log(log_path: str | None, output: str) -> str:
    if not log_path:
        return ""
    target = Path(log_path)
    if not target.is_absolute():
        target = state_dir() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8", newline="\n")
    return str(target)

def _gate_output(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")

def _print_failure_tail(output: str) -> None:
    tail = "\n".join(output.splitlines()[-40:])
    if tail:
        print(tail)

def _execute_gate(
    args: argparse.Namespace,
    data: dict[str, Any],
    command: list[str],
    fingerprint: dict[str, Any],
) -> int:
    print(f"GATE {args.gate_id}: RUN")
    print("command: " + " ".join(command))
    start = time.time()
    proc = subprocess.run(command, cwd=str(repo_path(args.repo)), text=True, capture_output=True)
    duration = round(time.time() - start, 3)
    output = _gate_output(proc)
    verdict = "PASS" if proc.returncode == 0 else "FAIL"
    short = args.summary or summarize_output(output, verdict)
    entry = {
        "gate_id": args.gate_id,
        "repo": args.repo,
        "command": " ".join(command),
        "working_directory": str(repo_path(args.repo)),
        "timestamp": utc_now(),
        "exit_code": proc.returncode,
        "verdict": verdict,
        "duration_seconds": duration,
        "fingerprint": fingerprint,
        "log_path": _write_gate_log(args.log_path, output),
        "short_result": short,
        "limitations": args.limitations or "",
    }
    phase = "gate-pass" if verdict == "PASS" else "gate-fail"
    _record_gate(data, entry, phase, f"{args.gate_id}: {verdict} - {short}")
    print(f"GATE {args.gate_id}: {verdict} ({duration}s)")
    print(f"summary: {short}")
    if proc.returncode != 0:
        _print_failure_tail(output)
    return proc.returncode

def run_gate(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    if args.repo not in data["target_repositories"]:
        raise TaskError(f"gate repo is not in checkpoint target_repositories: {args.repo}")
    command = _resolve_gate_command(args)
    fingerprint = gate_fingerprint(args, data)
    previous = None if args.always_fresh else previous_matching_pass(data, args.gate_id, args.repo, fingerprint)
    if not previous:
        return _execute_gate(args, data, command, fingerprint)
    entry = _deduplicated_entry(args, command, fingerprint, previous)
    _record_gate(data, entry, "gate-deduplicated", f"{args.gate_id}: DEDUPLICATED")
    print(f"GATE {args.gate_id}: DEDUPLICATED")
    print(entry["short_result"])
    return 0

def summarize_output(output: str, verdict: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return verdict
    return lines[-1][:500]

def open_blockers(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        blocker
        for blocker in data["blockers"]
        if blocker.get("status") not in {"RESOLVED", "DEFERRED_WITH_EVIDENCE", "ACCEPTED"}
    ]

def latest_current_passing_gate(data: dict[str, Any], repo: str) -> dict[str, Any] | None:
    for gate in reversed(data.get("gates", [])):
        if gate.get("repo") != repo or gate.get("verdict") not in PASSING_GATE_VERDICTS:
            continue
        try:
            if recompute_gate_fingerprint_from_entry(gate) == gate.get("fingerprint"):
                return gate
        except TaskError:
            continue
    return None

def recompute_gate_fingerprint_from_entry(gate: dict[str, Any]) -> dict[str, Any]:
    fp = gate["fingerprint"]
    repo = gate["repo"]
    return {
        "head_sha": git_head(repo),
        "staged_diff_hash": staged_diff_hash(repo),
        "scope_hash": scope_hash(repo, fp.get("scope") or ["."]),
        "config_hash": config_hash(repo, fp.get("config_paths") or []),
        "config_paths": fp.get("config_paths") or [],
        "runtime_identity": fp.get("runtime_identity", ""),
        "scope": fp.get("scope") or ["."],
    }
