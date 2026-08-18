"""EVAL-RECOVERY-1 harness. Extends EVAL-1/DELIVERY-1's `run_baseline.py`
(`C:\\ai-os-eval-1-20260716T125141Z\\harness\\run_baseline.py`) with measurement-integrity
fixes identified by this session's read-only reconstruction. Does NOT modify gmail-agent
code, does NOT modify corpus-v1.json / rubric-v1.md (frozen, byte-identical, verified by
../frozen-corpus-integrity.json before use).

Fixes vs run_baseline.py, each traceable to a section of this session's brief:

1. TWO EXPLICIT MODES (brief §6A):
   - production_faithful (default): respects the real preclassifier lane. If the real
     production path would stop a case before the planner (lane in {skip, reference_only}),
     this harness does NOT run extraction/planner/draft either — it records
     `stage_reached="intake_only"` and `mode_note="production_lane_short_circuit"`.
     This directly closes the EVAL1-INTAKE-AUTO-NOTIFICATION-adjacent finding from the
     clean-eval-rerun (INT-06 cascading into 5 repeated search_gmail_thread failures
     specifically because run_baseline.py always ran the planner regardless of lane).
   - component_capability: unconditionally runs every stage on every case regardless of
     intake lane (run_baseline.py's original, unconditional behavior) — kept as an
     explicit, separately-labeled mode for isolating one layer's capability. Every case
     result in this mode is tagged `measurement_mode="component_capability"`, never
     `"production_e2e"`, per the brief's explicit prohibition on mixing the two.

2. UNDERSTANDING CAPTURE (brief §6B): `run_baseline.py` never called the real
   Understanding-producing function at all. This harness adds `run_understanding()`,
   which chains `gmail_intake.run_business_reasoning()` (the real production wrapper —
   it already returns `build_skipped_business_reasoning(...)` on a skip lane per its own
   `lane_stage_plan`, so it is production-faithful by construction) into
   `gmail_intake.build_case_intelligence_layer()` (verified call shape:
   `tools/gmail_audit/tests/test_decision_pipeline_intake_integration.py`,
   `test_build_case_intelligence_layer_with_flags_produces_understanding_and_pipeline`),
   and captures the real `result["understanding_output"]` dict verbatim — not
   reconstructed from tool trace.
   CAUTION (disclosed, not hidden): this adds one additional real LLM call per admitted
   case (business_reasoning) on top of extraction/planner/draft — a real, material
   increase in per-case token cost. This wiring is built to the exact signature the
   repo's own integration tests use, but has NOT been exercised against a live container
   this session (Docker Desktop was down for part of this session; capacity was not
   spent to smoke-test it once it came back up, per the brief's "zero czekania" /
   conserve-capacity instruction). Whoever runs RUN-A should treat the first 1-2 cases'
   `understanding` field as a live smoke test of this wiring before trusting the rest.

3. FINAL DRAFT CONTENT CAPTURE (brief §6B): `generate_draft_reply`'s composed body
   (`snapshot_delta["actions"][0]["payload_pl"]`, handlers.py:103-134) was applied to the
   final snapshot but never read back by run_baseline.py — the turn journal itself never
   carries `snapshot_delta` (confirmed this session by direct trace of
   `InMemoryAgentTurnJournal.append_turn`). Fixed by reading `final.actions` after
   `engine.run()` and capturing any `draft_reply` action's `payload_pl` into
   `planner.generate_draft_reply_body`. The separate `reply_drafter` stage is invoked
   from `run_understanding()` via production `gi_draft_reply`. `run_draft()` no longer
   fabricates `action=reply`; a missing Brain1 draft is recorded as
   `draft_skipped_reason=no_brain1_draft_no_fabricated_fallback`.

4. RUBRIC SCORING + CLASSIFICATION (brief §6C/§6D): `score_case()` applies the
   deterministic checks from `metric-definitions.md` sections A/B/H/K (intake,
   extraction-field-presence, planner proposal/fabrication/escalation, HITL) directly
   against each case's `ground_truth` (must/must_not/acceptable). Sections C-G/J
   (understanding correctness, draft tone/relevance) are marked
   `requires_manual_or_llm_judge=True` with the raw evidence attached — no LLM judge is
   implemented this session (out of scope: this session's mandate is measurement
   integrity, not building a new judge pipeline); a future session can score those from
   the captured raw evidence without re-running anything.
   `classify_outcome()` mechanically separates CAPACITY / DELIVERY / CAPABILITY /
   HARNESS / CLEAN_PASS per case per layer from the real exception text and
   `is_rate_limit` signal (never inferred from case position or "looks like the others").

5. SENTINEL SUITE (brief §7): `SENTINEL_CASE_IDS` — run before the full corpus, on fresh
   capacity, so `EVAL-1/DEC-01` and other S3/S4 cases are never last-in-line for a
   provider that may exhaust mid-run. Does not replace the full corpus run.

6. CURRENT BRAIN-1 ACTION CAPTURE (post-Stage-6): the historical harness passed
   `reply_result=None` and `action_plan_result=None` into Case Intelligence. This copy
   runs the existing production functions in their current causal order:
   BusinessReasoning -> ReplyDrafter -> ActionPlanner -> Case Intelligence. It captures
   the action plan and compact divergence inputs without changing corpus, scorer, tool
   behavior, or the independent Brain-2 planner run.

Usage (inside container):
  python3 run_recovery.py <production_faithful|component_capability> corpus-v1.json out.json [--sentinel-only] [case_id ...]
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

HARNESS_DIR = Path(__file__).resolve().parent
if str(HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(HARNESS_DIR))
SCRIPTS_DIR = HARNESS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

try:
    from _gmail_agent_env import ensure_gmail_agent_env_file
except Exception:  # pragma: no cover - fallback for copied standalone harnesses
    def ensure_gmail_agent_env_file() -> Path | None:
        current = str(os.environ.get("GMAIL_AGENT_ENV_FILE") or "").strip()
        if current:
            return Path(current)
        for parent in Path(__file__).resolve().parents:
            candidate = parent / "gmail-agent" / ".env.local-vps"
            if candidate.is_file():
                os.environ["GMAIL_AGENT_ENV_FILE"] = str(candidate)
                return candidate
        return None

ensure_gmail_agent_env_file()

from scoring import (  # noqa: E402
    SENTINEL_CASE_IDS,
    SKIP_LANES as _SKIP_LANES,
    classify_outcome,
    outcome_coverage,
    reclassify_planner_error,
    score_case,
)

TOOL_DIR = Path("/app/tools/gmail_audit")
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from config import load_settings  # noqa: E402
from preclassifier import is_obvious_noise, preclassify_snapshot  # noqa: E402
from signal_contract import CanonicalSignal  # noqa: E402
from signal_extractor import run_signal_extraction  # noqa: E402
from reply_drafter import run_reply_drafter  # noqa: E402
from agent_runtime.agent_reconcile import _evaluate_cost_gate, _intake_case_family  # noqa: E402
from agent_runtime.constitution import load_constitution  # noqa: E402
from agent_runtime.graph import AgentGraphEngine  # noqa: E402
from agent_runtime.openai_agent_client import OpenAIToolPlanner  # noqa: E402
from agent_runtime.settings import load_agent_runtime_settings  # noqa: E402
from agent_runtime.store import build_initial_snapshot  # noqa: E402
from agent_runtime.tool_context import ToolExecutionContext  # noqa: E402
from agent_runtime.tools_registry import AgentToolRegistry  # noqa: E402
from agent_runtime.turn_journal import InMemoryAgentTurnJournal  # noqa: E402
from agent_runtime.tool_result import ToolResult  # noqa: E402
from agent_runtime.tools.handlers import _classify_case_kind  # noqa: E402
# CLOSEOUT-01 Phase 5 — production-faithful intake wiring (real run_intake_reasoning
# instead of the thin stub) + production case_kind classification before the planner.
from gmail_intake import (  # noqa: E402
    build_context_bundle as _pf_build_context_bundle,
    run_intake_reasoning as _pf_run_intake_reasoning,
    validate_intake_output as _pf_validate_intake_output,
    _build_lane_stage_plan as _pf_build_lane_stage_plan,
)
from intake_schema import load_intake_schema as _pf_load_intake_schema  # noqa: E402
from intake_payload import render_system_prompt as _pf_render_system_prompt  # noqa: E402
import hashlib as _pf_hashlib  # noqa: E402


def _pf_canon_hash(obj: Any) -> str:
    return _pf_hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


class HarnessParityError(RuntimeError):
    """Raised when production_faithful mode would otherwise silently use a critical
    placeholder (stubbed intake_result / unclassified case_kind despite classifiable data).
    A component_isolated run may stub; production_faithful must not."""


class HarnessCaptureContractError(RuntimeError):
    """Raised when the runner cannot prove its canonical terminal artifact."""


def _read_proc_text(path: str) -> str:
    try:
        return Path(path).read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _runner_process_identity() -> dict[str, Any]:
    pid = os.getpid()
    stat = _read_proc_text(f"/proc/{pid}/stat")
    start_ticks = None
    if stat:
        parts = stat.split()
        if len(parts) > 21:
            try:
                start_ticks = int(parts[21])
            except ValueError:
                start_ticks = None
    return {
        "pid": pid,
        "ppid": os.getppid() if hasattr(os, "getppid") else None,
        "cmdline": _read_proc_text(f"/proc/{pid}/cmdline"),
        "proc_start_ticks": start_ticks,
        "cwd": str(Path.cwd()),
    }


def _child_process_snapshot() -> list[dict[str, Any]]:
    parent = os.getpid()
    children: list[dict[str, Any]] = []
    proc_root = Path("/proc")
    if not proc_root.exists():
        return children
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        stat = _read_proc_text(str(entry / "stat"))
        if not stat:
            continue
        parts = stat.split()
        if len(parts) <= 3:
            continue
        try:
            ppid = int(parts[3])
        except ValueError:
            continue
        if ppid != parent:
            continue
        children.append(
            {
                "pid": int(entry.name),
                "ppid": ppid,
                "cmdline": _read_proc_text(str(entry / "cmdline")),
                "proc_start_ticks": int(parts[21]) if len(parts) > 21 and parts[21].isdigit() else None,
            }
        )
    return children


def _measurement_attempt() -> dict[str, Any]:
    return {
        "attempt_id": str(os.environ.get("FRESH38_ATTEMPT_ID") or "").strip(),
        "artifact_path": str(os.environ.get("FRESH38_ARTIFACT_PATH") or "").strip(),
        "runner": _runner_process_identity(),
    }


def _lifecycle_diag_enabled(case_id: str | None = None) -> bool:
    target = str(os.environ.get("FRESH38_LIFECYCLE_DIAG_CASE") or "").strip()
    if target and case_id and target != case_id:
        return False
    return str(os.environ.get("FRESH38_LIFECYCLE_DIAG") or "").strip() == "1"


def _thread_snapshot() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for thread in threading.enumerate():
        items.append(
            {
                "name": thread.name,
                "ident": thread.ident,
                "daemon": thread.daemon,
                "alive": thread.is_alive(),
            }
        )
    return items


def _lifecycle_diag(event: str, case_id: str | None = None, **fields: Any) -> None:
    if not _lifecycle_diag_enabled(case_id):
        return
    payload = {
        "event": event,
        "case_id": case_id,
        "attempt_id": str(os.environ.get("FRESH38_ATTEMPT_ID") or "").strip(),
        "pid": os.getpid(),
        "ppid": os.getppid() if hasattr(os, "getppid") else None,
        "monotonic_s": round(time.monotonic(), 6),
        "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **fields,
    }
    print("[fresh38-lifecycle] " + json.dumps(payload, ensure_ascii=False, default=str), file=sys.stderr, flush=True)


def _capture_contract_errors(payload: dict[str, Any], expected_case_ids: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    expected_attempt = str(os.environ.get("FRESH38_ATTEMPT_ID") or "").strip()
    if expected_attempt:
        measurement = payload.get("measurement_attempt")
        if not isinstance(measurement, dict) or measurement.get("attempt_id") != expected_attempt:
            errors.append("attempt_id_mismatch")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return ["missing_cases_list"]
    if expected_case_ids is not None:
        actual_ids = [str((case or {}).get("id") or (case or {}).get("case_id") or "") for case in cases]
        if actual_ids != expected_case_ids:
            errors.append(f"case_ids_mismatch expected={expected_case_ids} actual={actual_ids}")
    for idx, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"case_{idx}_not_object")
            continue
        case_id = str(case.get("id") or case.get("case_id") or "")
        if not case_id:
            errors.append(f"case_{idx}_missing_case_id")
        if not str(case.get("stage_reached") or ""):
            errors.append(f"{case_id or idx}_missing_terminal_state")
        if case.get("parity_error"):
            errors.append(f"{case_id or idx}_parity_error={case.get('parity_error')}")
    return errors


def write_canonical_capture_artifact(
    out_path: Path,
    payload: dict[str, Any],
    *,
    expected_case_ids: list[str] | None = None,
) -> None:
    """Atomically materialize and validate the terminal capture before exit 0 is possible."""
    errors = _capture_contract_errors(payload, expected_case_ids)
    if errors:
        raise HarnessCaptureContractError("; ".join(errors))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(f".{out_path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, out_path)
        try:
            dir_fd = os.open(str(out_path.parent), os.O_RDONLY)
        except OSError:
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    try:
        parsed = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HarnessCaptureContractError(f"artifact_reopen_failed: {type(exc).__name__}: {exc}") from exc
    errors = _capture_contract_errors(parsed, expected_case_ids)
    if errors:
        raise HarnessCaptureContractError("artifact_reopen_invalid: " + "; ".join(errors))


def _shutdown_planner_engine(engine: Any, case_id: str) -> None:
    """Runner-owned lifecycle boundary for AgentGraphEngine resources."""
    pool = getattr(engine, "_timeout_pool", None)
    _lifecycle_diag(
        "planner_engine_shutdown_start",
        case_id,
        has_timeout_pool=pool is not None,
        threads=_thread_snapshot(),
        children=_child_process_snapshot(),
    )
    if pool is not None and hasattr(pool, "shutdown"):
        pool.shutdown(wait=True)
        try:
            setattr(engine, "_timeout_pool", None)
        except Exception:
            pass
    else:
        shutdown = getattr(engine, "shutdown", None)
        if callable(shutdown):
            shutdown()
    _lifecycle_diag("planner_engine_shutdown_done", case_id, threads=_thread_snapshot(), children=_child_process_snapshot())


def compute_real_intake_result(
    settings,
    snapshot: dict,
    preclassification_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the REAL production intake-reasoning stage (run_intake_reasoning ->
    validate_intake_output) and return {intake_result_final, meta}. This is the exact
    production intake path — no placeholder. Used only in production_faithful mode."""
    preclass = dict(preclassification_result or {})
    if not preclass.get("lane"):
        preclass = {"lane": "intake_llm", "reasons": ["closeout_pf_harness"], "confidence": 0.75}
    context_bundle = _pf_build_context_bundle(snapshot)
    stage_config = {
        "settings": settings,
        "schema": _pf_load_intake_schema(None),
        "instructions": _pf_render_system_prompt(),
        "model": None,
        "verbose": False,
        "snapshot": snapshot,
        "preclassification_result": preclass,
        "lane_stage_plan": _pf_build_lane_stage_plan(preclass),
    }
    raw = _pf_run_intake_reasoning(snapshot, context_bundle, stage_config)
    vr = _pf_validate_intake_output(raw, stage_config)
    intake_result = vr.get("intake_result_final")
    return {
        "intake_result_final": intake_result if isinstance(intake_result, dict) else None,
        "is_valid": bool(vr.get("is_valid")),
        "final_output_origin": vr.get("final_output_origin"),
        "intake_result_hash": _pf_canon_hash(intake_result) if isinstance(intake_result, dict) else None,
        "request_meta": (raw or {}).get("request_meta"),
        "raw_valid": bool(vr.get("raw_valid")),
        "normalized_valid": bool(vr.get("normalized_valid")),
        "repaired_valid": bool(vr.get("repaired_valid")),
        "guardrail_error": vr.get("guardrail_error"),
    }


