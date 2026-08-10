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
    MAX_SINGLE_CALL_REASONING_TOKENS,
    MAX_TOTAL_COMPLETION_TOKENS,
    MAX_TOTAL_REASONING_TOKENS,
    CostGuard,
    classify_http,
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
