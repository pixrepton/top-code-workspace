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

from ai_os_task_constants import (
    FORBIDDEN_COMMAND_MARKERS,
    FROZEN_PATHS,
    NESTED_PRODUCT_REPO_DIRS,
    PASSING_GATE_VERDICTS,
    SECRET_CONTENT_PATTERNS,
    SECRET_PATH_PATTERNS,
)
from ai_os_task_errors import TaskError
from ai_os_task_gates import (
    latest_current_passing_gate,
    open_blockers,
    recompute_gate_fingerprint_from_entry,
)
from ai_os_task_git import (
    branch_is_protected,
    git_branch,
    git_head,
    git_operation_in_progress,
    repo_path,
    run,
)
from ai_os_task_locks import RepoCommitLock
from ai_os_task_ownership import OwnershipError, collect_raw_git_state, prepare_owned_commit_states, scope_contains
from ai_os_task_paths import state_dir, utc_now
from ai_os_task_scope import normalize_rel
from ai_os_task_commit_decision import evaluate_commit_decision, print_commit_decision
from ai_os_task_state import atomic_write, load_checkpoint, refresh_git_fields, resolve_task_id

CommitStates = dict[str, dict[str, tuple[str, bytes | None]]]

def owned_paths_for_repo(data: dict[str, Any], repo: str) -> list[str]:
    prefix = f"{repo}:"
    values: set[str] = set()
    for key in ("own_staged_files", "own_unstaged_files", "own_untracked_files"):
        for item in data.get(key, []):
            if item.startswith(prefix):
                values.add(normalize_rel(item[len(prefix) :]))
    return sorted(values)

def nested_product_path_issue(repo: str, rel_path: str) -> str:
    """Block staging nested product repo files through workspace-root Git."""
    if repo not in {".", "root", "workspace"}:
        return ""
    normalized = normalize_rel(rel_path)
    if not normalized:
        return ""
    top = normalized.split("/", 1)[0]
    if top in NESTED_PRODUCT_REPO_DIRS:
        return (
            f"nested product repo path forbidden from workspace commit: {normalized} "
            f"(use task-commit --repo {top})"
        )
    return ""

def _secret_path_issue(path: str) -> str:
    normalized = normalize_rel(path)
    if normalized.lower().endswith((".env.example", ".env.sample", ".env.template")):
        return ""
    name = Path(normalized).name.lower()
    if name.startswith(".env.") and name.endswith(".example"):
        return ""
    for pattern in SECRET_PATH_PATTERNS:
        if pattern.search(normalized):
            return f"sensitive path: {normalized}"
    return ""

def _secret_content_issues(path: str, state: tuple[str, bytes | None]) -> list[str]:
    kind, content = state
    if kind not in {"file", "symlink"}:
        return []
    if content is None:
        return []
    return [
        f"{path}: detected {label}"
        for label, pattern in SECRET_CONTENT_PATTERNS
        if pattern.search(content)
    ]

def scan_commit_states_for_secrets(states: CommitStates) -> list[str]:
    issues: list[str] = []
    for path, payload in states.items():
        issues.extend(_secret_content_issues(path, payload["commit"]))
        path_issue = _secret_path_issue(path)
        if path_issue:
            issues.append(path_issue)
    return sorted(set(issues))

def _repo_state_reasons(data: dict[str, Any], repo: str) -> list[str]:
    reasons: list[str] = []
    branch = data["current_branches"].get(repo, "")
    operation = git_operation_in_progress(repo)
    if operation:
        reasons.append(f"git operation in progress: {operation}")
    if not branch:
        reasons.append("detached HEAD is not allowed for task commits")
    elif branch_is_protected(repo, branch):
        reasons.append(f"current branch is protected/default: {branch}; run task-branch first")
    if data["status"] == "BLOCKED":
        reasons.append("task status is BLOCKED")
    blockers = open_blockers(data)
    if blockers:
        reasons.append(f"open blockers remain: {len(blockers)}")
    return reasons

def _planned_commit_states(data: dict[str, Any], repo: str, owned_paths: list[str]) -> tuple[CommitStates, list[str]]:
    reasons: list[str] = []
    if owned_paths and latest_current_passing_gate(data, repo) is None:
        reasons.append("no current PASS/DEDUPLICATED gate matches the present repo state")
    try:
        states = prepare_owned_commit_states(
            repo,
            repo_path(repo),
            owned_paths,
            data["ownership_baseline"],
            data["adopted_baseline_scope"],
            state_dir(),
        )
    except OwnershipError as exc:
        return {}, [*reasons, str(exc)]
    return states, reasons

