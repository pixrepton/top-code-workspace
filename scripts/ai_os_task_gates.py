from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
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
from ai_os_task_paths import sanitize_task_id, state_dir, utc_now
from ai_os_task_scope import normalize_rel, scopes_for_repo
from ai_os_task_state import atomic_write, load_checkpoint, mutate_active_checkpoint, refresh_git_fields

def _runtime_identity(args: argparse.Namespace) -> str:
    if not args.runtime_command:
        return args.runtime_id or ""
    proc = run(args.runtime_command, repo_path(args.repo), check=False)
    return (proc.stdout or proc.stderr).strip()

def gate_fingerprint(args: argparse.Namespace, data: dict[str, Any], command: list[str] | None = None) -> dict[str, Any]:
    repo = args.repo
    rel_paths = args.scope or scopes_for_repo(data["declared_write_scope"], repo)
    config_paths = args.config_path or []
    runtime_identity = _runtime_identity(args)
    v1 = {
        "head_sha": git_head(repo),
        "staged_diff_hash": staged_diff_hash(repo),
        "scope_hash": scope_hash(repo, rel_paths),
        "config_hash": config_hash(repo, config_paths),
        "config_paths": [normalize_rel(path) for path in config_paths],
        "runtime_identity": runtime_identity,
        "scope": [normalize_rel(p) for p in rel_paths],
    }
    if not data.get("execution_id"):
        return v1
    from ai_os_execution.bundle import load_bundle_for_task
    from ai_os_execution.proof import build_fingerprint_v2

    bundle = load_bundle_for_task(data["task_id"]) or {}
    db = bundle.get("database") or {}
    runtime = bundle.get("runtime") or {}
    digest_entry = (runtime.get("image_digests") or {}).get(repo) or {}
    if isinstance(digest_entry, str):
        digest_entry = {"digest": digest_entry}
    gate_class = "FINAL_HEAD" if args.gate_id == "FINAL_HEAD_GATE" or getattr(args, "final_head", False) else "DEVELOPMENT"
    argv = list(command or getattr(args, "command", None) or [])
    return build_fingerprint_v2(
        task_id=data["task_id"],
        repo=repo,
        command=argv,
        rel_paths=rel_paths,
        config_hash_value=v1["config_hash"],
        config_paths=config_paths,
        runtime_identity=runtime_identity,
        staged=v1["staged_diff_hash"],
        execution_id=str(data.get("execution_id") or ""),
        environment_manifest_hash=str(bundle.get("environment_manifest_hash") or ""),
        image_digest=str(digest_entry.get("digest") or ""),
        db_seed_identity=str(db.get("seed_identity") or ""),
        db_seed_hash=str(db.get("seed_hash") or ""),
        benchmark_manifest_hash=str((bundle.get("benchmark") or {}).get("manifest_hash") or ""),
        scorer_hash=str((bundle.get("benchmark") or {}).get("scorer_hash") or ""),
        gate_class=gate_class,
        target_repositories=list(data.get("target_repositories") or [repo]),
    )

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
    def _mutate(latest: dict[str, Any]) -> None:
        latest["gates"].append(entry)
        latest["current_phase"] = phase
        latest["last_summary"] = summary

    mutate_active_checkpoint(data["task_id"], _mutate)

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
        "command_argv": list(command),
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


def _default_gate_log_path(task_id: str, gate_id: str) -> str:
    """Always-on structured gate log artifact under the task state dir."""
    directory = state_dir() / "gate-logs" / sanitize_task_id(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / f"{gate_id}-{utc_now().replace(':', '-')}.log")


def _gate_env() -> dict[str, str]:
    """Deterministic UTF-8 environment for gate subprocesses.

    The workspace encoding contract is UTF-8; without this, Windows subprocess
    text mode follows the locale (cp1250) and Polish pytest output in gate logs
    becomes non-deterministic. User-set values are preserved.
    """
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONLEGACYWINDOWSSTDIO", "0")
    # Parent CLI sets AI_OS_TASK_ID for fingerprint/worktree routing.
    # Nested task-engine tests must not inherit the live parent task identity.
    env.pop("AI_OS_TASK_ID", None)
    return env


