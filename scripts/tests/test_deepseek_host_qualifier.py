"""Deterministic tests for the DeepSeek host qualifier's cost guard.

The guard exists because a previous diagnostic consumed 38,699 completion tokens and zeroed a
provider account. These tests verify the limits actually stop a run — no provider is contacted.

    python -m pytest scripts/tests/test_deepseek_host_qualifier.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from qualify_deepseek_host import (  # noqa: E402
    MAX_CALLS,
    SMOKE_MAX_TOKENS,
    MAX_SINGLE_CALL_REASONING_TOKENS,
    MAX_TOTAL_COMPLETION_TOKENS,
    MAX_TOTAL_REASONING_TOKENS,
    build_connectivity_smoke_request,
    CostGuard,
    classify_http,
    error_detail,
    summarize_chat_response,
)


def test_limits_are_small_enough_to_be_diagnostic():
    """A 'guard' that permits the previous 38,699-token incident is not a guard."""
    assert MAX_CALLS == 6
    assert MAX_TOTAL_COMPLETION_TOKENS < 38_699
    assert MAX_TOTAL_REASONING_TOKENS < MAX_TOTAL_COMPLETION_TOKENS


def test_call_budget_stops_the_run():
    guard = CostGuard()
    for _ in range(MAX_CALLS):
        assert guard.may_call()
        guard.record(completion=10, reasoning=0, error_class=None)
    assert guard.may_call() is False
    assert "max_calls" in guard.triggered


def test_completion_token_budget_stops_the_run():
    guard = CostGuard()
    guard.record(completion=MAX_TOTAL_COMPLETION_TOKENS, reasoning=0, error_class=None)
    assert guard.may_call() is False
    assert "max_total_completion_tokens" in guard.triggered


def test_reasoning_token_budget_stops_the_run():
    """Accumulated across calls, each individually under the per-call ceiling.

    Putting the whole reasoning budget into one call would trip the single-call explosion guard
    instead, which is a different (also correct) stop condition.
    """
    guard = CostGuard()
    per_call = MAX_SINGLE_CALL_REASONING_TOKENS - 1
    spent = 0
    while spent < MAX_TOTAL_REASONING_TOKENS and guard.may_call():
        guard.record(completion=1, reasoning=per_call, error_class=None)
        spent += per_call

    assert guard.may_call() is False
    assert "max_total_reasoning_tokens" in guard.triggered
    assert guard.reasoning_tokens >= MAX_TOTAL_REASONING_TOKENS


def test_billing_error_aborts_immediately():
    """The exact failure that zeroed the account must stop the run on its first appearance."""
    guard = CostGuard()
    guard.record(completion=0, reasoning=0, error_class="quota_exhausted")
    assert guard.may_call() is False
    assert "quota_exhausted" in guard.triggered


def test_auth_and_rate_limit_also_abort():
    for error_class in ("auth", "rate_limit"):
        guard = CostGuard()
        guard.record(completion=0, reasoning=0, error_class=error_class)
        assert guard.may_call() is False, error_class


def test_single_call_reasoning_explosion_aborts():
    guard = CostGuard()
    guard.record(completion=100, reasoning=MAX_SINGLE_CALL_REASONING_TOKENS + 1, error_class=None)
    assert guard.may_call() is False
    assert "token explosion" in guard.triggered


def test_ordinary_call_does_not_trigger_the_guard():
    guard = CostGuard()
    guard.record(completion=500, reasoning=300, error_class=None)
    assert guard.may_call() is True
    assert guard.triggered is None


def test_402_is_classified_as_quota_exhausted():
    assert classify_http(402, {"error": {"message": "Insufficient Balance"}}) == "quota_exhausted"


def test_insufficient_credits_on_a_non_402_status_is_still_quota():
    assert classify_http(400, {"error": {"message": "requires more credits"}}) == "quota_exhausted"


def test_auth_and_rate_limit_statuses_are_classified():
    assert classify_http(401, {}) == "auth"
    assert classify_http(403, {}) == "auth"
    assert classify_http(429, {}) == "rate_limit"


def test_success_has_no_error_class():
    assert classify_http(200, {}) is None


# ── error-envelope parsing ──────────────────────────────────────────────────────────
#
# Regression cover for a real diagnostic failure. The NVIDIA NIM bridge qualification returned
# HTTP 410 with a body that stated its own cause verbatim, but the qualifier reported
# `error_message=""` because it only understood the OpenAI-style `{"error": {"message": ...}}`
# envelope. NIM answers with RFC 7807 `application/problem+json`. The body below is the exact
# response captured on 2026-08-11 — these tests replay it rather than re-spending a call.

NIM_410_BODY = {
    "type": "about:blank",
    "title": "Gone",
    "status": 410,
    "detail": (
        "The model 'deepseek-ai/deepseek-v4-flash' has reached its end of life on "
        "2026-08-07T09:00:00Z and is no longer available."
    ),
}


def test_rfc7807_detail_is_read_not_dropped():
    assert "end of life" in error_detail(NIM_410_BODY)


def test_openai_envelope_still_wins_when_present():
    assert error_detail({"error": {"message": "Insufficient Balance"}, "detail": "ignored"}) == (
        "Insufficient Balance"
    )


def test_missing_reason_yields_empty_string_not_an_exception():
    assert error_detail({}) == ""
    assert error_detail(None) == ""
    assert error_detail({"error": "plain string form"}) == "plain string form"


def test_retired_model_is_classified_as_model_unavailable():
    """410 is a fact about the configured model id, not a transport fault."""
    assert classify_http(410, NIM_410_BODY) == "model_unavailable"


def test_end_of_life_wording_is_caught_on_other_statuses_too():
    assert classify_http(400, {"detail": "model X is no longer available"}) == "model_unavailable"


def test_404_distinguishes_a_missing_model_from_a_missing_route():
    assert classify_http(404, {"detail": "model not found"}) == "model_unavailable"
    assert classify_http(404, {}) == "not_found"


def test_model_unavailable_aborts_instead_of_burning_six_calls():
    guard = CostGuard()
    guard.record(completion=0, reasoning=0, error_class="model_unavailable")
    assert guard.may_call() is False
    assert "model_unavailable" in guard.triggered


def test_connectivity_smoke_request_is_deterministic_and_not_underbudgeted():
    request = build_connectivity_smoke_request("deepseek-v4-flash")
    assert request["model"] == "deepseek-v4-flash"
    assert request["messages"] == [{"role": "user", "content": "Reply with exactly: OK"}]
    assert request["max_tokens"] == SMOKE_MAX_TOKENS
    assert request["max_tokens"] >= 16
    assert request["thinking"] == {"type": "disabled"}
    assert request["temperature"] == 0.0
    assert request["stream"] is False


def test_summarize_chat_response_records_safe_shape_for_reasoning_only_empty_content():
    summary = summarize_chat_response(
        {
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "", "reasoning_content": "thinking"},
                }
            ],
            "usage": {
                "prompt_tokens": 7,
                "completion_tokens": 8,
                "total_tokens": 15,
                "completion_tokens_details": {"reasoning_tokens": 8},
            },
        }
    )
    assert summary["returned_model"] == "deepseek-v4-flash"
    assert summary["choices_count"] == 1
    assert summary["finish_reason"] == "length"
    assert summary["message_content_present"] is True
    assert summary["message_content_len"] == 0
    assert summary["reasoning_content_present"] is True
    assert summary["reasoning_content_len"] == len("thinking")
    assert summary["usage_completion_tokens"] == 8
    assert summary["usage_reasoning_tokens"] == 8
    assert summary["non_empty_usable_content"] is False


def test_summarize_chat_response_handles_non_empty_final_content():
    summary = summarize_chat_response(
        {
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "OK", "reasoning_content": ""},
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        }
    )
    assert summary["message_content_type"] == "str"
    assert summary["message_content_len"] == 2
    assert summary["reasoning_content_present"] is False
    assert summary["non_empty_usable_content"] is True
