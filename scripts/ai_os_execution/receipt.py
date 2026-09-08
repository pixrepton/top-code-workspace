"""Append-only COMMAND_RECEIPT ledger for mediated execution."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from ai_os_execution.bundle import execution_dir
from ai_os_task_errors import TaskError
from ai_os_task_paths import utc_now


def receipts_path(execution_id: str) -> Path:
    root = execution_dir(execution_id) / "receipts"
    root.mkdir(parents=True, exist_ok=True)
    return root / "COMMAND_RECEIPTS.jsonl"


def new_receipt_id() -> str:
    return f"rcpt_{utc_now().replace('-', '').replace(':', '')}_{secrets.token_hex(3)}"


def _hash_file(path: Path) -> str:
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append_receipt(execution_id: str, receipt: dict[str, Any]) -> Path:
    path = receipts_path(execution_id)
    line = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")
    return path


def load_receipts(execution_id: str) -> list[dict[str, Any]]:
    path = receipts_path(execution_id)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def load_receipt(execution_id: str, receipt_id: str) -> dict[str, Any] | None:
    for row in load_receipts(execution_id):
        if row.get("receipt_id") == receipt_id:
            return row
    return None


def write_command_receipt(
    *,
    context: dict[str, Any],
    command: list[str],
    exit_code: int,
    repo_sha_before: str,
    repo_sha_after: str,
    stdout_path: Path,
    stderr_path: Path,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    receipt = {
        "receipt_id": new_receipt_id(),
        "execution_id": context["execution_id"],
        "generation": context["generation"],
        "repo": context["repo"],
        "operation": context["operation_kind"],
        "trusted": bool(context.get("trusted")),
        "command": " ".join(command),
        "command_argv": list(command),
        "repo_sha_before": repo_sha_before,
        "repo_sha_after": repo_sha_after,
        "execution_context_hash": context["execution_context_hash"],
        "environment_manifest_hash": context.get("environment_manifest_hash") or "",
        "fencing_token": context.get("fencing_token") or "",
        "started_at": started_at,
        "finished_at": finished_at,
        "exit_code": exit_code,
        "artifact_hashes": {
            "stdout": _hash_file(stdout_path),
            "stderr": _hash_file(stderr_path),
        },
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    append_receipt(context["execution_id"], receipt)
    return receipt


def validate_receipt_for_proof(
    receipt: dict[str, Any],
    *,
    bundle: dict[str, Any],
    current_context_hash: str,
    operation_kind: str,
) -> None:
    from ai_os_execution.execution_context import PROOF_OPERATION_KINDS
    from ai_os_execution.generation import current_lease_generation

    if operation_kind not in PROOF_OPERATION_KINDS:
        return
    if not receipt.get("trusted"):
        raise TaskError("UNTRUSTED_PROOF_EXECUTION: receipt is not from mediated trusted execution")
    if int(receipt.get("generation") or 0) != current_lease_generation(bundle):
        raise TaskError("GENERATION_LOST: receipt generation does not match active bundle generation")
    if str(receipt.get("execution_context_hash") or "") != current_context_hash:
        raise TaskError("execution_context_hash mismatch between receipt and current execution context")
    if str(receipt.get("fencing_token") or "") != str(bundle.get("fencing_token") or ""):
        raise TaskError("FENCING_TOKEN_MISMATCH: receipt fencing token is stale")
    exit_code = receipt.get("exit_code")
    if exit_code is None or int(exit_code) != 0:
        raise TaskError(f"receipt exit_code is not zero: {exit_code}")