def _ownership_conflict_findings(
    data: dict[str, Any],
    repo: str,
    owned_paths: list[str],
    isolated: bool,
) -> tuple[list[str], list[str]]:
    """Split baseline conflicts into soft warnings the wrapper can isolate and hard reasons."""
    owned_keys = {f"{repo}:{path}" for path in owned_paths}
    warnings: list[str] = []
    reasons: list[str] = []
    for conflict in data["ownership_conflicts"]:
        key = conflict.split(": OWNERSHIP_", 1)[0]
        if isolated and key in owned_keys:
            warnings.append(
                f"mixed baseline state isolated by commit wrapper (soft ownership conflict; "
                f"commit proceeds with task-only delta): {key}"
            )
        else:
            reasons.append(conflict)
    return warnings, reasons

def _foreign_staged_warning(data: dict[str, Any], repo: str) -> str:
    all_staged = collect_raw_git_state(repo_path(repo), ["."])["staged"]
    owned_staged = {
        normalize_rel(item.split(":", 1)[1])
        for item in data.get("own_staged_files", [])
        if item.startswith(f"{repo}:")
    }
    foreign_staged = sorted(all_staged - owned_staged)
    if not foreign_staged:
        return ""
    return (
        "foreign staged paths will be preserved through an isolated temporary index: "
        + ", ".join(foreign_staged)
    )

def _owned_commit_findings(data: dict[str, Any], repo: str, owned_paths: list[str]) -> tuple[list[str], list[str]]:
    """Blocking reasons and non-blocking warnings for a repo that carries task-owned paths."""
    states, reasons = _planned_commit_states(data, repo, owned_paths)
    conflict_warnings, conflict_reasons = _ownership_conflict_findings(data, repo, owned_paths, bool(states))
    reasons.extend(conflict_reasons)
    reasons.extend(scan_commit_states_for_secrets(states))
    for owned_path in owned_paths:
        nested_issue = nested_product_path_issue(repo, owned_path)
        if nested_issue:
            reasons.append(nested_issue)
    warnings = list(conflict_warnings)
    foreign_staged = _foreign_staged_warning(data, repo)
    if foreign_staged:
        warnings.append(foreign_staged)
    return reasons, warnings

def _record_commit_evaluation(data: dict[str, Any], payload: dict[str, Any]) -> None:
    data["commit_evaluations"].append({"timestamp": utc_now(), **payload})
    data["commit_evaluations"] = data["commit_evaluations"][-20:]
    data["last_summary"] = f"commit-plan {payload['repo']}: {payload['verdict']}"
    atomic_write(data)

def commit_plan_payload(data: dict[str, Any], repo: str) -> dict[str, Any]:
    if repo not in data["target_repositories"]:
        raise TaskError(f"commit repo is not in checkpoint target_repositories: {repo}")
    refresh_git_fields(data)
    reasons = _repo_state_reasons(data, repo)
    owned_paths = owned_paths_for_repo(data, repo)
    warnings: list[str] = []
    if not owned_paths and not reasons:
        verdict = "NO_COMMIT"
    else:
        owned_reasons, warnings = _owned_commit_findings(data, repo, owned_paths)
        reasons.extend(owned_reasons)
        verdict = "BLOCKED" if reasons else "COMMIT_READY"
    payload = {
        "verdict": verdict,
        "task_id": data["task_id"],
        "repo": repo,
        "branch": data["current_branches"].get(repo, ""),
        "publication_mode": data["publication_mode"],
        "owned_paths": owned_paths,
        "reasons": reasons,
        "warnings": warnings,
        "suggested_message": f"chore({data['task_id']}): {data['task_title']}"[:100],
    }
    payload["decision"] = evaluate_commit_decision(data, repo, payload)
    _record_commit_evaluation(data, payload)
    return payload

def print_commit_plan(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"COMMIT PLAN: {payload['verdict']}")
    print(f"repo: {payload['repo']}")
    print(f"branch: {payload['branch'] or '<detached>'}")
    print(f"publication: {payload['publication_mode']}")
    if payload["owned_paths"]:
        print("paths: " + ", ".join(payload["owned_paths"]))
    for warning in payload["warnings"]:
        print(f"warning: {warning}")
    for reason in payload["reasons"]:
        print(f"blocked: {reason}")
    if payload["verdict"] == "COMMIT_READY":
        print(f"suggested_message: {payload['suggested_message']}")
    print_commit_decision(payload["decision"], as_json)

