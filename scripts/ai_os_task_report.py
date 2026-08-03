"""Console rendering for checkpoint summaries and commit plans."""

from __future__ import annotations

import json
from typing import Any

from ai_os_task_state import git_mismatches


DETACHED = "<detached>"


def _print_branches(data: dict[str, Any]) -> None:
    branches = data.get("current_branches", {})
    for repo in data["target_repositories"]:
        branch = branches.get(repo, "")
        print(f"branch[{repo}]: {branch or DETACHED}")


def _print_last_commit(data: dict[str, Any]) -> None:
    if data["commits"]:
        print(f"last_commit: {data['commits'][-1]}")


def _print_last_gate(data: dict[str, Any]) -> None:
    gates = data["gates"]
    if not gates:
        return
    last_gate = gates[-1]
    print(f"last_gate: {last_gate['gate_id']} {last_gate['verdict']}")


def _print_counters(data: dict[str, Any]) -> None:
    if data["blockers"]:
        print(f"blockers: {len(data['blockers'])}")
    if data["ownership_conflicts"]:
        print(f"ownership_conflicts: {len(data['ownership_conflicts'])}")


def _print_git_mismatches(data: dict[str, Any]) -> None:
    mismatches = git_mismatches(data)
    if mismatches:
        print("git_state_mismatch: " + "; ".join(mismatches))


def print_summary(data: dict[str, Any], prefix: str = "TASK") -> None:
    scope = ", ".join(f"{item['repo']}:{item['path']}" for item in data["declared_write_scope"])
    print(f"{prefix}: {data['task_id']} [{data['status']}] {data['current_phase']}")
    print(f"title: {data['task_title']}")
    print(f"class: {data['task_class']}")
    print("repos: " + ", ".join(data["target_repositories"]))
    print("scope: " + scope)
    print(f"publication: {data['publication_mode']}")
    _print_branches(data)
    _print_last_commit(data)
    _print_last_gate(data)
    print(f"next: {data['next_action'] or '<none>'}")
    _print_counters(data)
    _print_git_mismatches(data)


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_commit_plan(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print_json(payload)
        return
    print(f"COMMIT PLAN: {payload['verdict']}")
    print(f"repo: {payload['repo']}")
    print(f"branch: {payload['branch'] or DETACHED}")
    print(f"publication: {payload['publication_mode']}")
    if payload["owned_paths"]:
        print("paths: " + ", ".join(payload["owned_paths"]))
    for warning in payload["warnings"]:
        print(f"warning: {warning}")
    for reason in payload["reasons"]:
        print(f"blocked: {reason}")
    if payload["verdict"] == "COMMIT_READY":
        print(f"suggested_message: {payload['suggested_message']}")