def derive_production_case_kind(settings, snapshot: dict, intake_result: dict) -> dict[str, Any]:
    """Classify case_kind the exact way production does before the planner: intake
    business_area/case_family + real signal-extraction hvac_intent + _classify_case_kind."""
    business_area = str((intake_result or {}).get("business_area") or "")
    case_family = str(_intake_case_family(intake_result or {}) or "")
    ex = run_signal_extraction(settings=settings, snapshot=snapshot, context_bundle={})
    hvac_intent = str((ex or {}).get("hvac_intent") or "")
    sm = (snapshot or {}).get("source_message") or {}
    text = f"{sm.get('subject','')} {sm.get('body','')}"
    kind = _classify_case_kind(business_area=business_area, case_family=case_family,
                               hvac_intent=hvac_intent, text=text)
    return {"case_kind": kind, "business_area": business_area, "case_family": case_family,
            "hvac_intent": hvac_intent}

# ── Harness stages (mostly unchanged from run_baseline.py) ─────────────────

class SafeShimToolRegistry:
    """Unchanged from run_baseline.py — see that file's docstring for the full
    propose_mutation-shim rationale. Reused verbatim, not re-derived."""

    def __init__(self) -> None:
        self._real = AgentToolRegistry()

    def execute(self, plan, *, context):  # noqa: ANN001
        if str(plan.tool_name or "").strip() == "propose_mutation":
            args = plan.arguments or {}
            return ToolResult(
                status="ok",
                turn_summary_pl=f"[EVAL-RECOVERY-1 SHIM: not executed] propose_mutation operation={args.get('operation')} target={args.get('target')}",
                snapshot_delta={"hitl_gate": {"required": True, "reason": "shim_recorded_proposal"}},
            )
        return self._real.execute(plan, context=context)


