"""Generated campaign state and TASK_ENTRY.md — not a competing manual SoT."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_os_execution.bundle import atomic_json, execution_dir, load_bundle_for_task, load_index
from ai_os_execution.proof import load_latest_proof
from ai_os_task_paths import list_active_task_ids, state_dir, utc_now


AUTHORITY_ORDER = [
    "current_task_record",
    "current_execution_bundle",
    "latest_valid_proof_bundle",
    "generated_campaign_state",
    "historical_task_archives",
    "historical_plans_transcripts",
]


def campaign_state_path() -> Path:
    return state_dir() / "CAMPAIGN_STATE.generated.json"


def generate_campaign_state(*, current_task_id: str = "", current_program: str = "") -> dict[str, Any]:
    active = list_active_task_ids()
    current = current_task_id or (active[0] if len(active) == 1 else "")
    bundle = load_bundle_for_task(current) if current else None
    proof = load_latest_proof(bundle["execution_id"]) if bundle else None
    heads = {}
    if bundle:
        heads = {
            name: {
                "sha": entry.get("current_sha"),
                "base_sha": entry.get("base_sha"),
                "worktree": entry.get("worktree_path"),
                "branch": entry.get("branch"),
            }
            for name, entry in (bundle.get("repos") or {}).items()
        }
    payload = {
        "generated_at": utc_now(),
        "authority_order": AUTHORITY_ORDER,
        "historical_plans_and_transcripts": "HISTORICAL_CONTEXT",
        "current_program": current_program or (bundle or {}).get("campaign_id") or "",
        "current_task": current,
        "execution_id": (bundle or {}).get("execution_id") or "",
        "active_tasks": active,
        "current_heads": heads,
        "last_valid_proof": (proof or {}).get("verdict") if proof else "",
        "last_valid_proof_path": str(execution_dir(bundle["execution_id"]) / "PROOF_BUNDLE.json") if bundle else "",
        "current_first_divergence": ((bundle or {}).get("benchmark") or {}).get("first_divergence") or "",
        "promotion_status": (bundle or {}).get("status") or "",
        "next_action": "",
        "lifecycle": (bundle or {}).get("status") or "",
    }
    if current:
        try:
            from ai_os_task_state import load_checkpoint

            data = load_checkpoint(current)
            payload["next_action"] = data.get("next_action") or ""
            payload["task_status"] = data.get("status")
        except Exception:
            payload["task_status"] = ""
    atomic_json(payload, campaign_state_path())
    return payload


def write_task_entry(bundle: dict[str, Any], *, goal: str, owned_paths: list[str], stop_conditions: list[str], references: list[str]) -> Path:
    repos = bundle.get("repos") or {}
    db = bundle.get("database") or {}
    runtime = bundle.get("runtime") or {}
    proof = bundle.get("proof") or {}
    lines = [
        f"# TASK ENTRY — {bundle.get('task_id')}",
        "",
        f"TASK: {bundle.get('task_id')}",
        f"EXECUTION: {bundle.get('execution_id')}",
        f"GOAL: {goal}",
        "",
        "## BASE SHAS",
    ]
    for name, entry in repos.items():
        lines.append(f"- {name}: {entry.get('base_sha')} ({entry.get('mutation_mode')})")
    lines.extend(["", "## WORKTREES"])
    for name, entry in repos.items():
        lines.append(f"- {name}: `{entry.get('worktree_path')}` HEAD {entry.get('current_sha')} branch {entry.get('branch')}")
    lines.extend(["", "## OWNED PATHS"])
    for path in owned_paths:
        lines.append(f"- {path}")
    lines.extend(
        [
            "",
            "## RUNTIME",
            f"- namespace: {runtime.get('namespace')}",
            f"- compose_project: {runtime.get('compose_project')}",
            "",
            "## DB MODE",
            f"- isolation_mode: {db.get('isolation_mode')}",
            f"- database: {db.get('database_name')}",
            f"- principal: {db.get('principal')}",
            f"- seed: {db.get('seed_origin')} {db.get('seed_identity')}",
            "",
            "## BENCHMARK",
            f"- manifest_hash: {(bundle.get('benchmark') or {}).get('manifest_hash') or '(none)'}",
            "",
            "## VALID PREVIOUS PROOF",
            f"- {proof.get('latest_proof_bundle') or '(none)'}",
            "",
            "## STOP CONDITIONS",
        ]
    )
    for item in stop_conditions:
        lines.append(f"- {item}")
    if references:
        lines.extend(["", "## REFERENCES (historical, not active instructions)"])
        for item in references:
            lines.append(f"- {item}")
    lines.append("")
    path = execution_dir(bundle["execution_id"]) / "TASK_ENTRY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path
