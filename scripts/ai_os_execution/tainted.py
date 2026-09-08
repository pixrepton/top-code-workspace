"""TAINTED execution state — recoverable work, invalid final proof until fresh trusted run."""

from __future__ import annotations

from typing import Any

from ai_os_task_errors import TaskError
from ai_os_task_paths import utc_now

TAINT_REASONS = frozenset(
    {
        "GENERATION_LOST",
        "UNTRUSTED_PROOF_EXECUTION",
        "CANONICAL_TREE_MUTATED",
        "STORE_POLICY_VIOLATION",
        "ENV_POLICY_VIOLATION",
        "IMAGE_SOURCE_MISMATCH",
        "FENCING_TOKEN_MISMATCH",
    }
)


def is_tainted(bundle: dict[str, Any]) -> bool:
    tainted = bundle.get("tainted") or {}
    return str(tainted.get("status") or "") == "TAINTED"


def mark_tainted(bundle: dict[str, Any], reason_code: str, *, detail: str = "") -> None:
    token = reason_code.split(":", 1)[0].strip()
    if token not in TAINT_REASONS:
        token = "UNTRUSTED_PROOF_EXECUTION"
    existing = bundle.get("tainted") or {}
    reasons = list(existing.get("reasons") or [])
    if token not in reasons:
        reasons.append(token)
    bundle["tainted"] = {
        "status": "TAINTED",
        "reasons": reasons,
        "detail": detail or existing.get("detail") or "",
        "since": existing.get("since") or utc_now(),
        "updated_at": utc_now(),
    }


def clear_tainted(bundle: dict[str, Any]) -> None:
    bundle.pop("tainted", None)


def assert_not_tainted_for_proof(bundle: dict[str, Any], *, operation_kind: str) -> None:
    from ai_os_execution.execution_context import PROOF_OPERATION_KINDS

    if operation_kind not in PROOF_OPERATION_KINDS:
        return
    if is_tainted(bundle):
        reasons = ", ".join((bundle.get("tainted") or {}).get("reasons") or [])
        raise TaskError(f"execution bundle is TAINTED ({reasons}); trusted proof blocked")