def plan_commit(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    payload = commit_plan_payload(data, args.repo)
    print_commit_plan(payload, args.json)
    return 0 if payload["verdict"] in {"NO_COMMIT", "COMMIT_READY"} else 1

def _validate_commit_message(message: str) -> str:
    message = message.strip()
    if not message:
        raise TaskError("commit message is empty")
    subject = message.splitlines()[0].strip()
    if len(subject) > 100:
        raise TaskError("commit subject exceeds 100 characters")
    if subject.endswith("."):
        raise TaskError("commit subject should not end with a period")
    return message

def _git_env_with_index(index_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index_path)
    env["GIT_EDITOR"] = "true"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env

def _run_git_env(repo_root: Path, args: list[str], env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[bytes]:
    proc = subprocess.run(["git", *args], cwd=str(repo_root), env=env, capture_output=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).decode(errors="replace").strip()
        raise TaskError(f"git command failed ({proc.returncode}): git {' '.join(args)}\n{detail}")
    return proc

def _mode_for_state(repo_root: Path, path: str, state: tuple[str, bytes | None]) -> str:
    kind, _content = state
    if kind == "symlink":
        return "120000"
    existing = run(["git", "ls-tree", "HEAD", "--", path], repo_root, check=False).stdout.strip()
    if existing:
        return existing.split()[0]
    full = repo_root / path
    if full.exists() and os.access(full, os.X_OK):
        return "100755"
    return "100644"

def _write_state_blob(repo_root: Path, path: str, state: tuple[str, bytes | None]) -> tuple[str, str] | None:
    kind, content = state
    if kind == "missing":
        return None
    if content is None:
        raise TaskError(f"missing content for {path}")
    args = ["git", "hash-object", "-w", "--stdin"]
    if kind == "file":
        args = ["git", "hash-object", "-w", f"--path={path}", "--stdin"]
    proc = subprocess.run(args, cwd=str(repo_root), input=content, capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise TaskError(f"cannot write git blob for {path}: {detail}")
    return _mode_for_state(repo_root, path, state), proc.stdout.decode().strip()

def _set_index_state(
    repo_root: Path,
    path: str,
    state: tuple[str, bytes | None],
    *,
    env: dict[str, str] | None = None,
) -> None:
    effective = env or os.environ.copy()
    blob = _write_state_blob(repo_root, path, state)
    if blob is None:
        _run_git_env(repo_root, ["update-index", "--force-remove", "--", path], effective)
        return
    mode, oid = blob
    _run_git_env(repo_root, ["update-index", "--add", "--cacheinfo", mode, oid, path], effective)

def _commit_states_or_fail(repo: str, repo_root: Path, owned_paths: list[str], data: dict[str, Any]) -> CommitStates:
    try:
        return prepare_owned_commit_states(
            repo,
            repo_root,
            owned_paths,
            data["ownership_baseline"],
            data["adopted_baseline_scope"],
            state_dir(),
        )
    except OwnershipError as exc:
        raise TaskError(str(exc)) from exc

def _write_isolated_commit(repo_root: Path, states: CommitStates, message: str) -> None:
    with tempfile.TemporaryDirectory(prefix="ai-os-commit-", dir=str(state_dir())) as temp_raw:
        temp = Path(temp_raw)
        env = _git_env_with_index(temp / "index")
        _run_git_env(repo_root, ["read-tree", "HEAD"], env)
        for path, path_states in states.items():
            _set_index_state(repo_root, path, path_states["commit"], env=env)
        tree = _run_git_env(repo_root, ["write-tree"], env).stdout.decode().strip()
        head_tree = run(["git", "rev-parse", "HEAD^{tree}"], repo_root).stdout.strip()
        if tree == head_tree:
            raise TaskError("isolated commit tree is identical to HEAD")
        message_file = temp / "message.txt"
        message_file.write_text(message + "\n", encoding="utf-8", newline="\n")
        proc = _run_git_env(repo_root, ["commit", "-F", str(message_file)], env, check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).decode(errors="replace").strip()
            raise TaskError(f"git commit failed: {detail}")

def _record_created_commit(task_id: str, repo: str, record: str) -> None:
    # Record SHA before index restore so a later failure still leaves an audit trail.
    data = load_checkpoint(task_id)
    if record not in data["commits"]:
        data["commits"].append(record)
    data["completed_steps"].append(
        {
            "timestamp": utc_now(),
            "text": f"Created scoped local commit {record} on {git_branch(repo)}",
        }
    )
    data["current_phase"] = "commit-created"
    data["last_summary"] = f"scoped local commit {record}"
    refresh_git_fields(data)
    atomic_write(data)

def _restore_real_index(repo_root: Path, states: CommitStates) -> list[str]:
    errors: list[str] = []
    for path, path_states in states.items():
        try:
            _set_index_state(repo_root, path, path_states["post_index"])
        except Exception as exc:  # noqa: BLE001 - collect residue, do not hide commit
            errors.append(f"{path}: {exc}")
    return errors

def _committed_paths(repo_root: Path, sha: str) -> set[str]:
    lines = run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha], repo_root
    ).stdout.splitlines()
    return {normalize_rel(line) for line in lines if line.strip()}

def _print_commit_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(f"COMMITTED: {result['repo']}:{result['sha']}")
    print(f"branch: {result['branch']}")
    print("paths: " + ", ".join(result["paths"]))
    print(f"publication: {result['publication_mode']} (no push performed)")

def commit_task(args: argparse.Namespace) -> int:
    message = _validate_commit_message(args.message)
    task_id = resolve_task_id(getattr(args, "task_id", None))
    with RepoCommitLock(args.repo):
        data = load_checkpoint(task_id)
        payload = commit_plan_payload(data, args.repo)
        if payload["verdict"] != "COMMIT_READY":
            print_commit_plan(payload, args.json)
            return 0 if payload["verdict"] == "NO_COMMIT" else 1
        repo_root = repo_path(args.repo)
        owned_paths = payload["owned_paths"]
        states = _commit_states_or_fail(args.repo, repo_root, owned_paths, data)
        _write_isolated_commit(repo_root, states, message)
        sha = git_head(args.repo)
        record = f"{args.repo}:{sha}"
        try:
            _record_created_commit(task_id, args.repo, record)
        finally:
            restore_errors = _restore_real_index(repo_root, states)
        if restore_errors:
            raise TaskError(
                f"commit {record} was created but index restore left residue: "
                + "; ".join(restore_errors)
            )
        changed = _committed_paths(repo_root, sha)
        unexpected = sorted(changed - set(owned_paths))
        if unexpected:
            raise TaskError(
                "commit was created but contains paths outside owned scope; do not rewrite history automatically: "
                + ", ".join(unexpected)
            )
        data = load_checkpoint(task_id)
        _print_commit_result(
            {
                "verdict": "COMMITTED",
                "repo": args.repo,
                "branch": git_branch(args.repo),
                "sha": sha,
                "subject": message.splitlines()[0],
                "paths": sorted(changed),
                "publication_mode": data["publication_mode"],
            },
            args.json,
        )
        return 0

def _require_clean_branch_ownership(data: dict[str, Any], repo: str) -> None:
    if data["ownership_conflicts"]:
        raise TaskError("cannot change branch while ownership conflicts exist")
    if owned_paths_for_repo(data, repo):
        raise TaskError("create/switch the task branch before making task-owned changes")

def _require_no_git_operation(repo: str) -> None:
    operation = git_operation_in_progress(repo)
    if operation:
        raise TaskError(f"cannot change branch during {operation}")

def _require_branch_switch_allowed(data: dict[str, Any], repo: str) -> None:
    if repo not in data["target_repositories"]:
        raise TaskError(f"branch repo is not in checkpoint target_repositories: {repo}")
    refresh_git_fields(data)
    _require_clean_branch_ownership(data, repo)
    _require_no_git_operation(repo)

def _require_creatable_branch_name(repo: str, name: str) -> None:
    check = run(["git", "check-ref-format", "--branch", name], repo_path(repo), check=False)
    if check.returncode != 0:
        raise TaskError(f"invalid branch name: {name}")
    exists = run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{name}"], repo_path(repo), check=False)
    if exists.returncode == 0:
        raise TaskError(f"branch already exists: {name}")

def create_task_branch(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    _require_branch_switch_allowed(data, args.repo)
    current = git_branch(args.repo)
    if current == args.name:
        print(f"BRANCH: already on {current}")
        return 0
    if current and not branch_is_protected(args.repo, current):
        raise TaskError(f"already on non-protected branch {current}; refusing implicit branch switch")
    _require_creatable_branch_name(args.repo, args.name)
    with RepoCommitLock(args.repo):
        run(["git", "switch", "-c", args.name], repo_path(args.repo))
    data["decisions"].append({"timestamp": utc_now(), "text": f"Created task branch {args.repo}:{args.name}"})
    data["current_phase"] = "task-branch"
    refresh_git_fields(data)
    atomic_write(data)
    print(f"BRANCH: {args.repo}:{args.name}")
    return 0

def _resolve_write_target(data: dict[str, Any], write_path: str) -> tuple[str, str]:
    raw = Path(write_path).expanduser()
    candidate = raw if raw.is_absolute() else (Path.cwd() / raw)
    candidate = candidate.resolve(strict=False)
    for repo in data["target_repositories"]:
        try:
            rel = candidate.relative_to(repo_path(repo))
        except ValueError:
            continue
        return repo, normalize_rel(str(rel))
    raise TaskError(f"write path is outside checkpoint target repositories: {candidate}")

def guard_write(args: argparse.Namespace) -> int:
    data = load_checkpoint(getattr(args, "task_id", None))
    matched_repo, matched_rel = _resolve_write_target(data, args.path)
    if not scope_contains(data["declared_write_scope"], {"repo": matched_repo, "path": matched_rel}):
        raise TaskError(f"write path is outside declared scope: {matched_repo}:{matched_rel}")
    operation = git_operation_in_progress(matched_repo)
    if operation:
        raise TaskError(f"write blocked while git operation is in progress: {operation}")
    branch = git_branch(matched_repo)
    if branch_is_protected(matched_repo, branch):
        raise TaskError(
            f"write blocked on protected/default branch {branch or '<detached>'}; "
            f"run task-branch --repo {matched_repo} --name <task-branch>"
        )
    print(json.dumps({"ok": True, "repo": matched_repo, "path": matched_rel, "branch": branch}))
    return 0

OWN_RESIDUE_LABELS = (
    ("own_staged_files", "own staged files remain"),
    ("own_unstaged_files", "own unstaged files remain"),
    ("own_untracked_files", "own untracked files remain"),
)

def _own_residue_issues(data: dict[str, Any]) -> list[str]:
    issues = [
        f"{label}: " + ", ".join(data[key])
        for key, label in OWN_RESIDUE_LABELS
        if data[key]
    ]
    issues.extend(data["ownership_conflicts"])
    return issues

def _split_commit_record(commit: str, default_repo: str) -> tuple[str, str]:
    if ":" not in commit:
        return default_repo, commit
    repo, sha = commit.split(":", 1)
    return repo, sha

def _commit_existence_issues(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not data["commits"]:
        issues.append("no created commits recorded")
    for commit in data["commits"]:
        repo, sha = _split_commit_record(commit, data["target_repositories"][0])
        proc = subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(repo_path(repo)), capture_output=True)
        if proc.returncode != 0:
            issues.append(f"declared commit does not exist: {commit}")
    return issues

def _forbidden_marker_issues(gate: dict[str, Any]) -> list[str]:
    command = str(gate.get("command", "")).lower()
    return [
        f"forbidden operation marker recorded in gate {gate['gate_id']}: {marker}"
        for marker in FORBIDDEN_COMMAND_MARKERS
        if marker in command
    ]

def _gate_currency_issues(gate_id: str, gate: dict[str, Any]) -> list[str]:
    if gate["verdict"] not in PASSING_GATE_VERDICTS:
        return [f"latest gate is not PASS/DEDUPLICATED: {gate_id}={gate['verdict']}"]
    if recompute_gate_fingerprint_from_entry(gate) != gate.get("fingerprint"):
        return [f"gate fingerprint is stale: {gate_id}"]
    return []

def _gate_issues(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not data["gates"]:
        issues.append("no gates recorded")
    latest_by_gate: dict[str, dict[str, Any]] = {}
    for gate in data["gates"]:
        latest_by_gate[gate["gate_id"]] = gate
        issues.extend(_forbidden_marker_issues(gate))
    for gate_id, gate in latest_by_gate.items():
        issues.extend(_gate_currency_issues(gate_id, gate))
    return issues

def _frozen_path_issues(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for repo in [name for name in FROZEN_PATHS if name in data["target_repositories"]]:
        frozen = sorted(FROZEN_PATHS[repo])
        changed = run(["git", "status", "--porcelain", "--", *frozen], repo_path(repo)).stdout.strip()
        if changed:
            issues.append(f"frozen paths changed in {repo}")
    return issues

def closure_issues(data: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if data["status"] != "READY_TO_CLOSE":
        issues.append(f"status must be READY_TO_CLOSE, got {data['status']}")
    if not data["declared_write_scope"]:
        issues.append("declared_write_scope is empty")
    refresh_git_fields(data)
    issues.extend(_own_residue_issues(data))
    issues.extend(_commit_existence_issues(data))
    issues.extend(_gate_issues(data))
    blockers = open_blockers(data)
    if blockers:
        issues.append(f"open blockers remain: {len(blockers)}")
    if data["next_action"]:
        issues.append("next_action must be empty for full close")
    issues.extend(_frozen_path_issues(data))
    return issues
