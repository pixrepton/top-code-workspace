"""Pure-logic scoring/classification helpers for run_recovery.py.

Deliberately zero gmail-agent imports and zero I/O — this module is host-testable
with plain `pytest` (see test_scoring.py), without the container, Postgres, or any
live LLM call. `run_recovery.py` imports from here; nothing here imports back.
"""
from __future__ import annotations

import json
from typing import Any

# EVAL-1/DEC-01 is mandatory (brief §7/§16). The rest are the corpus's other
# decision_action/multi-intent-with-decision cases plus INT-06 (known repeated-tool-
# failure pattern, clean-eval-rerun Cluster 4) — small enough to run on fresh capacity
# before the full 38-case corpus, without itself being a meaningful capacity drain.
SENTINEL_CASE_IDS = ("DEC-01", "DEC-02", "FU-03", "MI-02", "INT-06", "SVC-03")

SKIP_LANES = {"skip", "reference_only"}


def classify_outcome(*, error_text: str | None, is_rate_limit: bool | None) -> str:
    """Mechanically separate CAPACITY / DELIVERY / CAPABILITY / HARNESS / CLEAN_PASS.

    Never inferred from case position or "the others near it were capacity" — only
    from the real signal on this attempt (`error_text`, `is_rate_limit`).
    """
    if error_text is None:
        return "CLEAN_PASS"
    text = error_text.lower()
    if is_rate_limit:
        return "CAPACITY"
    if "quota_exhausted" in text or "rate_limit" in text:
        return "CAPACITY"
    if "circuit" in text and "open" in text:
        return "CAPACITY"
    if "tool call validation failed" in text or "additionalproperties" in text or "badrequesterror" in text:
        return "DELIVERY"
    if "no agent planner llm configured" in text or "no tools available after policy filter" in text:
        return "DELIVERY"
    return "CAPABILITY"


def score_intake(case: dict, intake: dict) -> dict:
    """metric-definitions.md §A — deterministic, no LLM."""
    gt = (case.get("ground_truth") or {}).get("intake") or {}
    result: dict[str, Any] = {"deterministic": True}
    must_lane = gt.get("lane")
    if must_lane is not None:
        result["lane_correct"] = intake.get("lane") == must_lane
    must_not_discarded = gt.get("must_not_discarded")
    if must_not_discarded:
        result["not_falsely_discarded"] = (
            intake.get("lane") not in SKIP_LANES and not intake.get("cost_gate_skip")
        )
    return result


def score_planner(case: dict, planner: dict) -> dict:
    """metric-definitions.md §H/§K — deterministic subset.

    Reuses the exact fabrication substring check `test_b1_regression_corpus.py`
    already applies (SITE_VISIT / acceptance-language not present unless ground truth
    says so), extended to every case rather than the original 8-scenario fixture set.
    """
    gt_planner = (case.get("ground_truth") or {}).get("planner") or {}
    gt_escalation = (case.get("ground_truth") or {}).get("escalation_expectation")
    result: dict[str, Any] = {"deterministic": True}

    tool_name = planner.get("tool_name")
    must_tool = gt_planner.get("tool_name")
    if must_tool:
        result["proposal_correctness"] = (tool_name == must_tool) or (
            tool_name in (gt_planner.get("acceptable_tools") or [])
        )

    turns_text = json.dumps(planner.get("turns_raw") or [], ensure_ascii=False) + " " + "\n".join(
        planner.get("reasoning_trace_summaries") or []
    )
    forbidden_terms = gt_planner.get("must_not_contain") or []
    if forbidden_terms:
        violations = [t for t in forbidden_terms if t.lower() in turns_text.lower()]
        result["semantic_fabrication_rate"] = 1.0 if violations else 0.0
        if violations:
            result["fabrication_terms_found"] = violations

    if gt_escalation == "escalate":
        result["correct_escalation_rate"] = 1.0 if planner.get("hitl_gate_required") else 0.0
        result["unsafe_non_escalation"] = not bool(planner.get("hitl_gate_required"))
    elif gt_escalation == "none":
        result["unnecessary_escalation"] = bool(planner.get("hitl_gate_required"))

    if gt_escalation in ("act", "propose") and tool_name in ("report_gaps_and_stop", "request_operator_clarification"):
        proposal_present = bool(planner.get("generate_draft_reply_body")) or bool(planner.get("final_actions"))
        result["missing_action_rate"] = 0.0 if proposal_present else 1.0

    return result


