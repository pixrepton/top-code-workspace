#!/usr/bin/env python
"""Playwright flow that proves the Row4a desk card against the live snapshot."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from row4a_proof_lib import (  # noqa: E402
    ProofPaths,
    as_text,
    find_exact_desk_membership,
    write_json,
)

TIMEOUT_MS = 30000
LATEST_SNAPSHOT_PATH = "/wp-json/daszek/v3/operational-feed-snapshots/latest"
ENGAGEMENTS_PATH = "/wp-json/daszek/v3/engagements/"
CRITICAL_ANCHORS = (
    "live_response_ok",
    "latest_matches_handoff_snapshot",
    "latest_matches_signal",
    "detail_contains_latest_title",
)
MAIN_SCREEN_VISIBLE_JS = """() => {
                    const main = document.getElementById('main-screen');
                    return !!main && window.getComputedStyle(main).display !== 'none';
                }"""


@dataclass
class ProofContext:
    paths: ProofPaths
    base_url: str
    login: str
    password: str
    expected: dict[str, Any]


@dataclass
class ProofObservations:
    latest_snapshot: dict[str, Any]
    membership: dict[str, Any]
    live_response: Any
    live_body: Any
    detail_text: str


@dataclass
class ProofDiagnostics:
    """Console, page-error and network signals captured during the run."""

    network: list[dict[str, Any]] = field(default_factory=list)
    console_messages: list[dict[str, str]] = field(default_factory=list)
    page_errors: list[dict[str, str]] = field(default_factory=list)
    failed_requests: list[dict[str, Any]] = field(default_factory=list)

    def attach(self, page: Any) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("requestfailed", self._on_failed_request)
        page.on("response", self._on_response)

    def _on_console(self, msg: Any) -> None:
        self.console_messages.append({"type": msg.type, "text": msg.text})

    def _on_page_error(self, err: Exception) -> None:
        self.page_errors.append({"name": err.__class__.__name__, "message": str(err)})

    def _on_failed_request(self, request: Any) -> None:
        self.failed_requests.append(
            {"url": request.url, "method": request.method, "failure": request.failure}
        )

    def _on_response(self, response: Any) -> None:
        entry: dict[str, Any] = {
            "url": response.url,
            "status": response.status,
            "method": response.request.method,
        }
        if _is_recorded_body(response.url):
            entry["body"] = _safe_body(response)
        self.network.append(entry)

    def console_payload(self) -> dict[str, Any]:
        return {
            "console": self.console_messages,
            "pageErrors": self.page_errors,
            "requestsFailed": self.failed_requests,
        }


def _is_recorded_body(url: str) -> bool:
    return LATEST_SNAPSHOT_PATH in url or ENGAGEMENTS_PATH in url


def _safe_body(response: Any) -> str:
    try:
        return response.text()
    except Exception:
        return ""


def persist_diagnostics(paths: ProofPaths, diagnostics: ProofDiagnostics, anchors: dict[str, Any]) -> None:
    write_json(paths.network, diagnostics.network)
    write_json(paths.console, diagnostics.console_payload())
    write_json(paths.anchors, anchors)


def critical_anchors_ok(anchors: dict[str, Any]) -> bool:
    return all(anchors.get(key) is True for key in CRITICAL_ANCHORS)


def _ok_get_response(url_fragment: str) -> Callable[[Any], bool]:
    def matches(response: Any) -> bool:
        if url_fragment not in response.url:
            return False
        if response.request.method != "GET":
            return False
        return response.status == 200

    return matches


def dismiss_onboarding(page: Any) -> None:
    skip_button = page.locator("#onboarding-skip")
    if skip_button.count() == 0:
        return
    try:
        if skip_button.first.is_visible():
            skip_button.first.click()
    except Exception:
        pass


def login_and_load_snapshot(page: Any, context: ProofContext) -> dict[str, Any]:
    page.goto(context.base_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    page.locator('#login-form input[name="login"]').fill(context.login)
    page.locator('#login-form input[name="password"]').fill(context.password)

    latest_response_info = page.expect_response(
        _ok_get_response(LATEST_SNAPSHOT_PATH),
        timeout=TIMEOUT_MS,
    )
    with latest_response_info as latest_wait:
        page.locator('#login-form button[type="submit"]').click()

    page.wait_for_function(MAIN_SCREEN_VISIBLE_JS, timeout=TIMEOUT_MS)
    dismiss_onboarding(page)

    latest_payload = latest_wait.value.json()
    return latest_payload.get("snapshot", {}) if isinstance(latest_payload, dict) else {}


def require_membership(latest_snapshot: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    membership = find_exact_desk_membership(latest_snapshot, expected)
    if not membership["found"]:
        raise RuntimeError("Exact snapshot membership not found for Row4a card.")
    actual_snapshot_id = as_text(latest_snapshot.get("snapshot_id"))
    if expected["snapshot_id"] and actual_snapshot_id != expected["snapshot_id"]:
        raise RuntimeError(
            f"Latest snapshot mismatch. expected={expected['snapshot_id']} actual={actual_snapshot_id}"
        )
    return membership


def _snapshot_source(latest_snapshot: dict[str, Any], key: str) -> str:
    return as_text((latest_snapshot.get("source") or {}).get(key))


def write_membership_file(
    context: ProofContext,
    latest_snapshot: dict[str, Any],
    membership: dict[str, Any],
) -> None:
    expected = context.expected
    latest_snapshot_id = as_text(latest_snapshot.get("snapshot_id"))
    write_json(
        context.paths.exact_membership,
        {
            "proof_dir": str(context.paths.proof_dir),
            "handoff_snapshot_id": expected["snapshot_id"],
            "latest_snapshot_id": latest_snapshot_id,
            "latest_matches_handoff_snapshot": latest_snapshot_id == expected["snapshot_id"],
            "expected_message_id": expected["message_id"],
            "expected_signal_id": expected["signal_id"],
            "expected_engagement_id": expected["engagement_id"],
            "expected_case_id": expected["case_id"],
            "expected_note_id": expected["note_id"],
            "expected_title": expected["title"],
            "membership_found": membership["found"],
            "membership": membership,
            "latest_source_run_id": _snapshot_source(latest_snapshot, "source_run_id"),
            "latest_trigger_message_id": _snapshot_source(latest_snapshot, "trigger_message_id"),
        },
    )


def open_card_detail(page: Any, context: ProofContext, membership: dict[str, Any]) -> tuple[Any, Any, str]:
    card_selector = f'button.record-main[data-open-note="{membership["card_id"]}"]'
    page.wait_for_selector(card_selector, timeout=TIMEOUT_MS)
    page.screenshot(path=str(context.paths.before_shot), full_page=True)

    os_events_fragment = f"{ENGAGEMENTS_PATH}{context.expected['engagement_id']}/os-events"
    detail_response_info = page.expect_response(
        _ok_get_response(os_events_fragment),
        timeout=TIMEOUT_MS,
    )
    with detail_response_info as detail_wait:
        page.locator(card_selector).click()

    live_response = detail_wait.value
    live_body = live_response.json()

    page.wait_for_selector(".detail-section-os-events .os-event-row", timeout=TIMEOUT_MS)
    page.screenshot(path=str(context.paths.detail_shot), full_page=True)
    return live_response, live_body, page.locator("#detail-panel").inner_text()


def _live_body_facts(live_body: Any) -> dict[str, Any]:
    if not isinstance(live_body, dict):
        return {"ok": False, "engagement_id": "", "items_count": 0}
    items = live_body.get("items")
    return {
        "ok": bool(live_body.get("ok")),
        "engagement_id": as_text(live_body.get("engagement_id")),
        "items_count": len(items) if isinstance(items, list) else 0,
    }


def build_anchors(
    context: ProofContext,
    observations: ProofObservations,
    diagnostics: ProofDiagnostics,
) -> dict[str, Any]:
    expected = context.expected
    membership = observations.membership
    latest_snapshot = observations.latest_snapshot
    latest_snapshot_id = as_text(latest_snapshot.get("snapshot_id"))
    live = _live_body_facts(observations.live_body)
    return {
        "proof_dir": str(context.paths.proof_dir),
        "page_url": context.base_url,
        "message_id": expected["message_id"],
        "signal_id": expected["signal_id"],
        "trace_id": expected["trace_id"],
        "trace_id_source": expected["trace_id_source"],
        "engagement_id": expected["engagement_id"],
        "case_id": expected["case_id"],
        "note_id": membership["card_id"],
        "snapshot_id": expected["snapshot_id"],
        "handoff_title": expected["title"],
        "latest_snapshot_id": latest_snapshot_id,
        "latest_title": membership["title"],
        "latest_source_signal_ids": membership["source_signal_ids"],
        "latest_trigger_message_id": _snapshot_source(latest_snapshot, "trigger_message_id"),
        "live_request_url": observations.live_response.url,
        "live_request_status": observations.live_response.status,
        "live_response_ok": live["ok"],
        "live_response_engagement_id": live["engagement_id"],
        "live_response_items_count": live["items_count"],
        "latest_matches_handoff_snapshot": latest_snapshot_id == expected["snapshot_id"],
        "latest_matches_signal": expected["signal_id"] in membership["source_signal_ids"],
        "latest_title_matches_handoff": membership["title"] == expected["title"],
        "detail_contains_latest_title": membership["title"] in observations.detail_text,
        "membership_found": membership["found"],
        "js_errors": len(diagnostics.page_errors),
        "failed_requests": len(diagnostics.failed_requests),
    }


def execute_proof(page: Any, context: ProofContext, diagnostics: ProofDiagnostics) -> dict[str, Any]:
    latest_snapshot = login_and_load_snapshot(page, context)
    membership = require_membership(latest_snapshot, context.expected)
    write_membership_file(context, latest_snapshot, membership)
    live_response, live_body, detail_text = open_card_detail(page, context, membership)
    observations = ProofObservations(
        latest_snapshot=latest_snapshot,
        membership=membership,
        live_response=live_response,
        live_body=live_body,
        detail_text=detail_text,
    )
    return build_anchors(context, observations, diagnostics)


def run_browser_proof(context: ProofContext) -> int:
    diagnostics = ProofDiagnostics()
    anchors: dict[str, Any] = {"proof_dir": str(context.paths.proof_dir)}
    exit_code = 1

    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(headless=True)
        browser_context = browser.new_context(ignore_https_errors=True)
        page = browser_context.new_page()
        diagnostics.attach(page)
        try:
            anchors = execute_proof(page, context, diagnostics)
            exit_code = 0 if critical_anchors_ok(anchors) else 1
        except Exception as exc:
            anchors["error"] = str(exc)
            exit_code = 1
        finally:
            persist_diagnostics(context.paths, diagnostics, anchors)
            browser_context.close()
            browser.close()

    return exit_code