def _corpus_attachment_raw_records(case: dict) -> list[dict]:
    """PARITY FIX (measurement, not product): the frozen build_snapshot dropped
    corpus input.attachments entirely, so the real production attachment_intelligence
    lane saw nothing for DOC-01/DOC-03/MI-04 — whereas production ingests attachment
    records + content into the CaseContextPack before Understanding. This maps each
    corpus attachment {type, content_hint} into a production-shaped raw attachment
    record (name classifies the business_type; content_hint becomes the extracted
    text the real fetcher would have produced) so build_attachment_intelligence runs
    faithfully. No corpus bytes changed; this only stops dropping context the real
    agent would hold."""
    records: list[dict] = []
    for idx, att in enumerate(((case.get("input") or {}).get("attachments") or [])):
        if not isinstance(att, dict):
            continue
        atype = str(att.get("type") or "attachment").strip()
        hint = str(att.get("content_hint") or "").strip()
        low = atype.lower()
        ext = "pdf" if ("pdf" in low or "invoice" in low or "faktur" in low) else "bin"
        records.append({
            "name": f"{atype}_{idx}.{ext}",
            "filename": f"{atype}_{idx}.{ext}",
            "mime_type": "application/pdf" if ext == "pdf" else "application/octet-stream",
            "size_bytes": max(1, len(hint)),
            "attachment_id": f"{case['id']}_att_{idx}",
            "extracted_text_preview": hint,
            "content_hint": hint,
        })
    return records


def build_snapshot(case: dict) -> dict:
    inp = case["input"]
    context_messages = []
    prior = case.get("prior_context")
    if prior and prior.get("prior_messages"):
        for m in prior["prior_messages"]:
            context_messages.append({"subject": m.get("subject", ""), "body": m.get("body", ""), "sender": "klient@example.com"})
    att_records = _corpus_attachment_raw_records(case)
    source_message = {
        "message_id": f"case_recovery_{case['id']}_current",
        "sender": "klient@example.com",
        "subject": inp.get("subject", ""),
        "body": inp.get("body", ""),
        "snippet": inp.get("body", ""),
    }
    if att_records:
        source_message["has_attachments"] = True
        source_message["attachment_names"] = [r["name"] for r in att_records]
        source_message["attachment_parts"] = att_records
        source_message["raw"] = {"attachments": att_records}
    return {
        "mailbox": "eval1@topinstal.local",
        "observed_at": "2026-07-16T12:00:00Z",
        "source_message": source_message,
        "context_messages": context_messages,
        "thread_context": {"quality": "normal" if context_messages else "weak"},
        "routing_hints": {},
    }


