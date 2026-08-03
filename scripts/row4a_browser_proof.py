#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from row4a_proof_support import (  # noqa: E402
    ENGAGEMENTS_PATH,
    LATEST_SNAPSHOT_PATH,
    ProofObservation,
    ProofPaths,
    ProofRecorder,
    ProofRequest,
    SnapshotMatch,
    as_text,
    expected_identity_from_handoff_item,
    find_exact_desk_membership,
    membership_payload,
    write_json,
)


TIMEOUT_MS = 30000
MAIN_SCREEN_VISIBLE_JS = """() => {
                    const main = document.getElementById('main-screen');
                    return !!main && window.getComputedStyle(main).display !== 'none';
                }"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-dir", required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--login", required=True)
    parser.add_argument("--password", required=True)
    return parser.parse_args()


def expected_identity_from_handoff(handoff_path: Path) -> dict[str, str | None]:
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    if handoff.get("actionable") is not True or not isinstance(handoff.get("item"), dict):
        raise RuntimeError("Handoff is not actionable.")
    return expected_identity_from_handoff_item(handoff["item"])


def _is_latest_snapshot_response(response: Any) -> bool:
    return (
        LATEST_SNAPSHOT_PATH in response.url
        and response.request.method == "GET"
        and response.status == 200
    )


def _dismiss_onboarding(page: Any) -> None:
    skip_button = page.locator("#onboarding-skip")
    if skip_button.count() == 0:
        return
    try:
        if skip_button.first.is_visible():
            skip_button.first.click()
    except Exception:
        pass


def log_in_and_await_latest(page: Any, request: ProofRequest) -> Any:
    """Log in, wait for the operator screen, and return the awaited `latest` response."""
    page.goto(request.base_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    page.locator('#login-form input[name="login"]').fill(request.login)
    page.locator('#login-form input[name="password"]').fill(request.password)

    latest_response_info = page.expect_response(_is_latest_snapshot_response, timeout=TIMEOUT_MS)
    with latest_response_info as latest_wait:
        page.locator('#login-form button[type="submit"]').click()

    page.wait_for_function(MAIN_SCREEN_VISIBLE_JS, timeout=TIMEOUT_MS)
    _dismiss_onboarding(page)
    return latest_wait.value


def latest_snapshot_from(response: Any) -> dict[str, Any]:
    payload = response.json()
    return payload.get("snapshot", {}) if isinstance(payload, dict) else {}


def resolve_membership(latest_snapshot: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Locate the Row4a card in the live snapshot, failing loudly on any identity mismatch."""
    membership = find_exact_desk_membership(latest_snapshot, expected)
    if not membership["found"]:
        raise RuntimeError("Exact snapshot membership not found for Row4a card.")
    actual_snapshot_id = as_text(latest_snapshot.get("snapshot_id"))
    if expected["snapshot_id"] and actual_snapshot_id != expected["snapshot_id"]:
        raise RuntimeError(
            f"Latest snapshot mismatch. expected={expected['snapshot_id']} actual={actual_snapshot_id}"
        )
    return membership


def open_card_and_read_detail(page: Any, paths: ProofPaths, engagement_id: str, card_id: str) -> tuple[Any, Any, str]:
    """Click the desk card and return (live os-events response, parsed body, detail text)."""
    card_selector = f'button.record-main[data-open-note="{card_id}"]'
    page.wait_for_selector(card_selector, timeout=TIMEOUT_MS)
    page.screenshot(path=str(paths.card_before_click), full_page=True)

    def is_os_events_response(response: Any) -> bool:
        return (
            f"{ENGAGEMENTS_PATH}{engagement_id}/os-events" in response.url
            and response.request.method == "GET"
            and response.status == 200
        )

    detail_response_info = page.expect_response(is_os_events_response, timeout=TIMEOUT_MS)
    with detail_response_info as detail_wait:
        page.locator(card_selector).click()

    live_response = detail_wait.value
    live_body = live_response.json()

    page.wait_for_selector(".detail-section-os-events .os-event-row", timeout=TIMEOUT_MS)
    page.screenshot(path=str(paths.detail_after_click), full_page=True)
    return live_response, live_body, page.locator("#detail-panel").inner_text()


def run_proof(page: Any, request: ProofRequest, recorder: ProofRecorder) -> int:
    paths = request.paths
    expected = request.expected
    latest_snapshot = latest_snapshot_from(log_in_and_await_latest(page, request))
    match = SnapshotMatch(
        proof_dir=paths.proof_dir,
        expected=expected,
        latest_snapshot=latest_snapshot,
        membership=resolve_membership(latest_snapshot, expected),
    )
    write_json(paths.exact_membership, membership_payload(match))

    live_response, live_body, detail_text = open_card_and_read_detail(
        page, paths, expected["engagement_id"], match.membership["card_id"]
    )
    recorder.record_anchors(
        ProofObservation(
            match=match,
            page_url=request.base_url,
            live_response=live_response,
            live_body=live_body,
            detail_text=detail_text,
        )
    )
    return 0 if recorder.critical_anchors_ok() else 1


def build_request(args: argparse.Namespace) -> ProofRequest:
    return ProofRequest(
        base_url=args.base_url,
        login=args.login,
        password=args.password,
        paths=ProofPaths.for_dir(Path(args.proof_dir).resolve()),
        expected=expected_identity_from_handoff(Path(args.handoff).resolve()),
    )


def main() -> int:
    request = build_request(parse_args())
    recorder = ProofRecorder(request.paths.proof_dir)

    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        recorder.attach(page)
        try:
            exit_code = run_proof(page, request, recorder)
        except Exception as exc:
            recorder.record_error(exc)
            exit_code = 1
        finally:
            recorder.persist(request.paths)
            context.close()
            browser.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
