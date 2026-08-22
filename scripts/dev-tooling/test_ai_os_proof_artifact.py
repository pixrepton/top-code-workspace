"""P3: ProofArtifact helper - deterministic JSON, redaction, failure recording."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_os_proof_artifact import ProofArtifact, redact_value


def test_write_produces_deterministic_json(tmp_path: Path) -> None:
    a = ProofArtifact("traj-a", tmp_path, metadata={"repo": "gmail-agent", "head": "abc123"})
    a.record("live_send", False).record("full_fresh38", "NOT_RUN")
    a.assert_invariant(True, "intent preserved")
    first = a.write("proof.json")
    second = a.write("proof.json")
    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["summary"]["verdict"] == "PASS"
    assert payload["summary"]["assertions_total"] == 1


def test_failed_invariant_raises_and_records(tmp_path: Path) -> None:
    a = ProofArtifact("traj-b", tmp_path)
    with pytest.raises(AssertionError):
        a.assert_invariant(False, "dropped intent", detail="document_request ignored")
    summary = a.summary()
    assert summary["verdict"] == "FAIL"
    assert summary["assertions_failed"] == 1


def test_redaction_removes_secret_values(tmp_path: Path) -> None:
    a = ProofArtifact("traj-c", tmp_path)
    # Runtime-constructed so the static secret scanner does not flag the test
    # file; at runtime they match the redaction patterns.
    fake_sk = "sk-" + "test-secret-token-1234567890abcdef"
    fake_gh = "ghp_" + "0123456789abcdefghijklmnopqrstuvwxyz"
    a.record(
        "credentials_probe",
        {
            "token": fake_sk,
            "nested": [fake_gh],
            "ok": "customer@example.com",
        },
    )
    target = a.write("proof.json")
    text = target.read_text(encoding="utf-8")
    assert fake_sk not in text
    assert fake_gh not in text
    assert "REDACTED:OpenAI-style secret" in text
    assert "customer@example.com" in text


def test_redact_value_handles_cycles() -> None:
    node: dict = {}
    node["self"] = node
    result = redact_value(node)
    assert result["self"] == "[CYCLE]"


def test_name_required(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ProofArtifact("", tmp_path)
