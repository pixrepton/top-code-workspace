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


def test_run_draft_does_not_fabricate_reply_eligibility():
    result = runner.run_draft(object(), {"source_message": {"sender": "klient@example.com"}})
    decision = (result.get("causal_observability") or {}).get("draft_gate") or {}
    inputs = decision.get("decision_inputs") or {}
    assert result.get("skipped") == "fabricated_eligibility_disabled"
    assert result.get("draft_enabled") is False
    assert inputs.get("intake_action") != "reply"
    assert "reply" not in str((result.get("execution_metadata") or {}).get("error") or "")


def test_production_faithful_does_not_call_fabricated_draft_when_understanding_fails(monkeypatch):
    calls = {"run_draft": 0}

    monkeypatch.setattr(runner, "build_snapshot", lambda _case: {"source_message": {"sender": "k@example.com"}})
    monkeypatch.setattr(
        runner,
        "run_intake",
        lambda _case, _snapshot: {
            "lane": "intake_llm",
            "lane_full": {"lane": "intake_llm"},
            "cost_gate_skip": False,
        },
    )
    monkeypatch.setattr(runner, "run_extraction", lambda _settings, _snapshot: {"hvac_intent": "awaria"})
    monkeypatch.setattr(
        runner,
        "compute_real_intake_result",
        lambda _settings, _snapshot, _preclass: {
            "intake_result_final": {"decision": {"action": "create_case"}, "review_required": True, "business_area": "service"},
            "is_valid": True,
            "final_output_origin": "raw",
            "intake_result_hash": "abc",
            "request_meta": {},
            "raw_valid": True,
            "normalized_valid": True,
            "repaired_valid": True,
            "guardrail_error": None,
        },
    )
    monkeypatch.setattr(
        runner,
        "derive_production_case_kind",
        lambda *_args, **_kwargs: {"case_kind": "awaria_naprawa", "source": "classified_from_intake"},
    )

    def _boom(*_args, **_kwargs):
        raise RuntimeError("understanding unavailable")

    monkeypatch.setattr(runner, "run_understanding", _boom)
    monkeypatch.setattr(
        runner,
        "run_planner",
        lambda *_args, **_kwargs: {"tool_name": "none", "envelope_presence": {"status": "absent"}, "plan_correlation_statuses": []},
    )

    def _spy_draft(*_args, **_kwargs):
        calls["run_draft"] += 1
        raise AssertionError("fabricated run_draft must not run")

    monkeypatch.setattr(runner, "run_draft", _spy_draft)
    monkeypatch.setattr(runner, "score_case", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "outcome_coverage", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(runner, "reclassify_planner_error", lambda case_result: case_result)

    case = {
        "id": "SVC-05",
        "categories": ["service_problem"],
        "input": {"subject": "nie dziala", "body": "fixture"},
        "ground_truth": {"draft_expected": True},
    }
    result = runner.run_one_case(case, mode="production_faithful", settings=object(), agent_settings=object())

    assert calls["run_draft"] == 0
    assert result.get("draft_skipped_reason") == "no_brain1_draft_no_fabricated_fallback"
    assert not isinstance(result.get("draft"), dict) or result.get("draft", {}).get("skipped") == "fabricated_eligibility_disabled"


def test_run_understanding_projects_review_required_and_attempt_run_id(monkeypatch):
    monkeypatch.setenv("FRESH38_ATTEMPT_ID", "attempt-xyz")
    seen = {}

    monkeypatch.setattr(runner, "_corpus_context_pack", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "_pf_build_context_bundle", lambda *_args, **_kwargs: {"case_id": "case_recovery_SVC-05"})

    def _fake_br(*_args, **_kwargs):
        return {
            "recommended_next_action": "escalate_review",
            "reply_recommended": False,
            "customer_state_guess": "waiting",
            "business_area": "service",
            "human_review_bias": "high",
            "confidence": {"business_confidence": 0.4, "action_confidence": 0.3},
        }

    def _fake_draft(_snapshot, intake_result, _business, _context, config):
        seen["run_id"] = config.get("run_id")
        seen["review_required"] = intake_result.get("review_required")
        return {
            "draft_enabled": False,
            "drafts": [],
            "causal_observability": {
                "schema_version": "draft_path_observability.v1",
                "lineage": {"run_id": config.get("run_id")},
            },
        }

    monkeypatch.setattr(
        "gmail_intake.run_business_reasoning",
        _fake_br,
        raising=False,
    )
    monkeypatch.setattr("gmail_intake.draft_reply", _fake_draft, raising=False)
    monkeypatch.setattr("gmail_intake.plan_actions", lambda *_a, **_k: {"primary_action": "create_task"}, raising=False)
    monkeypatch.setattr(
        "gmail_intake.build_case_intelligence_layer",
        lambda *_a, **_k: {"next_best_action": {}, "case_understanding": {}, "understanding_output": {}},
        raising=False,
    )

    capture: dict = {}
    intake_override = {
        "decision": {"action": "create_case"},
        "review_required": True,
        "business_area": "service",
    }
    runner.run_understanding(
        object(),
        {"source_message": {}},
        {"lane": "intake_llm"},
        {"id": "SVC-05", "input": {}},
        {},
        intake_result_override=intake_override,
        capture=capture,
    )
    assert capture["business_reasoning"]["review_required"] is True
    assert capture["business_reasoning"]["reply_recommended"] is False
    assert seen.get("run_id") == "attempt-xyz"
    assert capture.get("causal_observability", {}).get("lineage", {}).get("run_id") == "attempt-xyz"


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