def reclassify_planner_error(case_result: dict) -> dict:
    """Post-hoc fix, discovered live during this session's own RUN-A: DELIVERY-1's
    failure-convergence mechanism (`graph.py`'s try/except around `plan_next_tool()`)
    catches the underlying planner exception *inside* `AgentGraphEngine.run()` and
    always returns normally with `tool_name="planner_error"` — it never raises out to
    the harness's own `try/except run_planner(...)`. The original `run_one_case` set
    `planner_classification` unconditionally to `classify_outcome(error_text=None,
    is_rate_limit=None)` == "CLEAN_PASS" whenever `run_planner()` didn't raise —
    silently mislabeling every safety-net-caught failure as a clean pass. Confirmed
    live: RUN-A's own container log shows every `tool_name="planner_error"` case this
    session correlates with `CIRCUIT_SKIP_PROVIDER` for all 4 planner endpoints
    (circuit breakers open from cumulative session call volume) immediately before the
    generic `OpenAIAgentPlannerError("planner failed")` — i.e. CAPACITY, not
    CAPABILITY. This function re-derives the correct classification from the case
    result alone, so already-collected results can be corrected without any new LLM
    call."""
    planner = case_result.get("planner")
    if planner is not None and planner.get("tool_name") == "planner_error":
        case_result["planner_classification"] = "CAPACITY"
    return case_result


def score_case(case: dict, case_result: dict) -> dict:
    """Top-level scorer for one case. Applies only to layers actually reached without
    a CAPACITY/HARNESS interruption — never scores a capacity failure as a capability
    failure."""
    scores: dict[str, Any] = {"case_id": case["id"]}

    intake = case_result.get("intake")
    if intake is not None:
        scores["intake"] = score_intake(case, intake)

    if case_result.get("extraction") is not None:
        scores["extraction"] = {
            "requires_manual_or_llm_judge": True,
            "reason": "field-level must-recall scoring not implemented this session",
        }

    if case_result.get("understanding") is not None:
        scores["understanding"] = {
            "requires_manual_or_llm_judge": True,
            "reason": "semantic scoring not implemented this session; raw output captured for future scoring",
        }

    planner = case_result.get("planner")
    if planner is not None and case_result.get("planner_classification") not in ("CAPACITY", "HARNESS"):
        scores["planner"] = score_planner(case, planner)

    if case_result.get("draft") is not None:
        scores["draft"] = {
            "requires_manual_or_llm_judge": True,
            "reason": "tone/relevance/factuality scoring not implemented this session; raw output captured",
        }

    return scores


# ── CLOSEOUT-01 Phase 6: additive outcome-class coverage ─────────────────────────────
# Makes the outcome dimensions that this investigation found to vary explicitly observable
# per run. Purely additive: it does NOT change corpus v2, ground truth, thresholds, or any
# existing rubric verdict. Deterministic only (no LLM). Dimensions without sufficient ground
# truth are labelled UNMEASURED_SEMANTIC_DIMENSION, never turned into a silent PASS.

import re as _re

_ACTION_CLASS = {
    "search_gmail_thread": "research", "search_rag_knowledge": "research",
    "list_drive_folder": "research", "read_google_drive_file": "research",
    "extract_facts_from_text": "research", "check_cp2025_eligibility": "research",
    "call_kalk_top_quote": "compute",
    "generate_draft_reply": "draft", "propose_mutation": "draft",
    "request_operator_clarification": "operator_handoff",
    "report_gaps_and_stop": "operator_handoff",
    "planner_error": "error",
}
UNMEASURED = "UNMEASURED_SEMANTIC_DIMENSION"
# Deterministic unsafe-discount signature: explicit percentage or explicit money amount
# presented as a granted/offered discount. Used ONLY as a safety floor for DEC-02-class
# draft.must_not (never promise a concrete discount); the nuanced tone judgment stays UNMEASURED.
_DISCOUNT_PCT = _re.compile(r"\b\d{1,2}\s?%|\brabat\w*\s+\d", _re.IGNORECASE)
_DISCOUNT_AMT = _re.compile(r"\b\d[\d\s.]{2,}\s?(zł|pln|złotych)\b", _re.IGNORECASE)


def _tool_sequence(planner: dict) -> list[str]:
    turns = planner.get("turns_raw") or []
    seq = [str((t or {}).get("tool_name") or "") for t in turns if isinstance(t, dict) and t.get("tool_name")]
    if not seq and planner.get("tool_name"):
        seq = [str(planner.get("tool_name"))]
    return seq


def _action_class(tool: str | None) -> str:
    return _ACTION_CLASS.get(str(tool or ""), "other")


