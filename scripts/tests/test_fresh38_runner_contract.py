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


def test_current_floor_heating_signal_is_preserved_as_context_fact():
    rows = runner._current_fact_rows(
        {
            "floor_heating_existing": True,
            "floor_heating_scope": "parter",
        },
        case_id="FU-07",
        current_signal_id="fresh38-FU-07-current",
    )

    by_key = {row["fact_key"]: row for row in rows}
    assert by_key["floor_heating_existing"]["normalized_value"] == "True"
    assert by_key["floor_heating_scope"]["normalized_value"] == "parter"
    assert all(row["source_ref"] == "fresh38-FU-07-current" for row in rows)


def test_current_message_fact_supersedes_different_prior_value_in_context_pack():
    pack = runner._corpus_context_pack(
        {
            "id": "FU-07",
            "prior_context": {
                "case_summary_pl": "Wycena zakladala brak ogrzewania podlogowego.",
                "prior_facts": {"floor_heating_existing": False},
            },
            "input": {},
        },
        {
            "floor_heating_existing": True,
            "floor_heating_scope": "parter",
        },
    )

    active_by_key = {row["fact_key"]: row for row in pack["active_facts"]}
    assert active_by_key["floor_heating_existing"]["normalized_value"] == "True"
    assert active_by_key["floor_heating_existing"]["source_ref"] == "case_recovery_FU-07_current"
    assert not any(
        row.get("fact_key") == "floor_heating_existing"
        for row in pack["conflicting_facts"]
    )
