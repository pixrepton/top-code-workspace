"""Payload, path and diagnostics helpers for the Row4a browser proof harness."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LATEST_SNAPSHOT_PATH = "/wp-json/daszek/v3/operational-feed-snapshots/latest"
ENGAGEMENTS_PATH = "/wp-json/daszek/v3/engagements/"
CRITICAL_ANCHOR_KEYS = (
    "live_response_ok",
    "latest_matches_handoff_snapshot",
    "latest_matches_signal",
    "detail_contains_latest_title",
)


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
    engagement_id = as_text(item.get("engagement_id"))
    return {
        "message_id": as_text(item.get("source_message_id") or item.get("message_id")),
        "signal_id": as_text(item.get("signal_id")),
        "trace_id": trace_id or None,
        "trace_id_source": "handoff.item.trace_id" if trace_id else "missing",
        "engagement_id": engagement_id,
        "case_id": as_text(item.get("case_id")),
        "note_id": as_text(item.get("note_id")) or (f"desk-{engagement_id}" if engagement_id else ""),
        "snapshot_id": as_text(item.get("snapshot_id")),
        "title": as_text(item.get("title")),
    }


def _desk_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    feed = snapshot.get("feed") if isinstance(snapshot.get("feed"), dict) else {}
    desk = feed.get("desk") if isinstance(feed.get("desk"), list) else []
    return [row for row in desk if isinstance(row, dict)]


def _row_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "found": True,
        "card_id": as_text(row.get("note_id") or row.get("desk_note_id")),
        "title": as_text(row.get("title") or row.get("title_pl")),
        "source_message_id": as_text(row.get("source_message_id") or row.get("message_id")),
        "source_signal_ids": as_list(row.get("source_signal_ids")),
        "engagement_id": as_text(row.get("engagement_id")),
        "case_id": as_text(row.get("case_id")),
    }


# (expected key, desk row key) pairs that must be equal when the expected value is set.
_IDENTITY_EQUALITY_FIELDS = (
    ("message_id", "source_message_id"),
    ("engagement_id", "engagement_id"),
    ("case_id", "case_id"),
    ("note_id", "card_id"),
)


def _identity_matches(identity: dict[str, Any], expected: dict[str, str]) -> bool:
    """Every non-empty expected identity field must match the desk row exactly."""
    if expected["signal_id"] and expected["signal_id"] not in identity["source_signal_ids"]:
        return False
    return all(
        identity[row_key] == expected[expected_key]
        for expected_key, row_key in _IDENTITY_EQUALITY_FIELDS
        if expected[expected_key]
    )


def _no_membership() -> dict[str, Any]:
    return {
        "found": False,
        "card_id": "",
        "title": "",
        "source_message_id": "",
        "source_signal_ids": [],
        "engagement_id": "",
        "case_id": "",
    }


def find_exact_desk_membership(snapshot: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    for row in _desk_rows(snapshot):
        identity = _row_identity(row)
        if _identity_matches(identity, expected):
            return identity
    return _no_membership()


@dataclass(frozen=True)
class ProofPaths:
    """Artifact locations for one proof directory."""

    proof_dir: Path
    network: Path
    console: Path
    anchors: Path
    exact_membership: Path
    card_before_click: Path
    detail_after_click: Path

    @classmethod
    def for_dir(cls, proof_dir: Path) -> ProofPaths:
        browser_dir = proof_dir / "browser"
        return cls(
            proof_dir=proof_dir,
            network=browser_dir / "network.json",
            console=browser_dir / "console.json",
            anchors=browser_dir / "anchors.json",
            exact_membership=proof_dir / "exact-snapshot-membership.json",
            card_before_click=browser_dir / "card-before-click.png",
            detail_after_click=browser_dir / "detail-after-click.png",
        )


@dataclass(frozen=True)
class ProofRequest:
    """Resolved CLI inputs for one Row4a proof run."""

    base_url: str
    login: str
    password: str
    paths: ProofPaths
    expected: dict[str, Any]


@dataclass(frozen=True)
class SnapshotMatch:
    """The Row4a desk card as located in the live `latest` snapshot."""

    proof_dir: Path
    expected: dict[str, Any]
    latest_snapshot: dict[str, Any]
    membership: dict[str, Any]

    @property
    def latest_snapshot_id(self) -> str:
        return as_text(self.latest_snapshot.get("snapshot_id"))

    @property
    def snapshot_source(self) -> dict[str, Any]:
        return self.latest_snapshot.get("source") or {}


@dataclass(frozen=True)
class ProofObservation:
    """A successful Row4a pass: the snapshot match plus the live detail request."""

    match: SnapshotMatch
    page_url: str
    live_response: Any
    live_body: Any
    detail_text: str


def membership_payload(match: SnapshotMatch) -> dict[str, Any]:
    expected = match.expected
    membership = match.membership
    source = match.snapshot_source
    return {
        "proof_dir": str(match.proof_dir),
        "handoff_snapshot_id": expected["snapshot_id"],
        "latest_snapshot_id": match.latest_snapshot_id,
        "latest_matches_handoff_snapshot": match.latest_snapshot_id == expected["snapshot_id"],
        "expected_message_id": expected["message_id"],
        "expected_signal_id": expected["signal_id"],
        "expected_engagement_id": expected["engagement_id"],
        "expected_case_id": expected["case_id"],
        "expected_note_id": expected["note_id"],
        "expected_title": expected["title"],
        "membership_found": membership["found"],
        "membership": membership,
        "latest_source_run_id": as_text(source.get("source_run_id")),
        "latest_trigger_message_id": as_text(source.get("trigger_message_id")),
    }


def _live_response_facts(live_body: Any) -> dict[str, Any]:
    body = live_body if isinstance(live_body, dict) else {}
    items = body.get("items")
    return {
        "live_response_ok": bool(body.get("ok")),
        "live_response_engagement_id": as_text(body.get("engagement_id")),
        "live_response_items_count": len(items) if isinstance(items, list) else 0,
    }


def build_anchors(observation: ProofObservation, page_errors: int, failed_requests: int) -> dict[str, Any]:
    match = observation.match
    expected = match.expected
    membership = match.membership
    anchors: dict[str, Any] = {
        "proof_dir": str(match.proof_dir),
        "page_url": observation.page_url,
        "message_id": expected["message_id"],
        "signal_id": expected["signal_id"],
        "trace_id": expected["trace_id"],
        "trace_id_source": expected["trace_id_source"],
        "engagement_id": expected["engagement_id"],
        "case_id": expected["case_id"],
        "note_id": membership["card_id"],
        "snapshot_id": expected["snapshot_id"],
        "handoff_title": expected["title"],
        "latest_snapshot_id": match.latest_snapshot_id,
        "latest_title": membership["title"],
        "latest_source_signal_ids": membership["source_signal_ids"],
        "latest_trigger_message_id": as_text(match.snapshot_source.get("trigger_message_id")),
        "live_request_url": observation.live_response.url,
        "live_request_status": observation.live_response.status,
    }
    anchors.update(_live_response_facts(observation.live_body))
    anchors.update(
        {
            "latest_matches_handoff_snapshot": match.latest_snapshot_id == expected["snapshot_id"],
            "latest_matches_signal": expected["signal_id"] in membership["source_signal_ids"],
            "latest_title_matches_handoff": membership["title"] == expected["title"],
            "detail_contains_latest_title": membership["title"] in observation.detail_text,
            "membership_found": membership["found"],
            "js_errors": page_errors,
            "failed_requests": failed_requests,
        }
    )
    return anchors


class ProofRecorder:
    """Collects browser diagnostics and the anchors payload for one proof run."""

    def __init__(self, proof_dir: Path) -> None:
        self.network: list[dict[str, Any]] = []
        self.console: list[dict[str, str]] = []
        self.page_errors: list[dict[str, str]] = []
        self.failed_requests: list[dict[str, Any]] = []
        self.anchors: dict[str, Any] = {"proof_dir": str(proof_dir)}

    def attach(self, page: Any) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)

    def _on_console(self, msg: Any) -> None:
        self.console.append({"type": msg.type, "text": msg.text})

    def _on_page_error(self, err: Exception) -> None:
        self.page_errors.append({"name": err.__class__.__name__, "message": str(err)})

    def _on_request_failed(self, request: Any) -> None:
        self.failed_requests.append(
            {"url": request.url, "method": request.method, "failure": request.failure}
        )

    def _on_response(self, response: Any) -> None:
        url = response.url
        entry: dict[str, Any] = {
            "url": url,
            "status": response.status,
            "method": response.request.method,
        }
        if LATEST_SNAPSHOT_PATH in url or ENGAGEMENTS_PATH in url:
            try:
                entry["body"] = response.text()
            except Exception:
                entry["body"] = ""
        self.network.append(entry)

    def record_anchors(self, observation: ProofObservation) -> None:
        self.anchors = build_anchors(observation, len(self.page_errors), len(self.failed_requests))

    def record_error(self, exc: Exception) -> None:
        self.anchors["error"] = str(exc)

    def critical_anchors_ok(self) -> bool:
        return all(self.anchors.get(key) is True for key in CRITICAL_ANCHOR_KEYS)

    def persist(self, paths: ProofPaths) -> None:
        write_json(paths.network, self.network)
        write_json(
            paths.console,
            {
                "console": self.console,
                "pageErrors": self.page_errors,
                "requestsFailed": self.failed_requests,
            },
        )
        write_json(paths.anchors, self.anchors)