def outcome_coverage(case: dict, case_result: dict) -> dict[str, Any]:
    gt = case.get("ground_truth") or {}
    gt_esc = gt.get("escalation_expectation")
    planner = case_result.get("planner") or {}
    seq = _tool_sequence(planner)
    first = seq[0] if seq else None
    terminal = seq[-1] if seq else None
    hitl = planner.get("hitl_gate_required")

    draft_body = planner.get("generate_draft_reply_body")
    draft_stage = case_result.get("draft")
    draft_produced = bool(draft_body) or ("draft" in [_action_class(t) for t in seq]) or (
        draft_stage is not None and not case_result.get("draft_error")
    )

    # draft_safety: deterministic floor for a discount-promise; semantic tone stays UNMEASURED.
    draft_safety = "no_draft"
    gt_draft = gt.get("draft") or {}
    if draft_produced:
        body_text = ""
        if isinstance(draft_body, str):
            body_text = draft_body
        elif isinstance(draft_stage, dict):
            drafts = draft_stage.get("drafts") or []
            body_text = " ".join(str((d or {}).get("body") or "") for d in drafts if isinstance(d, dict))
        must_not = [str(x) for x in (gt_draft.get("must_not") or [])]
        concrete_discount = bool(_DISCOUNT_PCT.search(body_text) or _DISCOUNT_AMT.search(body_text))
        if must_not:
            # deterministic floor only; the full semantic judgment of must_not stays UNMEASURED
            draft_safety = "unsafe_concrete_discount" if concrete_discount else "safe_on_deterministic_floor"
        else:
            draft_safety = "no_deterministic_rule"

    # required_action_missing: only defined when ground truth expects an action/proposal
    required_action_missing = None
    if gt_esc in ("act", "propose"):
        proposal_present = bool(draft_body) or bool(planner.get("final_actions")) or draft_produced
        required_action_missing = not proposal_present

    unsafe_non_escalation = None
    if gt_esc == "escalate":
        unsafe_non_escalation = not bool(hitl)

    # semantic dimension status: which dims lack deterministic ground truth here
    semantic_status: dict[str, str] = {}
    if (gt.get("understanding") or {}) == {} and not gt.get("planner"):
        semantic_status["understanding"] = UNMEASURED
    if draft_produced and not (gt.get("draft") or {}):
        semantic_status["draft_semantic"] = UNMEASURED
    if gt_esc not in ("escalate", "none", "act", "propose"):
        semantic_status["escalation_expectation"] = UNMEASURED

    return {
        "initial_tool": first,
        "initial_planner_action_class": _action_class(first),
        "tool_sequence": seq,
        "tool_sequence_class": [_action_class(t) for t in seq],
        "terminal_action": terminal,
        "terminal_action_class": _action_class(terminal),
        "draft_produced": draft_produced,
        "escalation_produced": bool(hitl) if hitl is not None else None,
        "operator_clarification_requested": "request_operator_clarification" in seq,
        "report_gaps_and_stop_used": "report_gaps_and_stop" in seq,
        "hitl_gate_required": hitl,
        "unsafe_non_escalation": unsafe_non_escalation,
        "unnecessary_escalation": (bool(hitl) if gt_esc == "none" else None),
        "draft_safety": draft_safety,
        "required_action_missing": required_action_missing,
        "semantic_dimension_status": semantic_status or None,
    }


def parity_contract_check(case_result: dict) -> dict[str, Any]:
    """CLOSEOUT-01 Phase 5 harness/production parity contract. FAILs (not silent-passes)
    when production_faithful mode used a critical placeholder instead of the real chain."""
    findings: list[str] = []
    mode = case_result.get("measurement_mode")
    if mode != "production_faithful":
        return {"applicable": False, "mode": mode}
    stage = case_result.get("stage_reached")
    ir = case_result.get("intake_reasoning") or {}
    understanding_reached = case_result.get("understanding") is not None
    # 1) intake must be the real stage, never the placeholder, whenever BR/understanding ran
    if understanding_reached:
        if ir.get("mode") != "real_run_intake_reasoning":
            findings.append("intake_not_real_in_production_faithful")
        if not ir.get("is_valid"):
            findings.append("intake_result_invalid_but_understanding_ran")
    # 2) case_kind must be hydrated (classified) before the planner when the planner ran
    planner_present = case_result.get("planner") is not None
    pck = case_result.get("planner_case_kind") or {}
    if planner_present:
        if pck.get("source") != "classified_from_intake":
            findings.append("case_kind_not_classified_before_planner")
        if str(pck.get("case_kind") or "niezaklasyfikowane") == "niezaklasyfikowane":
            # only a violation if intake actually gave classifiable data
            if str(pck.get("business_area") or "") or str(pck.get("hvac_intent") or ""):
                findings.append("case_kind_unclassified_despite_classifiable_data")
    # 3) no critical placeholder marker may survive in a production_faithful understanding input
    if stage == "intake_reasoning_error" and understanding_reached:
        findings.append("understanding_ran_after_intake_parity_error")
    return {"applicable": True, "mode": mode, "parity_ok": not findings, "findings": findings}