def _terminate_owned_process_tree(proc: subprocess.Popen[Any]) -> None:
    """Terminate ONLY the process tree spawned by this gate.

    Ownership-safe: the target pid is the direct child this runner created;
    user/foreign processes are never touched. On Windows, taskkill /T scopes
    termination to that spawned tree. On POSIX, the child is its own process
    group (start_new_session=True), so killpg touches only that group.
    """
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


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
    gate_timeout = int(getattr(args, "timeout", 0) or 0)
    creationflags = 0
    start_new_session = False
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        start_new_session = True
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(repo_path(args.repo)),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_gate_env(),
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        stdout, stderr = proc.communicate(timeout=gate_timeout if gate_timeout else None)
        timed_out = False
    except subprocess.TimeoutExpired:
        _terminate_owned_process_tree(proc)
        stdout, stderr = proc.communicate()
        timed_out = True
    duration = round(time.time() - start, 3)
    output = (stdout or "") + (("\n" + stderr) if stderr else "")
    if timed_out:
        verdict = "TIMEOUT"
        exit_code: int | None = proc.returncode
    else:
        verdict = "PASS" if proc.returncode == 0 else "FAIL"
        exit_code = proc.returncode
    short = args.summary or summarize_output(output, verdict)
    log_path = args.log_path or _default_gate_log_path(data["task_id"], args.gate_id)
    entry = {
        "gate_id": args.gate_id,
        "repo": args.repo,
        "command": " ".join(command),
        "command_argv": list(command),
        "working_directory": str(repo_path(args.repo)),
        "timestamp": utc_now(),
        "exit_code": exit_code,
        "verdict": verdict,
        "duration_seconds": duration,
        "fingerprint": fingerprint,
        "log_path": _write_gate_log(log_path, output),
        "short_result": short,
        "limitations": args.limitations or "",
        "diagnostics": (
            {
                "failure_kind": "TIMEOUT",
                "hung": True,
                "gate_timeout_seconds": gate_timeout,
                "terminated": True,
                "termination_target": f"spawned_pid={proc.pid}",
                "partial_output_tail": "\n".join(output.splitlines()[-40:]),
            }
            if timed_out
            else None
        ),
    }
    phase = "gate-pass" if verdict == "PASS" else "gate-fail"
    _record_gate(data, entry, phase, f"{args.gate_id}: {verdict} - {short}")
    if verdict == "PASS" and data.get("execution_id"):
        _record_execution_proof(data, entry)
    print(f"GATE {args.gate_id}: {verdict} ({duration}s)")
    print(f"summary: {short}")
    print(f"log: {log_path}")
    if verdict != "PASS":
        if timed_out:
            print(f"HUNG_TEST: gate exceeded {gate_timeout}s; owned process tree {proc.pid} terminated")
        _print_failure_tail(output)
    return 1 if timed_out else (0 if verdict == "PASS" else 1)

def run_gate(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    if args.repo not in data["target_repositories"]:
        raise TaskError(f"gate repo is not in checkpoint target_repositories: {args.repo}")
    profile = getattr(args, "profile", None)
    raw_command = getattr(args, "command", None)
    if profile and raw_command:
        raise TaskError("task-gate: --profile and a raw command are mutually exclusive")
    if profile:
        from ai_os_task_profiles import resolve_profile

        resolved = resolve_profile(args.repo, profile)
        command = resolved.command()
        forbidden = command_contains_forbidden(command)
        if forbidden:
            raise TaskError(f"refusing profile with forbidden command marker(s): {', '.join(forbidden)}")
        if not getattr(args, "timeout", 0):
            args.timeout = resolved.gate_timeout
        if not args.summary:
            args.summary = resolved.description
    else:
        command = _resolve_gate_command(args)
    fingerprint = gate_fingerprint(args, data, command)
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
    if int(fp.get("fingerprint_version") or 1) < 2:
        return {
            "head_sha": git_head(repo),
            "staged_diff_hash": staged_diff_hash(repo),
            "scope_hash": scope_hash(repo, fp.get("scope") or ["."]),
            "config_hash": config_hash(repo, fp.get("config_paths") or []),
            "config_paths": fp.get("config_paths") or [],
            "runtime_identity": fp.get("runtime_identity", ""),
            "scope": fp.get("scope") or ["."],
        }
    args = argparse.Namespace(
        repo=repo,
        scope=fp.get("scope") or ["."],
        config_path=fp.get("config_paths") or [],
        runtime_id=fp.get("runtime_identity") or "",
        runtime_command=None,
        gate_id=gate.get("gate_id") or "",
        final_head=fp.get("gate_class") == "FINAL_HEAD",
        command=list(gate.get("command_argv") or []),
    )
    from ai_os_task_state import load_checkpoint

    data = load_checkpoint(fp.get("task_id"))
    return gate_fingerprint(args, data, list(gate.get("command_argv") or []))


def _record_execution_proof(data: dict[str, Any], entry: dict[str, Any]) -> None:
    from ai_os_execution.bundle import load_bundle_for_task, save_bundle
    from ai_os_execution.proof import write_proof_bundle

    bundle = load_bundle_for_task(data["task_id"])
    if not bundle:
        return
    repos = {name: item.get("current_sha") or git_head(name) for name, item in (bundle.get("repos") or {}).items()}
    path = write_proof_bundle(
        task_id=data["task_id"],
        execution_id=bundle["execution_id"],
        repos=repos,
        gate=entry,
        verdict=entry.get("verdict") or "PASS",
        runtime=bundle.get("runtime") or {},
        database={
            "seed_identity": (bundle.get("database") or {}).get("seed_identity"),
            "seed_hash": (bundle.get("database") or {}).get("seed_hash"),
        },
        benchmark=bundle.get("benchmark") or {},
        environment_manifest_hash=str(bundle.get("environment_manifest_hash") or ""),
        artifacts={"log_path": entry.get("log_path") or ""},
    )
    bundle["proof"] = {"latest_proof_bundle": str(path)}
    if entry.get("gate_id") == "FINAL_HEAD_GATE" or (entry.get("fingerprint") or {}).get("gate_class") == "FINAL_HEAD":
        bundle["final_head"] = {
            **(bundle.get("final_head") or {}),
            "required": True,
            "valid": True,
            "gate_id": "FINAL_HEAD_GATE",
            "invalidated_reason": "",
        }
    save_bundle(bundle)