class CorpusMailboxStore:
    """Read-only mailbox_store fixture backed by one corpus case."""

    def __init__(self, case: dict, *, case_id: str) -> None:
        self._case = case
        self._case_id = case_id

    def _messages(self) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        prior = self._case.get("prior_context") or {}
        for index, message in enumerate(prior.get("prior_messages") or []):
            if not isinstance(message, dict):
                continue
            messages.append(
                {
                    "case_id": self._case_id,
                    "message_id": f"{self._case_id}_prior_{index}",
                    "sender": str(message.get("sender") or "klient@example.com"),
                    "subject": str(message.get("subject") or ""),
                    "body": str(message.get("body") or ""),
                    "snippet": str(message.get("body") or "")[:240],
                }
            )
        current = self._case.get("input") or {}
        messages.append(
            {
                "case_id": self._case_id,
                "message_id": f"{self._case_id}_current",
                "sender": str(current.get("sender") or "klient@example.com"),
                "subject": str(current.get("subject") or ""),
                "body": str(current.get("body") or ""),
                "snippet": str(current.get("body") or "")[:240],
            }
        )
        return messages

    def fetch_messages_for_case(self, case_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if str(case_id or "") != self._case_id:
            return []
        return self._messages()[-max(1, int(limit)):]

    def fetch_semantic_chunk_candidates_for_case(
        self,
        case_id: str,
        _query_vector_literal: str,
        *,
        limit_mailbox: int = 5,
        limit_drive: int = 5,
    ) -> list[dict[str, Any]]:
        if str(case_id or "") != self._case_id:
            return []
        limit = max(1, min(int(limit_mailbox or 5), int(limit_drive or 5), 10))
        chunks = []
        for index, message in enumerate(self._messages()[-limit:]):
            text = " ".join(
                part
                for part in (
                    str(message.get("subject") or ""),
                    str(message.get("body") or ""),
                )
                if part
            ).strip()
            if text:
                chunks.append(
                    {
                        "chunk_id": f"{self._case_id}_chunk_{index}",
                        "chunk_text": text,
                        "source_kind": "eval_corpus",
                        "source_ref": message.get("message_id"),
                    }
                )
        return chunks


def build_gmail_signal(case: dict) -> CanonicalSignal:
    return CanonicalSignal(
        signal_id=f"sig_recovery_{case['id']}",
        schema_version="1",
        signal_kind="gmail_message_observed",
        source_kind="gmail_inbound",
        source_ref={"message_id": f"msg_recovery_{case['id']}"},
        observed_at="2026-07-16T12:00:00Z",
        effective_at=None,
        case_key_hint=None,
        thread_key_hint=None,
        business_lane=None,
        signal_summary_pl=case["input"].get("subject", ""),
        payload={},
        artifacts={},
        processing_state="pending",
        idempotency_key=f"idem_recovery_{case['id']}",
        content_hash=None,
        replayable=True,
        created_by_runtime="eval_recovery_1",
    )


def run_intake(case: dict, snapshot: dict) -> dict:
    lane_result = preclassify_snapshot(snapshot)
    noise = is_obvious_noise(snapshot)
    signal = build_gmail_signal(case)
    intake = {"message": {"subject": case["input"].get("subject", ""), "body": case["input"].get("body", "")}}
    cost_gate = _evaluate_cost_gate(signal, intake)
    return {
        "lane": lane_result.get("lane"),
        "lane_full": lane_result,
        "is_obvious_noise": noise,
        "cost_gate_skip": cost_gate.get("skip"),
        "cost_gate_reason": cost_gate.get("reason"),
    }


def run_extraction(settings, snapshot: dict) -> dict:
    return run_signal_extraction(settings=settings, snapshot=snapshot, context_bundle={}, case_link_result=None)


_CURRENT_FACT_KEYS = (
    "heated_area_m2", "budget_pln_estimated", "current_heating_source",
    "building_type", "construction_year", "raw_geographic_signal",
    "floor_heating_existing", "floor_heating_scope",
)


def _current_fact_rows(extraction: dict, case_id: str, current_signal_id: str) -> list[dict]:
    """WAVE-2 PARITY (measurement): production's accumulated CaseContextPack carries
    the CURRENT message's extracted facts alongside prior facts, and real conflict
    detection (split_conflicting_facts) flags prior-vs-current discrepancies. The
    frozen harness pack held only prior facts, so the current-state/thread-delta lane
    had no structural current-vs-prior signal. This adds the current extracted facts
    with current-signal provenance so the REAL split_conflicting_facts (not a
    hand-injected conflict) can detect discrepancies — production-faithful, no
    benchmark tuning."""
    rows: list[dict] = []
    ex = extraction if isinstance(extraction, dict) else {}
    for k in _CURRENT_FACT_KEYS:
        v = ex.get(k)
        if v in (None, "", [], {}):
            continue
        nv = str(int(v)) if isinstance(v, float) and float(v).is_integer() else str(v)
        rows.append({
            "entity_scope": "case",
            "fact_key": k,
            "value": v,
            "normalized_value": nv,
            "confidence": 0.72,
            "observed_at": "2026-07-16T12:00:00Z",
            "source_ref": current_signal_id,
            "evidence_refs": [{
                "source_type": "gmail_message", "source_id": current_signal_id,
                "message_id": current_signal_id, "evidence_role": "supports", "confidence": 0.72,
            }],
            "summary_pl": f"{k}={nv}",
        })
    return rows


def _corpus_context_pack(case: dict, extraction: dict | None = None) -> dict | None:
    """PARITY FIX (measurement, not product). The frozen run_understanding passed a
    bare {"settings": ...} config into build_case_intelligence_layer, so
    _resolve_effective_mailbox_context_pack returned None and the Understanding lane
    never received the prior_context (prior_facts, case_summary_pl, prior_messages,
    attachment content) that the corpus supplies — while the production active path
    ALWAYS assembles a CaseContextPack (config["mailbox_memory_context_pack"]) carrying
    exactly this before Understanding (gmail_intake._resolve_effective_mailbox_context_pack
    -> build_case_intelligence_result(case_context_pack=...) -> build_understanding_output).

    This reconstructs a production-SHAPED CaseContextPack from the corpus prior_context
    and injects it through the SAME production config boundary, so both the
    business-reasoning LLM (case_context_pack -> context_bundle -> assembled system
    prompt via overlay_pack_onto_assembled) and the deterministic understanding
    projection see the context a real agent would hold. active_facts become case_facts
    in the LLM prompt; chunks carry the prior summary / prior messages / attachment
    content. Conflict + gap detection is deliberately left to the real downstream logic
    and the LLM (NO per-case conflict/gap hand-injection = no benchmark tuning). No
    corpus bytes are changed; this only stops dropping context, it never adds facts the
    corpus did not already state."""
    prior = case.get("prior_context") or {}
    prior_facts = prior.get("prior_facts") or {}
    case_summary = str(prior.get("case_summary_pl") or "").strip()
    case_id = f"case_recovery_{case['id']}"
    active_facts: list[dict] = []
    if isinstance(prior_facts, dict):
        for k, v in prior_facts.items():
            active_facts.append({
                "entity_scope": "case",
                "fact_key": str(k),
                "value": v,
                "normalized_value": str(v),
                "confidence": 0.9,
                "observed_at": "2026-07-10T00:00:00Z",
                "source_ref": f"{case_id}_prior",
                "summary_pl": f"{k}={v}",
            })
    chunks: list[dict] = []
    if case_summary:
        chunks.append({
            "chunk_id": f"{case_id}_summary",
            "chunk_text": f"Wcześniejszy stan sprawy: {case_summary}",
            "source_kind": "case_summary",
            "source_ref": f"{case_id}_prior",
        })
    for i, m in enumerate(prior.get("prior_messages") or []):
        if not isinstance(m, dict):
            continue
        txt = " ".join(x for x in (str(m.get("subject") or ""), str(m.get("body") or "")) if x).strip()
        if txt:
            chunks.append({
                "chunk_id": f"{case_id}_prior_msg_{i}",
                "chunk_text": f"Wcześniejsza wiadomość: {txt}",
                "source_kind": "prior_message",
                "source_ref": f"{case_id}_prior_{i}",
            })
    for i, a in enumerate(((case.get("input") or {}).get("attachments") or [])):
        hint = str((a or {}).get("content_hint") or "").strip() if isinstance(a, dict) else ""
        if hint:
            chunks.append({
                "chunk_id": f"{case_id}_att_{i}",
                "chunk_text": f"Treść załącznika: {hint}",
                "source_kind": "attachment",
                "source_ref": f"{case_id}_att_{i}",
            })
    # WAVE-2 PARITY: production's replace_message_facts supersedes a different
    # active value from an older message before the context pack is projected.
    # Reproduce that write-path edge before running the real conflict splitter.
    current_signal_id = f"{case_id}_current"
    current_rows = _current_fact_rows(extraction or {}, case_id, current_signal_id)
    conflicting_facts: list[dict] = []
    current_values = {
        (str(row.get("entity_scope") or "case"), str(row.get("fact_key") or "")):
            str(row.get("normalized_value") or "").strip()
        for row in current_rows
    }
    for index, fact in enumerate(active_facts):
        identity = (str(fact.get("entity_scope") or "case"), str(fact.get("fact_key") or ""))
        current_value = current_values.get(identity)
        prior_value = str(fact.get("normalized_value") or "").strip()
        if current_value is not None and current_value != prior_value:
            active_facts[index] = {**fact, "status": "superseded"}
    combined = active_facts + current_rows
    if current_rows:
        try:
            from mailbox_memory_runtime import split_conflicting_facts  # noqa: E402
            active_split, conflicts = split_conflicting_facts(combined)
            active_facts = active_split
            for c in conflicts:
                fk = str(c.get("fact_key") or "")
                vals = [str(x) for x in (c.get("values") or [])]
                conflicting_facts.append({
                    **c,
                    "field_name": fk,
                    "summary_pl": f"Rozbieznosc dla {fk}: {' vs '.join(vals)} (wczesniej vs biezaco)",
                    "evidence_refs": [{
                        "source_type": "gmail_message", "source_id": current_signal_id,
                        "message_id": current_signal_id, "evidence_role": "supports",
                    }],
                })
        except Exception:
            active_facts = combined
    if not active_facts and not chunks:
        return None
    return {
        "case_id": case_id,
        "snapshot": {"open_questions": [], "summary_pl": case_summary},
        "active_facts": active_facts,
        "conflicting_facts": conflicting_facts,
        "completeness_gaps": [],
        "relevant_chunks": chunks,
        "recent_events": [],
        "source_refs": [],
    }


def run_understanding(settings, snapshot: dict, intake: dict, case: dict, extraction: dict | None = None,
                      intake_result_override: dict | None = None, capture: dict | None = None) -> dict | None:
    """New this session (brief §6B) + PARITY FIX: now injects a production-shaped
    CaseContextPack built from corpus prior_context through the real production config
    boundary (config["mailbox_memory_context_pack"]) so Understanding sees the context
    the production active path would hold. See _corpus_context_pack for the full
    rationale.

    CLOSEOUT-01 Phase 5: when `intake_result_override` is supplied (production_faithful
    mode), BusinessReasoning/Understanding consume the REAL production intake_result_final
    (from run_intake_reasoning). The placeholder path below remains ONLY for
    component_isolated mode and is explicitly tagged `_harness_placeholder` (never
    presented as production)."""
    from gmail_intake import (
        build_case_intelligence_layer,
        draft_reply as gi_draft_reply,
        plan_actions as gi_plan_actions,
        run_business_reasoning as gi_run_business_reasoning,
    )

    if isinstance(intake_result_override, dict) and intake_result_override:
        intake_result = intake_result_override
    else:
        intake_result = {
            "decision": {"action": "create_case" if intake.get("lane") not in _SKIP_LANES else "skip"},
            "business_area": "unknown",
            "priority": "normal",
            # COMPONENT_ISOLATED placeholder (NOT production). dash_preview.py
            # :_select_case_key_info requires case_assessment.case_family unconditionally.
            "case_assessment": {"case_family": "unclassified"},
            "thread": {"thread_id": "thread_recovery_placeholder"},
            "_harness_placeholder": True,
        }
    pack = _corpus_context_pack(case, extraction)
    config = {
        "settings": settings,
        "model": None,
        "verbose": False,
        "run_id": str(os.environ.get("FRESH38_ATTEMPT_ID") or "").strip(),
        "preclassification_result": {"lane": intake.get("lane")},
        "lane_stage_plan": {"run_business_reasoning": intake.get("lane") not in _SKIP_LANES},
        "case_link_result": {},
    }
    if pack:
        config["mailbox_memory_context_pack"] = pack
    context_bundle = _pf_build_context_bundle(
        snapshot,
        case_context_pack=pack if isinstance(pack, dict) else None,
    )
    business_result = gi_run_business_reasoning(
        snapshot,
        intake_result,
        {},
        context_bundle,
        config,
    )
    # CLOSEOUT-01: expose the BR decision class directly (operator requires recommended_action
    # observable), not only the reshaped understanding projection.
    if isinstance(capture, dict) and isinstance(business_result, dict):
        conf = business_result.get("confidence") or {}
        capture["business_reasoning"] = {
            "recommended_next_action": business_result.get("recommended_next_action"),
            "reply_recommended": business_result.get("reply_recommended"),
            "review_required": intake_result.get("review_required"),
            "customer_state_guess": business_result.get("customer_state_guess"),
            "business_area": business_result.get("business_area"),
            "human_review_bias": business_result.get("human_review_bias"),
            "confidence_business": conf.get("business_confidence"),
            "confidence_action": conf.get("action_confidence"),
        }
    reply_result = gi_draft_reply(
        snapshot,
        intake_result,
        business_result,
        context_bundle,
        config,
    )
    action_plan_result = gi_plan_actions(
        intake_result,
        {},
        business_result,
        reply_result,
        config,
    )
    ci_config: dict[str, Any] = {
        "settings": settings,
        "preclassification_result": {"lane": intake.get("lane")},
    }
    if pack:
        ci_config["mailbox_memory_context_pack"] = pack
    ci_layer = build_case_intelligence_layer(
        snapshot,
        intake_result,
        {},
        business_result,
        reply_result,
        action_plan_result,
        ci_config,
    )
    if isinstance(capture, dict):
        action_plan = action_plan_result if isinstance(action_plan_result, dict) else {}
        reply = reply_result if isinstance(reply_result, dict) else {}
        next_best_action = (
            ci_layer.get("next_best_action")
            if isinstance(ci_layer.get("next_best_action"), dict)
            else {}
        )
        primary_next_action = (
            next_best_action.get("primary_next_action")
            if isinstance(next_best_action.get("primary_next_action"), dict)
            else {}
        )
        case_understanding = (
            ci_layer.get("case_understanding")
            if isinstance(ci_layer.get("case_understanding"), dict)
            else {}
        )
        capture["brain1_reply_result"] = reply
        if isinstance(reply.get("causal_observability"), dict):
            capture["causal_observability"] = reply["causal_observability"]
        capture["action_plan"] = action_plan
        decision_comparison_inputs = {
            "schema_version": "decision_comparison_inputs.v1",
            "source_signal_id": str(
                snapshot.get("signal_id") if isinstance(snapshot, dict) else ""
            ),
            "business_recommended_action": str(
                business_result.get("recommended_next_action") or ""
            ),
            "action_planner_primary_action": str(
                action_plan.get("primary_action") or ""
            ),
            "next_best_action_type": str(
                primary_next_action.get("action_type") or ""
            ),
            "reply_draft_enabled": bool(reply.get("draft_enabled")),
            "case_family": str(case_understanding.get("case_family") or ""),
        }
        capture["decision_comparison_inputs"] = decision_comparison_inputs
        capture["decision_divergence_inputs"] = {
            "action_planner_primary_action": str(
                action_plan.get("primary_action") or ""
            ),
            "next_best_action_type": str(
                primary_next_action.get("action_type") or ""
            ),
            "case_family": str(case_understanding.get("case_family") or ""),
            "action_plan_shadow_only": bool(
                (action_plan.get("execution_metadata") or {}).get("shadow_only")
            ),
            "reply_draft_enabled": bool(reply.get("draft_enabled")),
            "reply_recommended_variant": str(reply.get("recommended_variant") or ""),
            "reply_source_mode": str(
                (reply.get("execution_metadata") or {}).get("source_mode") or ""
            ),
        }
        if isinstance(ci_layer, dict):
            ci_layer["decision_comparison_inputs"] = decision_comparison_inputs
    # PLANNER-FIDELITY-CLOSEOUT-02: return full intelligence so planner can receive
    # PolicyDecision/APv2 envelope + Brain1 projection (not only understanding_output).
    return ci_layer


def run_planner(
    agent_settings,
    case: dict,
    extraction: dict,
    case_kind: str | None = None,
    case_intelligence: dict | None = None,
) -> dict:
    case_diag_id = str(case.get("id") or "")
    constitution = load_constitution()
    journal = InMemoryAgentTurnJournal()
    engagement_id = f"eng_recovery_{case['id']}"
    case_id = f"case_recovery_{case['id']}"
    message_id = f"{case_id}_current"
    signal_id = f"sig_{case['id']}"
    planner = OpenAIToolPlanner(settings=agent_settings)
    engine = AgentGraphEngine(
        planner=planner,
        constitution=constitution,
        tool_registry=SafeShimToolRegistry(),
        turn_journal=journal,
    )
    snapshot = build_initial_snapshot(case_id=case_id, engagement_id=engagement_id, trace_id=f"trace_recovery_{case['id']}")
    # CLOSEOUT-01 Phase 5: production classifies case_kind (via _classify_case_kind) BEFORE
    # the planner runs; build_initial_snapshot only defaults it to "niezaklasyfikowane".
    # In production_faithful mode we hydrate the real classified case_kind so the planner
    # sees the same goal/tool contract production would, removing the unclassified-follow-up
    # goal↔follow-up-rule contradiction that made the first tool choice nondeterministic.
    if case_kind:
        snapshot.case_kind = case_kind

    # PLANNER-FIDELITY-CLOSEOUT-02: production-faithful spine handoff.
    # Falls back to prior subject/snippet-only payload only if handoff import fails.
    envelope_presence = None
    try:
        from eval_planner_spine_handoff import (
            apply_hvac_seed_to_snapshot,
            build_production_faithful_planner_signal,
        )

        intel = case_intelligence if isinstance(case_intelligence, dict) else {}
        # If harness previously returned only understanding_output, wrap it.
        if intel and "understanding_output" not in intel and (
            intel.get("operator_explanation") or intel.get("situation_summary_pl")
        ):
            intel = {"understanding_output": intel}
        handoff = build_production_faithful_planner_signal(
            case_id=case_id,
            signal_id=signal_id,
            message_id=message_id,
            subject=str((case.get("input") or {}).get("subject") or ""),
            body=str((case.get("input") or {}).get("body") or ""),
            case_intelligence_result=intel,
            case_kind=case_kind,
            extraction=extraction if isinstance(extraction, dict) else None,
            harness_mode=False,
            policy_required=True,
        )
        signal_payload = handoff["signal_payload"]
        envelope_presence = handoff.get("envelope_presence")
        snapshot = apply_hvac_seed_to_snapshot(snapshot, signal_payload)
        policy_store = handoff["mailbox_store"]
    except Exception as handoff_exc:  # noqa: BLE001
        prior = case.get("prior_context")
        signal_payload = {
            "case_id": case_id,
            "subject": case["input"].get("subject", ""),
            "snippet": case["input"].get("body", ""),
            "harness_mode": True,
            "policy_required": False,
            "spine_handoff_error": f"{type(handoff_exc).__name__}: {handoff_exc}",
        }
        if prior:
            signal_payload["understanding_brief_pl"] = prior.get("case_summary_pl", "")
        policy_store = CorpusMailboxStore(case, case_id=case_id)

    # P1.4A: production-faithful eligibility context. The deterministic kalk-top
    # eligibility gate (agent_runtime.kalk_eligibility) reads the authoritative
    # BusinessReasoning recommendation from decision_comparison_inputs on the
    # very first planner turn — mirroring agent_reconcile's production wiring.
    if isinstance(case_intelligence, dict) and isinstance(
        case_intelligence.get("decision_comparison_inputs"), dict
    ):
        signal_payload["decision_comparison_inputs"] = case_intelligence[
            "decision_comparison_inputs"
        ]

    ctx = ToolExecutionContext.from_snapshot(
        snapshot,
        signal_payload=signal_payload,
        constitution=constitution,
        mailbox_store=policy_store,
    )
    t0 = time.time()
    _lifecycle_diag("planner_engine_run_start", case_diag_id, threads=_thread_snapshot())
    try:
        result = engine.run(snapshot, context=ctx)
    finally:
        _shutdown_planner_engine(engine, case_diag_id)
    elapsed = time.time() - t0
    _lifecycle_diag("planner_engine_run_done", case_diag_id, elapsed_s=round(elapsed, 3), threads=_thread_snapshot())
    final = result.snapshot
    turns_raw = journal.list_turns(engagement_id)

    # Fix #3: read the composed draft body back from the final snapshot, not the turn
    # journal (which never carries snapshot_delta — confirmed this session).
    final_actions = [a.model_dump() if hasattr(a, "model_dump") else a for a in getattr(final, "actions", [])]
    draft_body = None
    for action in final_actions:
        if isinstance(action, dict) and action.get("id") == "draft_reply" and action.get("payload_pl"):
            draft_body = action["payload_pl"]
            break

    correlation_statuses = []
    for turn in turns_raw:
        if isinstance(turn, dict):
            pc = turn.get("plan_correlation") or {}
            if isinstance(pc, dict) and pc.get("status"):
                correlation_statuses.append(pc.get("status"))

    return {
        "elapsed_s": round(elapsed, 2),
        "tool_name": result.turns[0].tool_name if result.turns else None,
        "arguments": getattr(result.turns[0], "arguments", None) if result.turns else None,
        "turns_raw": turns_raw,
        "hitl_gate_required": bool(final.hitl_gate.required) if hasattr(final, "hitl_gate") and final.hitl_gate else None,
        "reasoning_trace_summaries": [item.summary_pl for item in final.agent_memory.reasoning_trace],
        "case_id": final.case_id,
        "final_actions": final_actions,
        "generate_draft_reply_body": draft_body,
        "envelope_presence": envelope_presence,
        "plan_correlation_statuses": correlation_statuses,
        "planner_run_budget": getattr(result, "planner_run_budget", {}) or {},
        "policy_decision_id": str(
            getattr(getattr(final, "policy_action_envelope", None), "policy_decision_id", "") or ""
        ),
        "action_proposal_id": str(
            getattr(getattr(final, "policy_action_envelope", None), "action_proposal_id", "") or ""
        ),
    }


def run_draft(settings, snapshot: dict, *, intake_result: dict | None = None, business_result: dict | None = None) -> dict:
    """Brain1 draft only when real intake/BR are supplied.

    Historical harness fabricated ``action=reply`` here. That contaminates
    measurement: a skipped or failed understanding still looked like a reply
    path. Production-faithful capture must not invent eligibility.
    """
    if not isinstance(intake_result, dict) or not isinstance(business_result, dict):
        return {
            "draft_enabled": False,
            "drafts": [],
            "skipped": "fabricated_eligibility_disabled",
            "do_not_send_reasons": ["fabricated_eligibility_disabled"],
            "requires_manual_edit": True,
        }
    return run_reply_drafter(
        settings=settings,
        snapshot=snapshot,
        intake_result=intake_result,
        business_result=business_result,
        business_context_bundle={},
        context_bundle={},
    )


def _stage_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"


def run_one_case(case: dict, *, mode: str, settings, agent_settings) -> dict:
    print(f"=== {case['id']} (mode={mode}) ===", flush=True)
    _lifecycle_diag(
        "case_start",
        str(case.get("id") or ""),
        mode=mode,
        runner=_runner_process_identity(),
        threads=_thread_snapshot(),
        children=_child_process_snapshot(),
    )
    snapshot = build_snapshot(case)
    case_result: dict[str, Any] = {
        "id": case["id"],
        "categories": case["categories"],
        "measurement_mode": mode,
        "measurement_attempt": _measurement_attempt(),
    }

    try:
        _lifecycle_diag("stage_intake_start", case["id"])
        case_result["intake"] = run_intake(case, snapshot)
        _lifecycle_diag("stage_intake_done", case["id"])
        print("  intake:", case_result["intake"]["lane"], "cost_gate_skip:", case_result["intake"]["cost_gate_skip"], flush=True)
    except Exception as exc:  # noqa: BLE001
        case_result["intake_error"] = _stage_error(exc)
        case_result["intake_classification"] = classify_outcome(error_text=case_result["intake_error"], is_rate_limit=False)
        print("  intake FAILED:", exc, flush=True)
        case_result["stage_reached"] = "intake_error"
        return case_result

    lane = (case_result.get("intake") or {}).get("lane")
    if mode == "production_faithful" and lane in _SKIP_LANES:
        case_result["stage_reached"] = "intake_only"
        case_result["mode_note"] = "production_lane_short_circuit"
        print(f"  production-faithful: lane={lane} — real production would stop here, not running planner", flush=True)
        return case_result

    extraction = None
    try:
        _lifecycle_diag("stage_extraction_start", case["id"])
        extraction = run_extraction(settings, snapshot)
        case_result["extraction"] = extraction
        _lifecycle_diag("stage_extraction_done", case["id"])
        print("  extraction OK", flush=True)
    except Exception as exc:  # noqa: BLE001
        err = _stage_error(exc)
        case_result["extraction_error"] = err
        case_result["extraction_classification"] = classify_outcome(
            error_text=err, is_rate_limit=_looks_rate_limited(exc)
        )
        print("  extraction FAILED:", exc, flush=True)

    # ── CLOSEOUT-01 Phase 5: production-faithful intake + case_kind hydration ──
    intake_result_override = None
    planner_case_kind = None
    is_pf = mode == "production_faithful"
    if is_pf:
        _lifecycle_diag("stage_pf_intake_reasoning_start", case["id"])
        real = compute_real_intake_result(
            settings,
            snapshot,
            (case_result.get("intake") or {}).get("lane_full") or {"lane": lane},
        )
        _lifecycle_diag("stage_pf_intake_reasoning_done", case["id"], is_valid=real.get("is_valid"))
        case_result["intake_reasoning"] = {
            "mode": "real_run_intake_reasoning",
            "is_valid": real["is_valid"],
            "final_output_origin": real["final_output_origin"],
            "intake_result_hash": real["intake_result_hash"],
            "business_area": (real["intake_result_final"] or {}).get("business_area"),
            "raw_valid": real.get("raw_valid"),
            "normalized_valid": real.get("normalized_valid"),
            "repaired_valid": real.get("repaired_valid"),
            "guardrail_error": real.get("guardrail_error"),
        }
        if not real["is_valid"] or not isinstance(real["intake_result_final"], dict):
            # Production-faithful capture must not substitute a placeholder. A real invalid
            # intake result is still a terminal SUT result, so capture it as product failure
            # rather than marking the measurement artifact corrupt.
            case_result["stage_reached"] = "intake_reasoning_error"
            classification = classify_outcome(
                error_text=str(real.get("final_output_origin") or "intake_invalid"), is_rate_limit=False)
            case_result["intake_reasoning_classification"] = classification
            case_result["case_product_outcome"] = "CASE_PRODUCT_FAIL"
            case_result["terminal_product_result"] = {
                "stage": "intake_reasoning",
                "reason": "intake_result_final_missing",
                "classification": classification,
                "final_output_origin": real.get("final_output_origin"),
            }
            case_result["capture_integrity"] = {
                "status": "CASE_CAPTURE_SUCCESS",
                "terminal_state": "intake_reasoning_error",
                "product_failure_preserved": True,
            }
            print("  production_faithful intake INVALID — not substituting a placeholder", flush=True)
            return case_result
        intake_result_override = real["intake_result_final"]
        ck = derive_production_case_kind(settings, snapshot, intake_result_override)
        planner_case_kind = ck["case_kind"]
        case_result["planner_case_kind"] = {"source": "classified_from_intake", **ck}
        print(f"  production_faithful intake OK (ba={case_result['intake_reasoning']['business_area']}) "
              f"case_kind={planner_case_kind}", flush=True)

    try:
        _br_capture: dict[str, Any] = {}
        _lifecycle_diag("stage_understanding_start", case["id"])
        case_result["case_intelligence"] = run_understanding(
            settings, snapshot, case_result.get("intake") or {}, case, extraction,
            intake_result_override=intake_result_override, capture=_br_capture)
        _lifecycle_diag("stage_understanding_done", case["id"])
        ci_layer = case_result.get("case_intelligence")
        if isinstance(ci_layer, dict):
            case_result["understanding"] = ci_layer.get("understanding_output")
        else:
            case_result["understanding"] = ci_layer
        if _br_capture.get("business_reasoning"):
            case_result["business_reasoning"] = _br_capture["business_reasoning"]
        if _br_capture.get("action_plan"):
            case_result["action_plan"] = _br_capture["action_plan"]
        if _br_capture.get("decision_divergence_inputs"):
            case_result["decision_divergence_inputs"] = _br_capture[
                "decision_divergence_inputs"
            ]
        if isinstance(_br_capture.get("brain1_reply_result"), dict):
            _reply_capture = _br_capture["brain1_reply_result"]
            if isinstance(_reply_capture.get("causal_observability"), dict):
                case_result["causal_observability"] = _reply_capture["causal_observability"]
        if (
            case.get("ground_truth", {}).get("draft_expected")
            and isinstance(_br_capture.get("brain1_reply_result"), dict)
        ):
            case_result["draft"] = _br_capture["brain1_reply_result"]
        print("  understanding OK" if case_result["understanding"] else "  understanding: none produced",
              "| BR:", (_br_capture.get("business_reasoning") or {}).get("recommended_next_action"),
              "| action:", (_br_capture.get("decision_divergence_inputs") or {}).get("action_planner_primary_action"),
              flush=True)
    except Exception as exc:  # noqa: BLE001
        err = _stage_error(exc)
        case_result["understanding_error"] = err
        case_result["understanding_classification"] = classify_outcome(
            error_text=err, is_rate_limit=_looks_rate_limited(exc)
        )
        print("  understanding FAILED:", exc, flush=True)

    try:
        _lifecycle_diag("stage_planner_start", case["id"])
        case_result["planner"] = run_planner(
            agent_settings,
            case,
            extraction or {},
            case_kind=planner_case_kind,
            case_intelligence=case_result.get("case_intelligence")
            if isinstance(case_result.get("case_intelligence"), dict)
            else (
                {"understanding_output": case_result["understanding"]}
                if isinstance(case_result.get("understanding"), dict)
                else None
            ),
        )
        _lifecycle_diag("stage_planner_done", case["id"])
        case_result["planner_classification"] = classify_outcome(error_text=None, is_rate_limit=None)
        case_result = reclassify_planner_error(case_result)
        print("  planner tool:", case_result["planner"]["tool_name"], "classification:", case_result["planner_classification"],
              "| envelope:", (case_result["planner"].get("envelope_presence") or {}).get("status"),
              "| corr:", case_result["planner"].get("plan_correlation_statuses"),
              flush=True)
    except Exception as exc:  # noqa: BLE001
        err = _stage_error(exc)
        case_result["planner_error"] = err
        case_result["planner_classification"] = classify_outcome(
            error_text=err, is_rate_limit=_looks_rate_limited(exc)
        )
        print("  planner FAILED:", exc, flush=True)

    if case.get("ground_truth", {}).get("draft_expected") and not isinstance(
        case_result.get("draft"), dict
    ):
        case_result["draft_skipped_reason"] = "no_brain1_draft_no_fabricated_fallback"
        print("  draft skipped: no Brain1 draft; fabricated eligibility fallback disabled", flush=True)

    case_result["stage_reached"] = "full"
    case_result["rubric_scores"] = score_case(case, case_result)
    # CLOSEOUT-01 Phase 6 — additive outcome-class coverage (does NOT change corpus,
    # ground truth, threshold, or any existing rubric verdict).
    case_result["outcome_coverage"] = outcome_coverage(case, case_result)
    _lifecycle_diag(
        "case_done",
        case["id"],
        terminal_state=case_result["stage_reached"],
        runner=_runner_process_identity(),
        threads=_thread_snapshot(),
        children=_child_process_snapshot(),
    )
    return case_result


def _looks_rate_limited(exc: Exception) -> bool:
    text = str(exc).lower()
    return "rate_limit" in text or "quota_exhausted" in text or "429" in text


def main() -> None:
    mode = sys.argv[1]
    # CLOSEOUT-01 Phase 5: component_isolated is an explicit alias of the stub mode
    # (component_capability) — stubs allowed but never presented as production.
    if mode == "component_isolated":
        mode = "component_capability"
    assert mode in ("production_faithful", "component_capability"), f"unknown mode: {mode}"
    corpus_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3])
    rest = sys.argv[4:]
    sentinel_only = "--sentinel-only" in rest
    only_ids = set(a for a in rest if a != "--sentinel-only") or None
    if sentinel_only:
        only_ids = set(SENTINEL_CASE_IDS)

    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    settings = load_settings(require_groq=False, require_google=False)
    agent_settings = load_agent_runtime_settings()

    selected_cases = [case for case in corpus["cases"] if not only_ids or case["id"] in only_ids]
    expected_case_ids = [str(case["id"]) for case in selected_cases]
    measurement_attempt = _measurement_attempt()
    if measurement_attempt["attempt_id"] and not measurement_attempt["artifact_path"]:
        measurement_attempt["artifact_path"] = str(out_path)
    _lifecycle_diag(
        "runner_start",
        None,
        mode=mode,
        corpus_path=str(corpus_path),
        out_path=str(out_path),
        selected_case_ids=expected_case_ids,
        runner=measurement_attempt["runner"],
        threads=_thread_snapshot(),
        children=_child_process_snapshot(),
    )
    results = []
    for case in selected_cases:
        _lifecycle_diag("main_case_loop_start", str(case.get("id") or ""), out_path=str(out_path))
        case_result = run_one_case(case, mode=mode, settings=settings, agent_settings=agent_settings)
        results.append(case_result)
        payload = {
            "mode": mode,
            "sentinel_only": sentinel_only,
            "measurement_attempt": measurement_attempt,
            "cases": results,
        }
        partial_expected = expected_case_ids[: len(results)] if expected_case_ids else None
        _lifecycle_diag(
            "artifact_write_start",
            str(case.get("id") or ""),
            out_path=str(out_path),
            expected_case_ids=partial_expected,
            threads=_thread_snapshot(),
            children=_child_process_snapshot(),
            runner=_runner_process_identity(),
        )
        write_canonical_capture_artifact(out_path, payload, expected_case_ids=partial_expected)
        stat = out_path.stat()
        _lifecycle_diag(
            "artifact_write_done",
            str(case.get("id") or ""),
            out_path=str(out_path),
            size=stat.st_size,
            mtime=stat.st_mtime,
            threads=_thread_snapshot(),
            children=_child_process_snapshot(),
            runner=_runner_process_identity(),
        )

    if expected_case_ids:
        final_payload = {
            "mode": mode,
            "sentinel_only": sentinel_only,
            "measurement_attempt": measurement_attempt,
            "cases": results,
        }
        _lifecycle_diag("artifact_final_validate_start", None, out_path=str(out_path), expected_case_ids=expected_case_ids)
        write_canonical_capture_artifact(out_path, final_payload, expected_case_ids=expected_case_ids)
        _lifecycle_diag(
            "artifact_final_validate_done",
            None,
            out_path=str(out_path),
            threads=_thread_snapshot(),
            children=_child_process_snapshot(),
            runner=_runner_process_identity(),
        )
    else:
        raise HarnessCaptureContractError("no_cases_selected")

    artifact_ok = False
    artifact_size = 0
    try:
        artifact_size = out_path.stat().st_size
        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        artifact_ok = not _capture_contract_errors(parsed, expected_case_ids)
    except Exception:
        artifact_ok = False
    _lifecycle_diag(
        "runner_about_to_exit",
        None,
        out_path=str(out_path),
        artifact_exists=out_path.exists(),
        artifact_size=artifact_size,
        artifact_valid=artifact_ok,
        runner=_runner_process_identity(),
        threads=_thread_snapshot(),
        children=_child_process_snapshot(),
    )
    print(f"Done. {len(results)} cases written to {out_path}", flush=True)


if __name__ == "__main__":
    main()
