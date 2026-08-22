"""Tiny proof artifact helper for bounded trajectory scripts (P3).

Removes only the repetitive boilerplate around deterministic proof JSON:
timestamp, metadata, assertion list, secret redaction, PASS/FAIL summary.
Scenario logic stays in the trajectory script; this is NOT a proof framework.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    ("OpenAI-style secret", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def redact_value(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Recursively redact secret-like values; deterministic; never raises."""
    if _seen is None:
        _seen = set()
    if isinstance(value, str):
        out = value
        for kind, pattern in _SECRET_PATTERNS:
            if pattern.search(out):
                out = pattern.sub(f"[REDACTED:{kind}]", out)
        return out
    if isinstance(value, dict):
        marker = id(value)
        if marker in _seen:
            return "[CYCLE]"
        _seen.add(marker)
        result = {key: redact_value(item, _seen=_seen) for key, item in value.items()}
        _seen.discard(marker)
        return result
    if isinstance(value, (list, tuple)):
        marker = id(value)
        if marker in _seen:
            return "[CYCLE]"
        _seen.add(marker)
        result = [redact_value(item, _seen=_seen) for item in value]
        _seen.discard(marker)
        return result
    return value


class ProofArtifact:
    """Record + assert + write deterministic proof JSON."""

    def __init__(
        self,
        name: str,
        directory: str | Path,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.name = str(name).strip()
        if not self.name:
            raise ValueError("proof artifact name is required")
        self.directory = Path(directory)
        self.metadata = dict(metadata or {})
        self.records: dict[str, Any] = {}
        self.assertions: list[dict[str, str]] = []
        self.created_at = utc_now()

    def record(self, key: str, value: Any) -> "ProofArtifact":
        self.records[str(key)] = value
        return self

    def assert_invariant(self, condition: bool, label: str, detail: str = "") -> "ProofArtifact":
        status = "PASS" if condition else "FAIL"
        self.assertions.append(
            {"label": str(label), "status": status, "detail": str(detail)[:400]}
        )
        if not condition:
            raise AssertionError(f"proof invariant FAILED: {label} {detail}".strip())
        return self

    def summary(self) -> dict[str, Any]:
        failed = [item for item in self.assertions if item["status"] == "FAIL"]
        return {
            "artifact": self.name,
            "assertions_total": len(self.assertions),
            "assertions_failed": len(failed),
            "verdict": "PASS" if not failed else "FAIL",
            "created_at": self.created_at,
        }

    def write(self, filename: str | None = None) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = redact_value(
            {
                "schema_version": "ai_os_proof_artifact.v1",
                "artifact": self.name,
                "created_at": self.created_at,
                "metadata": self.metadata,
                "records": self.records,
                "assertions": self.assertions,
                "summary": self.summary(),
            }
        )
        target = self.directory / (filename or f"{self.name}.json")
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"PROOF {self.name}: {json.dumps(payload['summary'], ensure_ascii=False)}")
        return target


__all__ = ["ProofArtifact", "redact_value", "utc_now"]
