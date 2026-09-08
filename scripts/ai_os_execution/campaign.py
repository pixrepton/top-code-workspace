"""Generated campaign state and TASK_ENTRY.md — projections, not a competing SoT."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ai_os_execution import EXECUTION_PROTOCOL_VERSION, SUPPORTED_EXECUTION_PROTOCOL_VERSIONS
from ai_os_execution.bundle import atomic_json, bundle_path, execution_dir, load_bundle_for_task, load_index
from ai_os_execution.generation import active_repo_entries, current_lease_generation
from ai_os_execution.preflight import graph_freshness_for_repo
from ai_os_execution.proof import load_latest_proof
from ai_os_execution.receipt import load_receipts
from ai_os_execution.tainted import is_tainted
from ai_os_task_errors import TaskError
from ai_os_task_git import canonical_repo_path, run
from ai_os_task_paths import list_active_task_ids, state_dir, utc_now


AUTHORITY_ORDER = [
    "current_task_record",
    "current_execution_bundle",
    "latest_valid_proof_bundle_receipts",
    "generated_campaign_state",
    "generated_task_entry",
    "historical_task_archives",
    "historical_plans_transcripts",
]

_SECRET_URL_RE = re.compile(r"(?i)(?:postgres(?:ql)?|mysql|mongodb|redis)://[^\s\"']+")
_CRED_URL_RE = re.compile(r"(?i)https?://[^/\s:]+:[^@/\s]+@")
_DEFAULT_STOP = [
    "Do not mutate the canonical shared checkout.",
    "Stateful proof commands go through mediated exec / trusted gate.",
    "TAINTED is not PASS; old-generation receipts are not valid.",
    "FINAL_HEAD_GATE is required after the last commit before task-close.",
]
_DEFAULT_REFS = [
    "HISTORICAL_CONTEXT: older Cursor/Codex/Claude plans and transcripts",
    "knowledge/system-atlas/tooling/EXECUTION_PLANE_V1.md",
    ".agents/skills/ai-os-execution/SKILL.md",
]


def campaign_state_path() -> Path:
    return state_dir() / "CAMPAIGN_STATE.generated.json"


def protocol_status(bundle: dict[str, Any] | None) -> str:
    if not bundle:
        return "NONE"
    protocol = str(bundle.get("execution_protocol_version") or "").strip()
    if not protocol:
        return "LEGACY"
    if protocol in SUPPORTED_EXECUTION_PROTOCOL_VERSIONS:
        return "CURRENT"
    return "UNSUPPORTED"


def peek_protocol_version(execution_id: str) -> str:
    path = bundle_path(execution_id)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("execution_protocol_version") or "").strip()


def _worktree_sha(entry: dict[str, Any]) -> str:
    worktree = Path(str(entry.get("worktree_path") or ""))
    recorded = str(entry.get("current_sha") or "")
    if worktree.exists() and (worktree / ".git").exists():
        try:
            return run(["git", "rev-parse", "--verify", "HEAD"], worktree).stdout.strip()
        except TaskError:
            return recorded
    return recorded


def _active_heads(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    heads: dict[str, dict[str, Any]] = {}
    for name, entry in active_repo_entries(bundle).items():
        sha = _worktree_sha(entry)
        canonical = str(entry.get("canonical_repo") or "")
        graph = {"status": "UNAVAILABLE", "repo_sha": sha, "index_sha": ""}
        try:
            graph = graph_freshness_for_repo(Path(canonical) if canonical else canonical_repo_path(name), sha)
        except TaskError:
            graph = graph_freshness_for_repo(Path(entry.get("worktree_path") or "."), sha)
        heads[name] = {
            "sha": sha,
            "base_sha": entry.get("base_sha"),
            "worktree": entry.get("worktree_path"),
            "branch": entry.get("branch"),
            "worktree_status": entry.get("worktree_status") or "ACTIVE",
            "graph_status": graph.get("status"),
        }
    return heads


def _lease_status_for(bundle: dict[str, Any]) -> str:
    from ai_os_execution.lease import lease_status, load_leases

    execution_id = str(bundle.get("execution_id") or "")
    for lease in load_leases():
        if lease.get("execution_id") == execution_id:
            return lease_status(lease)
    return "NONE"


def _latest_trusted_receipt(execution_id: str, generation: int) -> dict[str, Any] | None:
    rows = []
    for row in load_receipts(execution_id):
        if not row.get("trusted"):
            continue
        if int(row.get("generation") or 0) != generation:
            continue
        exit_code = row.get("exit_code")
        if exit_code is None or int(exit_code) != 0:
            continue
        rows.append(row)
    return rows[-1] if rows else None


def _public_receipt(receipt: dict[str, Any] | None) -> dict[str, Any]:
    if not receipt:
        return {}
    return {
        "receipt_id": receipt.get("receipt_id") or "",
        "generation": receipt.get("generation"),
        "operation": receipt.get("operation") or "",
        "exit_code": receipt.get("exit_code"),
        "execution_context_hash": receipt.get("execution_context_hash") or "",
        "environment_manifest_hash": receipt.get("environment_manifest_hash") or "",
        "finished_at": receipt.get("finished_at") or "",
        "repo": receipt.get("repo") or "",
    }


def _final_head_status(bundle: dict[str, Any]) -> str:
    final_head = bundle.get("final_head") or {}
    if final_head.get("valid"):
        return "VALID"
    reason = str(final_head.get("invalidated_reason") or "").lower()
    if any(token in reason for token in ("takeover", "commit", "head", "generation")):
        return "STALE"
    if final_head.get("required"):
        return "INVALID"
    return "INVALID"


def _taint_payload(bundle: dict[str, Any]) -> tuple[str, list[str]]:
    if is_tainted(bundle):
        tainted = bundle.get("tainted") or {}
        return "TAINTED", list(tainted.get("reasons") or [])
    return "CLEAN", []


def _execution_status(bundle: dict[str, Any], taint_status: str) -> str:
    status = str(bundle.get("status") or "ACTIVE")
    if taint_status == "TAINTED":
        return f"{status}_TAINTED"
    if status == "ACTIVE":
        return "ACTIVE_CLEAN"
    return status


def generate_campaign_state(*, current_task_id: str = "", current_program: str = "") -> dict[str, Any]:
    active = list_active_task_ids()
    current = current_task_id or (active[0] if len(active) == 1 else "")
    checkpoint: dict[str, Any] = {}
    if current:
        try:
            from ai_os_task_state import load_checkpoint

            checkpoint = load_checkpoint(current)
        except Exception:
            checkpoint = {}
    execution_id = str((checkpoint or {}).get("execution_id") or "")
    if current and not execution_id:
        execution_id = str(load_index().get(current) or "")
    bundle = None
    protocol = "legacy"
    proto_status = "NONE"
    if execution_id:
        protocol = peek_protocol_version(execution_id) or "legacy"
        if protocol and protocol not in SUPPORTED_EXECUTION_PROTOCOL_VERSIONS and protocol != "legacy":
            proto_status = "UNSUPPORTED"
        else:
            bundle = load_bundle_for_task(current) if current else None
            proto_status = protocol_status(bundle)
            protocol = str((bundle or {}).get("execution_protocol_version") or protocol or "legacy")
    generation = current_lease_generation(bundle) if bundle else 0
    taint_status, taint_reasons = _taint_payload(bundle) if bundle else ("NONE", [])
    heads = _active_heads(bundle) if bundle else {}
    receipt = _latest_trusted_receipt(str(bundle["execution_id"]), generation) if bundle else None
    proof = load_latest_proof(bundle["execution_id"]) if bundle else None
    proof_path = ""
    if bundle:
        candidate = execution_dir(bundle["execution_id"]) / "PROOF_BUNDLE.json"
        proof_path = str(candidate) if candidate.exists() else ""
    lease = _lease_status_for(bundle) if bundle else "NONE"
    next_action = str(checkpoint.get("next_action") or "")
    recommended = ""
    if lease == "STALE_LEASE":
        recommended = "explicit recovery/takeover via execution-takeover"
    elif taint_status == "TAINTED":
        recommended = "fresh mediated exec/gate in current generation; do not treat as PASS"
    elif not current:
        recommended = "start a mutating task with Execution Plane (python scripts/ai_os_task.py start ...)"
    elif bundle is None and current:
        recommended = "LEGACY checkpoint: do not invent an Execution Bundle; use --legacy only where allowed"
    payload = {
        "generated_at": utc_now(),
        "projection": True,
        "authority_order": AUTHORITY_ORDER,
        "historical_plans_and_transcripts": "HISTORICAL_CONTEXT",
        "current_program": current_program or (bundle or {}).get("campaign_id") or "",
        "current_task": current,
        "task_status": checkpoint.get("status") or "",
        "execution_id": (bundle or {}).get("execution_id") or "",
        "execution_protocol_version": protocol if bundle or proto_status == "UNSUPPORTED" else ("legacy" if current else ""),
        "protocol_status": proto_status,
        "execution_generation": generation,
        "execution_status": _execution_status(bundle, taint_status) if bundle else ("LEGACY" if current else "NONE"),
        "taint_status": taint_status,
        "taint_reasons": taint_reasons,
        "execution_mode": (bundle or {}).get("execution_mode") or checkpoint.get("execution_mode") or "",
        "seed_origin": ((bundle or {}).get("database") or {}).get("seed_origin") or "",
        "current_heads": heads,
        "worktrees": {name: item.get("worktree") for name, item in heads.items()},
        "owned_paths": list(((bundle or {}).get("ownership") or {}).get("owned_paths") or checkpoint.get("declared_write_scope") or []),
        "runtime_profile": ((bundle or {}).get("runtime") or {}).get("profile") or "",
        "current_first_divergence": ((bundle or {}).get("benchmark") or {}).get("first_divergence") or "",
        "latest_command_receipt": _public_receipt(receipt),
        "last_valid_proof": {
            "verdict": (proof or {}).get("verdict") or "",
            "path": proof_path,
            "command_receipt_id": ((proof or {}).get("gate") or {}).get("command_receipt_id") or "",
            "execution_context_hash": ((proof or {}).get("gate") or {}).get("execution_context_hash") or "",
        },
        "final_head_status": _final_head_status(bundle) if bundle else "N/A",
        "lease_status": lease,
        "promotion_status": (bundle or {}).get("status") or "",
        "next_action": next_action,
        "recommended_action": recommended,
        "active_tasks": active,
        "lifecycle": (bundle or {}).get("status") or "",
        "kind": (
            "UNSUPPORTED"
            if proto_status == "UNSUPPORTED"
            else ("PLANE" if bundle else ("LEGACY" if current else "NONE"))
        ),
    }
    atomic_json(payload, campaign_state_path())
    return payload


def write_task_entry(
    bundle: dict[str, Any],
    *,
    goal: str = "",
    owned_paths: list[str] | None = None,
    stop_conditions: list[str] | None = None,
    references: list[str] | None = None,
    checkpoint: dict[str, Any] | None = None,
    campaign: dict[str, Any] | None = None,
) -> Path:
    state = campaign or {}
    heads = state.get("current_heads") or _active_heads(bundle)
    owned = owned_paths or list((bundle.get("ownership") or {}).get("owned_paths") or [])
    if owned and isinstance(owned[0], dict):
        owned = [f"{item.get('repo')}:{item.get('path')}" for item in owned]
    taint_status, taint_reasons = _taint_payload(bundle)
    receipt = state.get("latest_command_receipt") or _public_receipt(
        _latest_trusted_receipt(str(bundle["execution_id"]), current_lease_generation(bundle))
    )
    proof = state.get("last_valid_proof") or {}
    runtime = bundle.get("runtime") or {}
    database = bundle.get("database") or {}
    next_action = str((checkpoint or {}).get("next_action") or state.get("next_action") or "")
    recommended = str(state.get("recommended_action") or "")
    protocol = str(bundle.get("execution_protocol_version") or "legacy")
    lines = [
        f"# TASK ENTRY — {bundle.get('task_id')}",
        "",
        f"TASK: {bundle.get('task_id')}",
        f"GOAL: {goal or (checkpoint or {}).get('task_title') or ''}",
        f"MODE: {bundle.get('execution_mode')}",
        f"EXECUTION_ID: {bundle.get('execution_id')}",
        f"PROTOCOL_VERSION: {protocol}",
        f"GENERATION: {current_lease_generation(bundle)}",
        f"STATUS: {_execution_status(bundle, taint_status)}",
        f"TAINT: {taint_status}" + (f" ({', '.join(taint_reasons)})" if taint_reasons else ""),
        "",
        "HEADS / WORKTREES:",
    ]
    for name, entry in heads.items():
        lines.append(
            f"- {name}: `{entry.get('worktree')}` HEAD {entry.get('sha')} base {entry.get('base_sha')} [{entry.get('graph_status')}]"
        )
    lines.append("OWNED PATHS: " + (", ".join(str(p) for p in owned) if owned else "(none)"))
    lines.append(f"RUNTIME PROFILE: {runtime.get('profile') or ''}")
    lines.append(
        f"DATA / REPLAY: seed={database.get('seed_origin') or ''} isolation={database.get('isolation_mode') or ''}"
    )
    lines.append(
        "LATEST VALID PROOF: "
        + (proof.get("verdict") or "(none)")
        + (f" receipt={proof.get('command_receipt_id')}" if proof.get("command_receipt_id") else "")
    )
    lines.append(
        "LATEST TRUSTED RECEIPT: "
        + (receipt.get("receipt_id") or "(none)")
        + (f" gen={receipt.get('generation')}" if receipt.get("generation") is not None else "")
    )
    lines.append(f"FINAL_HEAD: {state.get('final_head_status') or _final_head_status(bundle)}")
    lines.append(f"NEXT: {next_action or recommended or '(none)'}")
    lines.append("STOP CONDITIONS:")
    for item in stop_conditions or _DEFAULT_STOP:
        lines.append(f"- {item}")
    lines.append("REFERENCES (historical, not CURRENT_INSTRUCTION):")
    for item in references or _DEFAULT_REFS:
        lines.append(f"- {item}")
    lines.append("")
    text = "\n".join(lines)
    assert_no_secrets(text)
    path = execution_dir(bundle["execution_id"]) / "TASK_ENTRY.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def assert_no_secrets(text: str) -> None:
    lowered = text.lower()
    if "postgresql://" in lowered or "mysql://" in lowered:
        raise TaskError("secret/DSN leaked into generated projection")
    if _SECRET_URL_RE.search(text) or _CRED_URL_RE.search(text):
        raise TaskError("URL credential leaked into generated projection")


def format_session_inject(state: dict[str, Any]) -> str:
    kind = str(state.get("kind") or "NONE")
    if kind == "NONE":
        return (
            "CURRENT TASK: none\n"
            "KIND: NONE\n"
            "Do not invent an Execution Bundle.\n"
            "RULE: Mutating work requires Execution Plane start."
        )
    if kind == "LEGACY":
        return (
            f"CURRENT TASK: {state.get('current_task')}\n"
            "KIND: LEGACY\n"
            "EXECUTION: none\n"
            f"STATUS: {state.get('task_status') or 'UNKNOWN'}\n"
            f"NEXT: {state.get('next_action') or '(none)'}\n"
            "RULE: Legacy checkpoint — not a plane proof. Do not fabricate execution_id."
        )
    if kind == "UNSUPPORTED":
        return (
            f"CURRENT TASK: {state.get('current_task')}\n"
            f"PROTOCOL: {state.get('execution_protocol_version')}\n"
            "STATUS: UNSUPPORTED\n"
            "FAIL: explicit incompatibility — do not guess execution semantics."
        )
    taint = str(state.get("taint_status") or "CLEAN")
    taint_line = f"TAINT: {taint}"
    if taint == "TAINTED":
        taint_line += f" reasons={', '.join(state.get('taint_reasons') or [])} — not PASS"
    repos = []
    for name, entry in (state.get("current_heads") or {}).items():
        repos.append(f"{name} -> {entry.get('worktree')} @ {str(entry.get('sha') or '')[:12]}")
    receipt = state.get("latest_command_receipt") or {}
    proof = state.get("last_valid_proof") or {}
    lease = str(state.get("lease_status") or "")
    next_line = str(state.get("next_action") or state.get("recommended_action") or "(none)")
    owned = state.get("owned_paths") or []
    owned_s = ", ".join(
        str(p) if not isinstance(p, dict) else f"{p.get('repo')}:{p.get('path')}" for p in owned
    ) or "(none)"
    repo_lines = [f"  {row}" for row in repos] or ["  (none)"]
    lines = [
        f"CURRENT TASK: {state.get('current_task')}",
        f"EXECUTION: {state.get('execution_id')}",
        f"PROTOCOL: {state.get('execution_protocol_version') or EXECUTION_PROTOCOL_VERSION}",
        f"GENERATION: {state.get('execution_generation')}",
        f"STATUS: {state.get('execution_status')}",
        f"MODE: {state.get('execution_mode')}",
        taint_line,
        "REPOS:",
        *repo_lines,
        f"OWNED PATHS: {owned_s}",
        f"LATEST TRUSTED RECEIPT: {receipt.get('receipt_id') or '(none)'} gen={receipt.get('generation') or '-'}",
        f"LATEST TRUSTED PROOF: {proof.get('verdict') or '(none)'} receipt={proof.get('command_receipt_id') or '-'}",
        f"FINAL_HEAD: {state.get('final_head_status')}",
        f"NEXT: {next_line}",
        "RULE: Use Execution Plane. Stateful commands via mediated exec. Raw pytest/build is not close proof.",
    ]
    if lease == "STALE_LEASE":
        lines.insert(-1, "STALE_LEASE recommended action: explicit recovery/takeover (do not auto-takeover)")
    text = "\n".join(lines)
    assert_no_secrets(text)
    return text
