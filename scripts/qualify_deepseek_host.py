#!/usr/bin/env python3
"""Cost-bounded qualification of a DeepSeek host (DEEPSEEK-TEMP-BRIDGE-01).

Answers one narrow question: *is this host a technically compatible place to run the DeepSeek
tier?* It is not a capability benchmark, not a statistical comparison against DeepSeek Direct,
and not a Fresh38 substitute.

COST GUARD is the reason this file exists rather than an ad-hoc probe. A previous diagnostic
consumed 38,699 completion tokens and zeroed a provider account. This run therefore:

  * makes exactly one tiny connectivity smoke call first, and stops if it fails;
  * caps the qualification at 6 calls;
  * caps cumulative completion and reasoning tokens, and aborts mid-run when either is passed;
  * aborts immediately on any quota/billing/auth error;
  * aborts if a single response's reasoning explodes past a per-call ceiling;
  * never raises max_tokens to make a test pass.

It never writes a secret, a prompt, or reasoning/chain-of-thought text. Only response shape.

    python scripts/qualify_deepseek_host.py --host deepseek_nvidia --out <file.json>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

def _audit_dir() -> Path:
    """Resolve the gmail_audit package whether run from the repo or inside the runtime container."""
    candidates = [
        Path(__file__).resolve().parents[1] / "gmail-agent" / "tools" / "gmail_audit",  # repo checkout
        Path("/app/tools/gmail_audit"),                                                  # container
    ]
    for candidate in candidates:
        if (candidate / "config.py").is_file():
            return candidate
    raise SystemExit(f"cannot locate gmail_audit package; looked in: {[str(c) for c in candidates]}")


AUDIT_DIR = _audit_dir()
if str(AUDIT_DIR) not in sys.path:
    sys.path.insert(0, str(AUDIT_DIR))

# ── cost guard limits (deliberately small; diagnostic, not a benchmark) ──────────────
MAX_CALLS = 6
MAX_TOTAL_COMPLETION_TOKENS = 20_000
MAX_TOTAL_REASONING_TOKENS = 15_000
MAX_SINGLE_CALL_REASONING_TOKENS = 6_000
SMOKE_MAX_TOKENS = 8
ABORT_ERROR_CLASSES = {"quota_exhausted", "auth", "rate_limit", "model_unavailable"}


class CostGuard:
    """Stops the run the moment it stops being cheap."""

    def __init__(self) -> None:
        self.calls = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.triggered: str | None = None

    def may_call(self) -> bool:
        if self.triggered:
            return False
        if self.calls >= MAX_CALLS:
            self.triggered = f"max_calls reached ({MAX_CALLS})"
            return False
        if self.completion_tokens >= MAX_TOTAL_COMPLETION_TOKENS:
            self.triggered = f"max_total_completion_tokens reached ({MAX_TOTAL_COMPLETION_TOKENS})"
            return False
        if self.reasoning_tokens >= MAX_TOTAL_REASONING_TOKENS:
            self.triggered = f"max_total_reasoning_tokens reached ({MAX_TOTAL_REASONING_TOKENS})"
            return False
        return True

    def record(self, *, completion: int, reasoning: int, error_class: str | None) -> None:
        self.calls += 1
        self.completion_tokens += int(completion or 0)
        self.reasoning_tokens += int(reasoning or 0)
        if error_class in ABORT_ERROR_CLASSES:
            self.triggered = f"provider error_class={error_class} (billing/quota/auth) — aborting"
        elif (reasoning or 0) > MAX_SINGLE_CALL_REASONING_TOKENS:
            self.triggered = (
                f"single-call reasoning_tokens={reasoning} exceeded "
                f"{MAX_SINGLE_CALL_REASONING_TOKENS} — possible token explosion"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls_made": self.calls,
            "max_calls": MAX_CALLS,
            "completion_tokens": self.completion_tokens,
            "max_total_completion_tokens": MAX_TOTAL_COMPLETION_TOKENS,
            "reasoning_tokens": self.reasoning_tokens,
            "max_total_reasoning_tokens": MAX_TOTAL_REASONING_TOKENS,
            "guard_triggered": bool(self.triggered),
            "guard_reason": self.triggered,
        }


def error_detail(body: dict[str, Any]) -> str:
    """Extract the human-readable reason from either error envelope a host may use.

    OpenAI-compatible hosts return `{"error": {"message": ...}}`. NVIDIA NIM returns RFC 7807
    `application/problem+json`: `{"title": ..., "detail": ...}`. Reading only the first shape
    turned a 410 that stated its own cause verbatim ("has reached its end of life on
    2026-08-07") into an empty string, which is the worst possible diagnostic: a failure that
    looks unexplained when the host in fact explained it.
    """
    body = body or {}
    for candidate in (
        ((body.get("error") or {}) if isinstance(body.get("error"), dict) else {}).get("message"),
        body.get("detail"),
        body.get("title"),
        body.get("message"),
        body.get("error") if isinstance(body.get("error"), str) else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def classify_http(status: int, body: dict[str, Any]) -> str | None:
    if status < 400:
        return None
    message = error_detail(body).lower()
    if status == 402 or "insufficient" in message or "credit" in message or "balance" in message:
        return "quota_exhausted"
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    # 410 Gone is how NIM reports a retired model id. That is a configuration fact about the
    # requested model, not a transport fault, and repeating it 6 times buys nothing.
    if status == 410 or "end of life" in message or "no longer available" in message:
        return "model_unavailable"
    if status == 404:
        return "model_unavailable" if "model" in message else "not_found"
    if status >= 500:
        return "server_error"
    return "http_error"


def build_cases() -> list[tuple[str, Any, str]]:
    """Representative stages using the real, existing contracts."""
    from llm_contracts.business_reasoning import BusinessReasoningResult
    from llm_contracts.intake_reasoning import IntakeReasoningResult
    from llm_contracts.reply_draft import ReplyDraftResult
    from llm_contracts.signal_extraction import SignalExtractionResult

    return [
        ("signal_extraction", SignalExtractionResult, "signal_extraction_v1"),
        ("intake_reasoning", IntakeReasoningResult, "intake_output_v1"),
        ("business_reasoning", BusinessReasoningResult, "business_reasoning_v1"),
        ("business_reasoning_large_context", BusinessReasoningResult, "business_reasoning_v1"),
        ("reply_drafter", ReplyDraftResult, "reply_draft_v1"),
        ("schema_stress", IntakeReasoningResult, "intake_output_v1"),
    ]


# Synthetic fixture — no real customer data.
FIXTURE_SHORT = (
    "Dzien dobry, prosze o wycene pompy ciepla dla domu 150 m2 w okolicach Krakowa. "
    "Obecnie ogrzewam gazem. Prosze o kontakt."
)
FIXTURE_LARGE = FIXTURE_SHORT + " " + (
    "Dodatkowo rozwazam fotowoltaike i termomodernizacje poddasza. "
    "Budynek z 2005 roku, sciany dwuwarstwowe, okna wymienione w 2018. "
) * 14


def run(host: str, out_path: Path) -> int:
    import requests
    from config import load_settings
    from groq_client import resolve_deepseek_host

    settings = load_settings(require_groq=False, require_google=False)
    # Force the host under test without mutating deployment configuration.
    object.__setattr__(settings, "deepseek_host", host) if hasattr(settings, "__slots__") else setattr(settings, "deepseek_host", host)
    resolved = resolve_deepseek_host(settings)

    report: dict[str, Any] = {
        "investigation": "DEEPSEEK-TEMP-BRIDGE-01",
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "Response shape only. No secret, prompt or reasoning text is recorded.",
        "host_under_test": resolved.host,
        "telemetry_provider_label": resolved.provider,
        "provider_role": resolved.role,
        "canonical_target": "deepseek_direct",
        "logical_model_intent": "deepseek",
        "model": resolved.model,
        "base_url": resolved.base_url,
        "credential_configured": bool(resolved.api_keys),
        "smoke": None,
        "calls": [],
        "verdict": None,
    }

    if not resolved.configured:
        missing_model = not resolved.model
        report["verdict"] = "BLOCKED_OPERATOR_ACTION"
        report["blocker"] = {
            "reason": "model_not_configured" if missing_model else "credential_not_configured",
            "env_var": resolved.missing_config,
            "detail": (
                f"{resolved.host} is not fully configured ({resolved.missing_config}); "
                "no call was attempted."
            ),
            "model_policy": (
                "DEEPSEEK_NVIDIA_MODEL is explicit-only: no default and no NVIDIA_MODEL fallback. "
                "The bridge must preserve the logical model identity while changing only the host."
            ) if resolved.host == "deepseek_nvidia" else None,
        }
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"BLOCKED_OPERATOR_ACTION: {resolved.missing_config} is not configured for {resolved.host}")
        print("No provider call was made; nothing was spent.")
        return 3

    guard = CostGuard()
    key = resolved.api_keys[0]
    url = resolved.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}

    def post(body: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
        started = time.monotonic()
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            return {"transport_error": type(exc).__name__, "latency_ms": int((time.monotonic() - started) * 1000)}
        latency = int((time.monotonic() - started) * 1000)
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return {"status": response.status_code, "json": payload, "latency_ms": latency}

    # ── 0. catalog preflight: free, no inference, no tokens ─────────────────────────
    #
    # `GET /models` is a listing, not a completion: it costs nothing. Checking it before the
    # smoke means a retired or mistyped model id is named precisely instead of surfacing as an
    # opaque HTTP error that has already consumed a call. Advisory by design — a host that does
    # not expose a catalog simply falls through to the smoke, exactly as before.
    catalog: list[str] = []
    try:
        listing = requests.get(url.rsplit("/chat/completions", 1)[0] + "/models", headers=headers, timeout=30)
        if listing.status_code == 200:
            catalog = sorted(
                str(entry.get("id") or "")
                for entry in (listing.json().get("data") or [])
                if entry.get("id")
            )
    except Exception:  # noqa: BLE001 - preflight must never be the reason a run fails
        catalog = []

    if catalog and resolved.model not in catalog:
        stem = resolved.model.rsplit("/", 1)[-1].split("-0")[0].lower()
        related = [entry for entry in catalog if stem and stem in entry.lower()]
        report["catalog_preflight"] = {
            "checked": True,
            "catalog_size": len(catalog),
            "configured_model_present": False,
            "related_ids_offered_by_host": related,
        }
        report["verdict"] = "BLOCKED_OPERATOR_ACTION"
        report["blocker"] = {
            "reason": "model_not_offered_by_host",
            "detail": (
                f"{resolved.host} does not list {resolved.model!r} in its catalog "
                f"({len(catalog)} models). No inference call was attempted."
            ),
            "operator_decision_required": (
                "Selecting a different model id changes provider AND model at once, which is the "
                "one thing this bridge exists to avoid. Any substitution is an operator decision, "
                "not an automatic fallback."
            ),
            "related_ids_offered_by_host": related,
        }
        report["cost_guard"] = guard.as_dict()
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"BLOCKED_OPERATOR_ACTION: host does not offer {resolved.model!r}.")
        print(f"  related ids it does offer: {related or '(none)'}")
        print("No inference call was made; nothing was spent.")
        return 3

    report["catalog_preflight"] = {
        "checked": bool(catalog),
        "catalog_size": len(catalog),
        "configured_model_present": bool(catalog) or None,
    }

    # ── 1. connectivity smoke: exactly one tiny call ────────────────────────────────
    smoke = post({
        "model": resolved.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": SMOKE_MAX_TOKENS,
    }, timeout=60)
    smoke_body = smoke.get("json") or {}
    smoke_choice = (smoke_body.get("choices") or [{}])[0]
    smoke_msg = smoke_choice.get("message") or {}
    smoke_usage = smoke_body.get("usage") or {}
    error_class = None if "transport_error" in smoke else classify_http(smoke.get("status", 0), smoke_body)
    report["smoke"] = {
        "http": smoke.get("status"),
        "transport_error": smoke.get("transport_error"),
        "latency_ms": smoke.get("latency_ms"),
        "model_echoed": smoke_body.get("model"),
        "content_len": len(smoke_msg.get("content") or ""),
        "finish_reason": smoke_choice.get("finish_reason"),
        "error_class": error_class,
        "error_message": error_detail(smoke_body)[:300],
    }
    guard.record(
        completion=smoke_usage.get("completion_tokens") or 0,
        reasoning=(smoke_usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
        error_class=error_class,
    )
    smoke_ok = smoke.get("status") == 200 and not smoke.get("transport_error")
    if not smoke_ok:
        report["verdict"] = "FAIL"
        report["cost_guard"] = guard.as_dict()
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"SMOKE FAILED: http={smoke.get('status')} error_class={error_class} - stopping before qualification.")
        if report["smoke"]["error_message"]:
            print(f"  host said: {report['smoke']['error_message']}")
        return 2
    print(f"smoke OK  http=200 model={smoke_body.get('model')} latency={smoke.get('latency_ms')}ms")

    # ── 2. bounded qualification ────────────────────────────────────────────────────
    for stage, model_cls, schema_name in build_cases():
        if not guard.may_call():
            report["calls"].append({"stage": stage, "skipped": True, "reason": guard.triggered})
            continue
        schema = model_cls.model_json_schema()
        user = FIXTURE_LARGE if "large" in stage else FIXTURE_SHORT
        system = (
            "Jestes asystentem TOP-INSTAL.\n\n"
            f"JSON Schema contract for {schema_name}:\n{json.dumps(schema, ensure_ascii=False, sort_keys=True)}\n"
            "Return exactly one JSON value that validates against this schema. "
            f"Schema name: {schema_name}. Reply with a single JSON value (object or array only). "
            "No markdown fences, no text outside JSON."
        )
        body = {
            "model": resolved.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "stream": False,
        }
        result = post(body)
        payload = result.get("json") or {}
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = payload.get("usage") or {}
        content = message.get("content")
        reasoning = message.get("reasoning_content")
        err = None if "transport_error" in result else classify_http(result.get("status", 0), payload)

        schema_valid = None
        structured_valid = None
        if isinstance(content, str) and content.strip():
            try:
                parsed = json.loads(content)
                structured_valid = isinstance(parsed, (dict, list))
                try:
                    model_cls.model_validate(parsed)
                    schema_valid = True
                except Exception:  # noqa: BLE001
                    schema_valid = False
            except ValueError:
                structured_valid = False
                schema_valid = False

        row = {
            "stage": stage,
            "provider": resolved.provider,
            "model": resolved.model,
            "http": result.get("status"),
            "transport_error": result.get("transport_error"),
            "latency_ms": result.get("latency_ms"),
            "finish_reason": choice.get("finish_reason"),
            "content_len": len(content) if isinstance(content, str) else 0,
            "content_type": type(content).__name__,
            "structured_output_valid": structured_valid,
            "schema_valid": schema_valid,
            "reasoning_present": bool(isinstance(reasoning, str) and reasoning.strip()),
            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "has_tool_calls": bool(message.get("tool_calls")),
            "schema_chars": len(json.dumps(schema)),
            "fallback_triggered": False,  # direct-to-host probe; the router is not involved here
            "failure_class": err or (None if (isinstance(content, str) and content.strip()) else "empty_content"),
        }
        row["outcome"] = (
            "PRIMARY_SUCCESS" if row["failure_class"] is None else f"PRIMARY_FAILED:{row['failure_class']}"
        )
        report["calls"].append(row)
        guard.record(
            completion=usage.get("completion_tokens") or 0,
            reasoning=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
            error_class=err,
        )
        print(f"{stage:34} http={row['http']} finish={row['finish_reason']!r} "
              f"content_len={row['content_len']:5} schema_valid={row['schema_valid']} "
              f"ct={row['completion_tokens']} rt={row['reasoning_tokens']} -> {row['outcome']}")
        if guard.triggered:
            print(f"COST GUARD: {guard.triggered}")

    executed = [c for c in report["calls"] if not c.get("skipped")]
    primary_success = [c for c in executed if c["failure_class"] is None]
    schema_ok = [c for c in executed if c.get("schema_valid") is True]
    report["cost_guard"] = guard.as_dict()
    report["summary"] = {
        "calls_executed": len(executed),
        "primary_success": len(primary_success),
        "schema_valid": len(schema_ok),
        "empty_content": sum(1 for c in executed if c["failure_class"] == "empty_content"),
    }
    if not executed:
        report["verdict"] = "BLOCKED_OPERATOR_ACTION"
    elif len(primary_success) == len(executed) and len(schema_ok) == len(executed):
        report["verdict"] = "PASS"
    elif primary_success:
        report["verdict"] = "PARTIAL"
    else:
        report["verdict"] = "FAIL"

    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nVERDICT={report['verdict']}  primary_success={len(primary_success)}/{len(executed)}  "
          f"schema_valid={len(schema_ok)}/{len(executed)}")
    print(f"cost: calls={guard.calls} completion_tokens={guard.completion_tokens} "
          f"reasoning_tokens={guard.reasoning_tokens} guard_triggered={bool(guard.triggered)}")
    return 0 if report["verdict"] == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="deepseek_nvidia", choices=["deepseek_direct", "deepseek_nvidia"])
    parser.add_argument("--out", type=Path, default=Path("/tmp/deepseek_host_qualification.json"))
    args = parser.parse_args()
    return run(args.host, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
