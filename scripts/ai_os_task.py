#!/usr/bin/env python3
"""Thin AI-OS task checkpoint, gate ledger, and closure helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_os_task_ownership import (
    OWNERSHIP_BASELINE_VERSION,
    OwnershipError,
    assess_ownership,
    capture_ownership_baseline,
    empty_ownership_baseline,
    scope_contains,
)


WORKSPACE = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
ALLOWED_STATUSES = {
    "INITIALIZED",
    "IN_PROGRESS",
    "BLOCKED",
    "READY_TO_CLOSE",
    "CLOSED",
    "ABORTED_WITH_EVIDENCE",
}
ALLOWED_CLASSES = {"SMALL", "MEDIUM", "CRITICAL"}
PASSING_GATE_VERDICTS = {"PASS", "DEDUPLICATED"}
FROZEN_PATHS = {
    "knowledge": {
        "system-atlas/workflows/WORKFLOW_REGISTRY.yaml",
        "system-atlas/workflows/WORKFLOW_EVIDENCE.jsonl",
    }
}
FORBIDDEN_COMMAND_MARKERS = (
    "git push",
    "git reset",
    "git clean",
    "ssh ",
    "scp ",
    "deploy",
    "kubectl ",
)


class TaskError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_dir() -> Path:
    explicit = os.environ.get("AI_OS_TASK_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    scratch = Path(os.environ.get("TOP_CODE_SESSION_SCRATCH", r"C:\top-code-session-scratch"))
    return scratch / "ai-os-execution" / "top-code-workspace"


def checkpoint_path() -> Path:
    return state_dir() / "current-task.json"


def summary_path() -> Path:
    return state_dir() / "last-summary.json"


def run(args: list[str], cwd: Path, check: bool = True, text: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=str(cwd), text=text, capture_output=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise TaskError(f"command failed ({proc.returncode}): {' '.join(args)}\n{detail}")
    return proc


def repo_path(repo: str) -> Path:
    if repo in {".", "root", "workspace"}:
        path = WORKSPACE
    else:
        path = WORKSPACE / repo
    if not path.exists():
        raise TaskError(f"repo path does not exist: {path}")
    if not (path / ".git").exists():
        raise TaskError(f"path is not a git repository root: {path}")
    return path.resolve()


def git_head(repo: str) -> str:
    return run(["git", "rev-parse", "--verify", "HEAD"], repo_path(repo)).stdout.strip()


def git_short_head(repo: str) -> str:
    return git_head(repo)[:7]


def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def parse_scope(values: list[str]) -> list[dict[str, str]]:
    scope: list[dict[str, str]] = []
    for raw in values:
        if ":" not in raw:
            raise TaskError(f"scope must use repo:path form: {raw}")
        repo, rel = raw.split(":", 1)
        repo = repo.strip()
        rel = normalize_rel(rel)
        if not repo or not rel:
            raise TaskError(f"invalid scope: {raw}")
        scope.append({"repo": repo, "path": rel})
    return scope


def scopes_for_repo(scope: list[dict[str, str]], repo: str) -> list[str]:
    paths = [item["path"] for item in scope if item["repo"] == repo]
    return paths or ["."]


def sha256_bytes(parts: list[bytes]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()


def sha256_text(parts: list[str]) -> str:
    return sha256_bytes([part.encode("utf-8", errors="replace") for part in parts])


def git_blob(args: list[str], cwd: Path) -> bytes:
    proc = subprocess.run(args, cwd=str(cwd), capture_output=True)
    if proc.returncode != 0:
        raise TaskError(f"git command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr.decode(errors='replace')}")
    return proc.stdout


def staged_diff_hash(repo: str) -> str:
    path = repo_path(repo)
    return sha256_bytes([git_blob(["git", "diff", "--cached", "--binary"], path)])


def untracked_file_hashes(path: Path, rel_paths: list[str]) -> list[str]:
    status = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *rel_paths], path).stdout.splitlines()
    values: list[str] = []
    for line in status:
        if not line.startswith("?? "):
            continue
        rel = normalize_rel(line[3:])
        full = path / rel
        if full.is_file():
            values.append(f"{rel}:{hashlib.sha256(full.read_bytes()).hexdigest()}")
    return values


def scope_hash(repo: str, rel_paths: list[str]) -> str:
    path = repo_path(repo)
    status = run(["git", "status", "--porcelain", "--untracked-files=all", "--", *rel_paths], path).stdout
    diff = git_blob(["git", "diff", "--binary", "--", *rel_paths], path)
    untracked = "\n".join(sorted(untracked_file_hashes(path, rel_paths)))
    return sha256_bytes([status.encode("utf-8"), diff, untracked.encode("utf-8")])


def config_hash(repo: str, values: list[str]) -> str:
    if not values:
        return sha256_text([""])
    path = repo_path(repo)
    parts: list[bytes] = []
    for raw in values:
        candidate = Path(raw)
        full = candidate if candidate.is_absolute() else path / raw
        if not full.exists():
            parts.append(f"MISSING:{raw}".encode())
        elif full.is_file():
            parts.append(f"FILE:{normalize_rel(raw)}".encode())
            parts.append(full.read_bytes())
        else:
            parts.append(f"DIR:{normalize_rel(raw)}".encode())
    return sha256_bytes(parts)


def validate_checkpoint(data: dict[str, Any]) -> None:
    required = {
        "schema_version": int,
        "task_id": str,
        "task_title": str,
        "task_class": str,
        "workspace_path": str,
        "started_at_utc": str,
        "updated_at_utc": str,
        "status": str,
        "current_phase": str,
        "target_repositories": list,
        "baseline_shas": dict,
        "current_shas": dict,
        "declared_write_scope": list,
        "own_staged_files": list,
        "own_unstaged_files": list,
        "own_untracked_files": list,
        "ownership_baseline": dict,
        "adopted_baseline_scope": list,
        "ownership_conflicts": list,
        "decisions": list,
        "completed_steps": list,
        "gates": list,
        "commits": list,
        "blockers": list,
        "next_action": str,
        "proof_limits": dict,
        "last_summary": str,
    }
    for key, expected in required.items():
        if key not in data:
            raise TaskError(f"checkpoint missing key: {key}")
        if not isinstance(data[key], expected):
            raise TaskError(f"checkpoint key has wrong type: {key}")
    if data["schema_version"] != SCHEMA_VERSION:
        raise TaskError(f"unsupported checkpoint schema_version: {data['schema_version']}")
    if data["status"] not in ALLOWED_STATUSES:
        raise TaskError(f"invalid status: {data['status']}")
    if data["task_class"] not in ALLOWED_CLASSES:
        raise TaskError(f"invalid task_class: {data['task_class']}")
    if data["ownership_baseline"].get("version") != OWNERSHIP_BASELINE_VERSION:
        raise TaskError("unsupported ownership_baseline version")


def migrate_pristine_legacy_checkpoint(data: dict[str, Any]) -> dict[str, Any]:
    activity_keys = (
        "own_staged_files",
        "own_unstaged_files",
        "own_untracked_files",
        "decisions",
        "completed_steps",
        "gates",
        "commits",
        "blockers",
    )
    pristine = (
        data.get("status") == "INITIALIZED"
        and data.get("current_phase") == "task-start"
        and data.get("current_shas") == data.get("baseline_shas")
        and all(not data.get(key) for key in activity_keys)
    )
    if not pristine:
        raise TaskError(
            "legacy checkpoint schema_version 1 has no ownership baseline; "
            "start a new checkpoint (historical state was not modified)"
        )
    migrated = dict(data)
    migrated["schema_version"] = SCHEMA_VERSION
    migrated["ownership_baseline"] = empty_ownership_baseline(data["started_at_utc"])
    migrated["adopted_baseline_scope"] = []
    migrated["ownership_conflicts"] = []
    return migrated


def atomic_write(data: dict[str, Any], path: Path | None = None) -> None:
    validate_checkpoint(data)
    target = path or checkpoint_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    loaded = json.loads(tmp.read_text(encoding="utf-8"))
    validate_checkpoint(loaded)
    os.replace(tmp, target)


def load_checkpoint() -> dict[str, Any]:
    path = checkpoint_path()
    if not path.exists():
        raise TaskError(f"checkpoint not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskError(f"checkpoint is corrupt JSON: {path}: {exc}") from exc
    if data.get("schema_version") == LEGACY_SCHEMA_VERSION:
        data = migrate_pristine_legacy_checkpoint(data)
        atomic_write(data)
    validate_checkpoint(data)
    return data


def refresh_git_fields(data: dict[str, Any]) -> None:
    data["current_shas"] = {repo: git_head(repo) for repo in data["target_repositories"]}
    try:
        ownership = assess_ownership(
            {repo: repo_path(repo) for repo in data["target_repositories"]},
            data["declared_write_scope"],
            data["ownership_baseline"],
            data["adopted_baseline_scope"],
            state_dir(),
        )
    except OwnershipError as exc:
        raise TaskError(str(exc)) from exc
    data["own_staged_files"] = ownership["staged"]
    data["own_unstaged_files"] = ownership["unstaged"]
    data["own_untracked_files"] = ownership["untracked"]
    data["ownership_conflicts"] = ownership["conflicts"]
    data["updated_at_utc"] = utc_now()


def git_mismatches(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for repo, recorded in data["current_shas"].items():
        current = git_head(repo)
        if current != recorded:
            issues.append(f"{repo}: recorded {recorded[:7]}, current {current[:7]}")
    return issues


def print_summary(data: dict[str, Any], prefix: str = "TASK") -> None:
    gates = data["gates"]
    last_gate = gates[-1] if gates else None
    print(f"{prefix}: {data['task_id']} [{data['status']}] {data['current_phase']}")
    print(f"title: {data['task_title']}")
    print(f"class: {data['task_class']}")
    print(f"repos: {', '.join(data['target_repositories'])}")
    print(f"scope: {', '.join(f'{s['repo']}:{s['path']}' for s in data['declared_write_scope'])}")
    if data["commits"]:
        print(f"last_commit: {data['commits'][-1]}")
    if last_gate:
        print(f"last_gate: {last_gate['gate_id']} {last_gate['verdict']}")
    print(f"next: {data['next_action'] or '<none>'}")
    if data["blockers"]:
        print(f"blockers: {len(data['blockers'])}")
    if data["ownership_conflicts"]:
        print(f"ownership_conflicts: {len(data['ownership_conflicts'])}")
    mismatches = git_mismatches(data)
    if mismatches:
        print("git_state_mismatch: " + "; ".join(mismatches))


def new_checkpoint(args: argparse.Namespace) -> int:
    existing = checkpoint_path().exists()
    if existing and not args.replace:
        raise TaskError(f"checkpoint already exists; use task-status/task-resume or --replace: {checkpoint_path()}")
    scope = parse_scope(args.scope)
    adopted = parse_scope(args.adopt_baseline or [])
    for item in adopted:
        if not scope_contains(scope, item):
            raise TaskError(f"adopted baseline path must be inside declared scope: {item['repo']}:{item['path']}")
    repos = args.repo or sorted({item["repo"] for item in scope})
    baseline = {repo: git_head(repo) for repo in repos}
    now = utc_now()
    try:
        ownership_baseline = capture_ownership_baseline(
            {repo: repo_path(repo) for repo in repos},
            scope,
            baseline,
            adopted,
            state_dir(),
            now,
        )
    except OwnershipError as exc:
        raise TaskError(str(exc)) from exc
    data: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": args.task_id,
        "task_title": args.title,
        "task_class": args.task_class,
        "workspace_path": str(WORKSPACE),
        "started_at_utc": now,
        "updated_at_utc": now,
        "status": "INITIALIZED",
        "current_phase": "task-start",
        "target_repositories": repos,
        "baseline_shas": baseline,
        "current_shas": dict(baseline),
        "declared_write_scope": scope,
        "own_staged_files": [],
        "own_unstaged_files": [],
        "own_untracked_files": [],
        "ownership_baseline": ownership_baseline,
        "adopted_baseline_scope": adopted,
        "ownership_conflicts": [],
        "decisions": [],
        "completed_steps": [],
        "gates": [],
        "commits": [],
        "blockers": [],
        "next_action": args.next_action,
        "proof_limits": {
            "checkpoint_json": 1,
            "final_execution_summary": 1,
            "test_logs": 1,
            "extra_logs": "failure-or-critical-runtime-only",
        },
        "last_summary": args.summary,
    }
    refresh_git_fields(data)
    atomic_write(data)
    print_summary(data, "INITIALIZED")
    print(f"checkpoint: {checkpoint_path()}")
    return 0


def update_checkpoint(args: argparse.Namespace) -> int:
    data = load_checkpoint()
    if args.status:
        data["status"] = args.status
    if args.phase:
        data["current_phase"] = args.phase
    if args.next_action is not None:
        data["next_action"] = args.next_action
    if args.summary is not None:
        data["last_summary"] = args.summary
    for value in args.decision or []:
        data["decisions"].append({"timestamp": utc_now(), "text": value})
    for value in args.step or []:
        data["completed_steps"].append({"timestamp": utc_now(), "text": value})
    for value in args.blocker or []:
        data["blockers"].append({"timestamp": utc_now(), "status": "OPEN", "text": value})
    for value in args.resolve_blocker or []:
        for blocker in data["blockers"]:
            if blocker.get("text") == value:
                blocker["status"] = "RESOLVED"
                blocker["resolved_at_utc"] = utc_now()
    for value in args.commit or []:
        if value not in data["commits"]:
            data["commits"].append(value)
    refresh_git_fields(data)
    atomic_write(data)
    print_summary(data, "CHECKPOINT")
    return 0


def gate_fingerprint(args: argparse.Namespace, data: dict[str, Any]) -> dict[str, Any]:
    repo = args.repo
    rel_paths = args.scope or scopes_for_repo(data["declared_write_scope"], repo)
    runtime_identity = args.runtime_id or ""
    if args.runtime_command:
        proc = run(args.runtime_command, repo_path(repo), check=False)
        runtime_identity = (proc.stdout or proc.stderr).strip()
    return {
        "head_sha": git_head(repo),
        "staged_diff_hash": staged_diff_hash(repo),
        "scope_hash": scope_hash(repo, rel_paths),
        "config_hash": config_hash(repo, args.config_path or []),
        "config_paths": [normalize_rel(path) for path in (args.config_path or [])],
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


def run_gate(args: argparse.Namespace) -> int:
    data = load_checkpoint()
    if args.repo not in data["target_repositories"]:
        raise TaskError(f"gate repo is not in checkpoint target_repositories: {args.repo}")
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise TaskError("task-gate requires a command after --")
    forbidden = command_contains_forbidden(command)
    if forbidden:
        raise TaskError(f"refusing forbidden command marker(s): {', '.join(forbidden)}")
    fingerprint = gate_fingerprint(args, data)
    previous = None if args.always_fresh else previous_matching_pass(data, args.gate_id, args.repo, fingerprint)
    start = time.time()
    if previous:
        entry = {
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
        data["gates"].append(entry)
        data["current_phase"] = "gate-deduplicated"
        data["last_summary"] = f"{args.gate_id}: DEDUPLICATED"
        refresh_git_fields(data)
        atomic_write(data)
        print(f"GATE {args.gate_id}: DEDUPLICATED")
        print(entry["short_result"])
        return 0

    print(f"GATE {args.gate_id}: RUN")
    print("command: " + " ".join(command))
    proc = subprocess.run(command, cwd=str(repo_path(args.repo)), text=True, capture_output=True)
    duration = round(time.time() - start, 3)
    output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    verdict = "PASS" if proc.returncode == 0 else "FAIL"
    short = args.summary or summarize_output(output, verdict)
    log_path = ""
    if args.log_path:
        target = Path(args.log_path)
        if not target.is_absolute():
            target = state_dir() / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8", newline="\n")
        log_path = str(target)
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
        "log_path": log_path,
        "short_result": short,
        "limitations": args.limitations or "",
    }
    data["gates"].append(entry)
    data["current_phase"] = "gate-pass" if verdict == "PASS" else "gate-fail"
    data["last_summary"] = f"{args.gate_id}: {verdict} - {short}"
    refresh_git_fields(data)
    atomic_write(data)
    print(f"GATE {args.gate_id}: {verdict} ({duration}s)")
    print(f"summary: {short}")
    if proc.returncode != 0:
        tail = "\n".join(output.splitlines()[-40:])
        if tail:
            print(tail)
    return proc.returncode


def summarize_output(output: str, verdict: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return verdict
    return lines[-1][:500]


def closure_issues(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if data["status"] != "READY_TO_CLOSE":
        issues.append(f"status must be READY_TO_CLOSE, got {data['status']}")
    if not data["declared_write_scope"]:
        issues.append("declared_write_scope is empty")
    refresh_git_fields(data)
    if data["own_staged_files"]:
        issues.append("own staged files remain: " + ", ".join(data["own_staged_files"]))
    if data["own_unstaged_files"]:
        issues.append("own unstaged files remain: " + ", ".join(data["own_unstaged_files"]))
    if data["own_untracked_files"]:
        issues.append("own untracked files remain: " + ", ".join(data["own_untracked_files"]))
    if data["ownership_conflicts"]:
        issues.extend(data["ownership_conflicts"])
    if not data["commits"]:
        issues.append("no created commits recorded")
    for commit in data["commits"]:
        repo = commit.split(":", 1)[0] if ":" in commit else data["target_repositories"][0]
        sha = commit.split(":", 1)[1] if ":" in commit else commit
        proc = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(repo_path(repo)), capture_output=True)
        if proc.returncode != 0:
            issues.append(f"declared commit does not exist: {commit}")
    if not data["gates"]:
        issues.append("no gates recorded")
    latest_by_gate: dict[str, dict[str, Any]] = {}
    for gate in data["gates"]:
        latest_by_gate[gate["gate_id"]] = gate
        command = str(gate.get("command", "")).lower()
        for marker in FORBIDDEN_COMMAND_MARKERS:
            if marker in command:
                issues.append(f"forbidden operation marker recorded in gate {gate['gate_id']}: {marker}")
    for gate_id, gate in latest_by_gate.items():
        if gate["verdict"] not in PASSING_GATE_VERDICTS:
            issues.append(f"latest gate is not PASS/DEDUPLICATED: {gate_id}={gate['verdict']}")
            continue
        current_fp = recompute_gate_fingerprint_from_entry(gate)
        if current_fp != gate.get("fingerprint"):
            issues.append(f"gate fingerprint is stale: {gate_id}")
    open_blockers = [b for b in data["blockers"] if b.get("status") not in {"RESOLVED", "DEFERRED_WITH_EVIDENCE", "ACCEPTED"}]
    if open_blockers:
        issues.append(f"open blockers remain: {len(open_blockers)}")
    if data["next_action"]:
        issues.append("next_action must be empty for full close")
    for repo, frozen in FROZEN_PATHS.items():
        if repo not in data["target_repositories"]:
            continue
        changed = run(["git", "status", "--porcelain", "--", *sorted(frozen)], repo_path(repo)).stdout.strip()
        if changed:
            issues.append(f"frozen paths changed in {repo}")
    return issues


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


def close_task(args: argparse.Namespace) -> int:
    data = load_checkpoint()
    issues = closure_issues(data)
    payload = {
        "ok": not issues,
        "verdict": "PASS" if not issues else "FAIL",
        "task_id": data["task_id"],
        "issues": issues,
        "checkpoint": str(checkpoint_path()),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"CLOSURE: {payload['verdict']}")
        for issue in issues:
            print(f"- {issue}")
    if issues:
        atomic_write(data)
        return 1
    if not args.validate_only:
        data["status"] = "CLOSED"
        data["current_phase"] = "closed"
        data["updated_at_utc"] = utc_now()
        data["last_summary"] = args.summary or "Task closed by package closure validator."
        atomic_write(data)
        final = {
            "task_id": data["task_id"],
            "closed_at_utc": data["updated_at_utc"],
            "commits": data["commits"],
            "gates": [
                {"gate_id": gate["gate_id"], "repo": gate["repo"], "verdict": gate["verdict"], "timestamp": gate["timestamp"]}
                for gate in data["gates"]
            ],
            "summary": data["last_summary"],
        }
        target = Path(args.summary_file) if args.summary_file else summary_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"summary_file: {target}")
    return 0


def status_task(args: argparse.Namespace) -> int:
    data = load_checkpoint()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print_summary(data, "STATUS")
        print(f"checkpoint: {checkpoint_path()}")
    return 0


def resume_task(args: argparse.Namespace) -> int:
    data = load_checkpoint()
    print_summary(data, "RESUME")
    return 0


def remove_state(args: argparse.Namespace) -> int:
    path = checkpoint_path()
    if path.exists():
        backup = path.with_name(f"{path.stem}.closed-{int(time.time())}.json")
        if args.archive:
            shutil.copy2(path, backup)
            print(f"archived: {backup}")
        path.unlink()
        print(f"removed: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-OS Codex execution task checkpoint helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("task-start")
    start.add_argument("--task-id", required=True)
    start.add_argument("--title", required=True)
    start.add_argument("--class", dest="task_class", choices=sorted(ALLOWED_CLASSES), required=True)
    start.add_argument("--repo", action="append")
    start.add_argument("--scope", action="append", required=True, help="repo:path")
    start.add_argument(
        "--adopt-baseline",
        action="append",
        help="repo:path already dirty at task start that this task is explicitly authorized to own",
    )
    start.add_argument("--next", dest="next_action", default="")
    start.add_argument("--summary", default="")
    start.add_argument("--replace", action="store_true")
    start.set_defaults(func=new_checkpoint)

    status = sub.add_parser("task-status")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=status_task)

    resume = sub.add_parser("task-resume")
    resume.set_defaults(func=resume_task)

    checkpoint = sub.add_parser("task-checkpoint")
    checkpoint.add_argument("--status", choices=sorted(ALLOWED_STATUSES))
    checkpoint.add_argument("--phase")
    checkpoint.add_argument("--next", dest="next_action")
    checkpoint.add_argument("--summary")
    checkpoint.add_argument("--decision", action="append")
    checkpoint.add_argument("--step", action="append")
    checkpoint.add_argument("--blocker", action="append")
    checkpoint.add_argument("--resolve-blocker", action="append")
    checkpoint.add_argument("--commit", action="append", help="repo:sha or sha")
    checkpoint.set_defaults(func=update_checkpoint)

    gate = sub.add_parser("task-gate")
    gate.add_argument("--gate-id", required=True)
    gate.add_argument("--repo", required=True)
    gate.add_argument("--scope", action="append")
    gate.add_argument("--config-path", action="append")
    gate.add_argument("--runtime-id")
    gate.add_argument("--runtime-command", nargs="+")
    gate.add_argument("--always-fresh", action="store_true")
    gate.add_argument("--summary")
    gate.add_argument("--limitations")
    gate.add_argument("--log-path")
    gate.add_argument("command", nargs=argparse.REMAINDER)
    gate.set_defaults(func=run_gate)

    close = sub.add_parser("task-close")
    close.add_argument("--validate-only", action="store_true")
    close.add_argument("--json", action="store_true")
    close.add_argument("--summary")
    close.add_argument("--summary-file")
    close.set_defaults(func=close_task)

    cleanup = sub.add_parser("task-cleanup")
    cleanup.add_argument("--archive", action="store_true")
    cleanup.set_defaults(func=remove_state)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except TaskError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
