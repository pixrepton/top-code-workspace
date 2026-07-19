#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


def as_text(value: Any) -> str:
    return str(value or "").strip()


def as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [as_text(item) for item in value if as_text(item)]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def expected_identity_from_handoff_item(item: dict[str, Any]) -> dict[str, str | None]:
    trace_id = as_text(item.get("trace_id"))
    return {
        "message_id": as_text(item.get("source_message_id") or item.get("message_id")),
        "signal_id": as_text(item.get("signal_id")),
        "trace_id": trace_id or None,
        "trace_id_source": "handoff.item.trace_id" if trace_id else "missing",
        "engagement_id": as_text(item.get("engagement_id")),
        "case_id": as_text(item.get("case_id")),
        "note_id": as_text(item.get("note_id"))
        or (f"desk-{as_text(item.get('engagement_id'))}" if as_text(item.get("engagement_id")) else ""),
        "snapshot_id": as_text(item.get("snapshot_id")),
        "title": as_text(item.get("title")),
    }


def find_exact_desk_membership(snapshot: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    feed = snapshot.get("feed") if isinstance(snapshot.get("feed"), dict) else {}
    desk = feed.get("desk") if isinstance(feed.get("desk"), list) else []
    for row in desk:
        if not isinstance(row, dict):
            continue
        row_note_id = as_text(row.get("note_id") or row.get("desk_note_id"))
        row_title = as_text(row.get("title") or row.get("title_pl"))
        row_message_id = as_text(row.get("source_message_id") or row.get("message_id"))
        row_signal_ids = as_list(row.get("source_signal_ids"))
        row_engagement_id = as_text(row.get("engagement_id"))
        row_case_id = as_text(row.get("case_id"))
        if expected["message_id"] and row_message_id != expected["message_id"]:
            continue
        if expected["signal_id"] and expected["signal_id"] not in row_signal_ids:
            continue
        if expected["engagement_id"] and row_engagement_id != expected["engagement_id"]:
            continue
        if expected["case_id"] and row_case_id != expected["case_id"]:
            continue
        if expected["note_id"] and row_note_id != expected["note_id"]:
            continue
        return {
            "found": True,
            "card_id": row_note_id,
            "title": row_title,
            "source_message_id": row_message_id,
            "source_signal_ids": row_signal_ids,
            "engagement_id": row_engagement_id,
            "case_id": row_case_id,
        }
    return {
        "found": False,
        "card_id": "",
        "title": "",
        "source_message_id": "",
        "source_signal_ids": [],
        "engagement_id": "",
        "case_id": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof-dir", required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--login", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    proof_dir = Path(args.proof_dir).resolve()
    handoff_path = Path(args.handoff).resolve()
    browser_dir = proof_dir / "browser"
    network_path = browser_dir / "network.json"
    console_path = browser_dir / "console.json"
    anchors_path = browser_dir / "anchors.json"
    exact_membership_path = proof_dir / "exact-snapshot-membership.json"
    before_shot = browser_dir / "card-before-click.png"
    detail_shot = browser_dir / "detail-after-click.png"

    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    if handoff.get("actionable") is not True or not isinstance(handoff.get("item"), dict):
        raise RuntimeError("Handoff is not actionable.")

    item = handoff["item"]
    expected = expected_identity_from_handoff_item(item)

    network: list[dict[str, Any]] = []
    console_messages: list[dict[str, str]] = []
    page_errors: list[dict[str, str]] = []
    failed_requests: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.firefox.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        def handle_console(msg: Any) -> None:
            console_messages.append({"type": msg.type, "text": msg.text})

        def handle_page_error(err: Exception) -> None:
            page_errors.append(
                {
                    "name": err.__class__.__name__,
                    "message": str(err),
                }
            )

        def handle_failed_request(request: Any) -> None:
            failed_requests.append(
                {
                    "url": request.url,
                    "method": request.method,
                    "failure": request.failure,
                }
            )

        def handle_response(response: Any) -> None:
            url = response.url
            entry: dict[str, Any] = {
                "url": url,
                "status": response.status,
                "method": response.request.method,
            }
            if "/wp-json/daszek/v3/operational-feed-snapshots/latest" in url or "/wp-json/daszek/v3/engagements/" in url:
                try:
                    entry["body"] = response.text()
                except Exception:
                    entry["body"] = ""
            network.append(entry)

        page.on("console", handle_console)
        page.on("pageerror", handle_page_error)
        page.on("requestfailed", handle_failed_request)
        page.on("response", handle_response)

        try:
            page.goto(args.base_url, wait_until="domcontentloaded", timeout=30000)
            page.locator('#login-form input[name="login"]').fill(args.login)
            page.locator('#login-form input[name="password"]').fill(args.password)

            latest_response_info = page.expect_response(
                lambda response: "/wp-json/daszek/v3/operational-feed-snapshots/latest" in response.url
                and response.request.method == "GET"
                and response.status == 200,
                timeout=30000,
            )

            with latest_response_info as latest_wait:
                page.locator('#login-form button[type="submit"]').click()

            page.wait_for_function(
                """() => {
                    const main = document.getElementById('main-screen');
                    return !!main && window.getComputedStyle(main).display !== 'none';
                }""",
                timeout=30000,
            )

            skip_button = page.locator("#onboarding-skip")
            if skip_button.count() > 0:
                try:
                    if skip_button.first.is_visible():
                        skip_button.first.click()
                except Exception:
                    pass

            latest_response = latest_wait.value
            latest_payload = latest_response.json()
            latest_snapshot = latest_payload.get("snapshot", {}) if isinstance(latest_payload, dict) else {}

            membership = find_exact_desk_membership(latest_snapshot, expected)
            if not membership["found"]:
                raise RuntimeError("Exact snapshot membership not found for Row4a card.")
            if expected["snapshot_id"] and as_text(latest_snapshot.get("snapshot_id")) != expected["snapshot_id"]:
                raise RuntimeError(
                    f"Latest snapshot mismatch. expected={expected['snapshot_id']} actual={as_text(latest_snapshot.get('snapshot_id'))}"
                )

            write_json(
                exact_membership_path,
                {
                    "proof_dir": str(proof_dir),
                    "handoff_snapshot_id": expected["snapshot_id"],
                    "latest_snapshot_id": as_text(latest_snapshot.get("snapshot_id")),
                    "latest_matches_handoff_snapshot": as_text(latest_snapshot.get("snapshot_id")) == expected["snapshot_id"],
                    "expected_message_id": expected["message_id"],
                    "expected_signal_id": expected["signal_id"],
                    "expected_engagement_id": expected["engagement_id"],
                    "expected_case_id": expected["case_id"],
                    "expected_note_id": expected["note_id"],
                    "expected_title": expected["title"],
                    "membership_found": membership["found"],
                    "membership": membership,
                    "latest_source_run_id": as_text((latest_snapshot.get("source") or {}).get("source_run_id")),
                    "latest_trigger_message_id": as_text((latest_snapshot.get("source") or {}).get("trigger_message_id")),
                },
            )

            card_selector = f'button.record-main[data-open-note="{membership["card_id"]}"]'
            page.wait_for_selector(card_selector, timeout=30000)
            page.screenshot(path=str(before_shot), full_page=True)

            detail_response_info = page.expect_response(
                lambda response: f"/wp-json/daszek/v3/engagements/{expected['engagement_id']}/os-events" in response.url
                and response.request.method == "GET"
                and response.status == 200,
                timeout=30000,
            )
            with detail_response_info as detail_wait:
                page.locator(card_selector).click()

            live_response = detail_wait.value
            live_body = live_response.json()

            page.wait_for_selector(".detail-section-os-events .os-event-row", timeout=30000)
            page.screenshot(path=str(detail_shot), full_page=True)
            detail_text = page.locator("#detail-panel").inner_text()

            anchors = {
                "proof_dir": str(proof_dir),
                "page_url": args.base_url,
                "message_id": expected["message_id"],
                "signal_id": expected["signal_id"],
                "trace_id": expected["trace_id"],
                "trace_id_source": expected["trace_id_source"],
                "engagement_id": expected["engagement_id"],
                "case_id": expected["case_id"],
                "note_id": membership["card_id"],
                "snapshot_id": expected["snapshot_id"],
                "handoff_title": expected["title"],
                "latest_snapshot_id": as_text(latest_snapshot.get("snapshot_id")),
                "latest_title": membership["title"],
                "latest_source_signal_ids": membership["source_signal_ids"],
                "latest_trigger_message_id": as_text((latest_snapshot.get("source") or {}).get("trigger_message_id")),
                "live_request_url": live_response.url,
                "live_request_status": live_response.status,
                "live_response_ok": bool(isinstance(live_body, dict) and live_body.get("ok")),
                "live_response_engagement_id": as_text(live_body.get("engagement_id") if isinstance(live_body, dict) else ""),
                "live_response_items_count": len(live_body.get("items")) if isinstance(live_body, dict) and isinstance(live_body.get("items"), list) else 0,
                "latest_matches_handoff_snapshot": as_text(latest_snapshot.get("snapshot_id")) == expected["snapshot_id"],
                "latest_matches_signal": expected["signal_id"] in membership["source_signal_ids"],
                "latest_title_matches_handoff": membership["title"] == expected["title"],
                "detail_contains_latest_title": membership["title"] in detail_text,
                "js_errors": len(page_errors),
                "failed_requests": len(failed_requests),
            }

            write_json(anchors_path, anchors)
            write_json(network_path, network)
            write_json(
                console_path,
                {
                    "console": console_messages,
                    "pageErrors": page_errors,
                    "requestsFailed": failed_requests,
                },
            )
        finally:
            context.close()
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
