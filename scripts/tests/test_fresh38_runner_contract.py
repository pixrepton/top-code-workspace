import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKSPACE / "gmail-agent" / "tools" / "gmail_audit"))
sys.path.insert(0, str(WORKSPACE))

from scripts.fresh38 import run_recovery_pf as runner  # noqa: E402


def test_production_faithful_invalid_intake_is_product_failure_capture(monkeypatch):
    case = {
        "id": "MI-03",
        "categories": ["multi_intent", "service_problem"],
        "input": {"subject": "reklamacja i nowe zapytanie", "body": "fixture"},
    }

    monkeypatch.setattr(runner, "build_snapshot", lambda _case: {"source_message": {}})
    monkeypatch.setattr(
        runner,
        "run_intake",
        lambda _case, _snapshot: {
            "lane": "intake_llm",
            "lane_full": {"lane": "intake_llm"},
            "cost_gate_skip": False,
        },
    )
    monkeypatch.setattr(runner, "run_extraction", lambda _settings, _snapshot: {"hvac_intent": "wycena_oferta"})
    monkeypatch.setattr(
        runner,
        "compute_real_intake_result",
        lambda _settings, _snapshot, _preclass: {
            "intake_result_final": None,
            "is_valid": False,
            "final_output_origin": "invalid",
            "intake_result_hash": None,
            "request_meta": {},
            "raw_valid": False,
            "normalized_valid": False,
            "repaired_valid": False,
            "guardrail_error": None,
        },
    )

    result = runner.run_one_case(case, mode="production_faithful", settings=object(), agent_settings=object())

    assert result["stage_reached"] == "intake_reasoning_error"
    assert "parity_error" not in result
    assert result["case_product_outcome"] == "CASE_PRODUCT_FAIL"
    assert result["terminal_product_result"]["reason"] == "intake_result_final_missing"
    assert result["capture_integrity"]["status"] == "CASE_CAPTURE_SUCCESS"


def test_atomic_capture_writer_reopens_and_validates_terminal_artifact(tmp_path):
    out = tmp_path / "one-MI-03.json"
    payload = {
        "mode": "production_faithful",
        "sentinel_only": False,
        "cases": [{"id": "MI-03", "stage_reached": "full"}],
    }

    runner.write_canonical_capture_artifact(out, payload, expected_case_ids=["MI-03"])

    assert out.exists()
    assert not list(tmp_path.glob(".*.tmp"))
    assert runner.json.loads(out.read_text(encoding="utf-8"))["cases"][0]["id"] == "MI-03"


def test_atomic_capture_writer_rejects_missing_terminal_state(tmp_path):
    out = tmp_path / "one-MI-03.json"
    payload = {
        "mode": "production_faithful",
        "sentinel_only": False,
        "cases": [{"id": "MI-03"}],
    }

    try:
        runner.write_canonical_capture_artifact(out, payload, expected_case_ids=["MI-03"])
    except runner.HarnessCaptureContractError as exc:
        assert "missing_terminal_state" in str(exc)
    else:
        raise AssertionError("missing terminal state was accepted")
    assert not out.exists()
