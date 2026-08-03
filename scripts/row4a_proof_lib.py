#!/usr/bin/env python
"""Identity extraction and snapshot matching for the Row4a browser proof."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXACT_MATCH_FIELDS = (
    ("message_id", "message_id"),
    ("engagement_id", "engagement_id"),
    ("case_id", "case_id"),
    ("note_id", "note_id"),
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


@dataclass(frozen=True)
class ProofPaths:
    proof_dir: Path

    @property
    def browser_dir(self) -> Path:
        return self.proof_dir / "browser"

    @property
    def network(self) -> Path:
        return self.browser_dir / "network.json"

    @property
    def console(self) -> Path:
        return self.browser_dir / "console.json"

    @property
    def anchors(self) -> Path:
        return self.browser_dir / "anchors.json"

    @property
    def exact_membership(self) -> Path:
        return self.proof_dir / "exact-snapshot-membership.json"

    @property
    def before_shot(self) -> Path:
        return self.browser_dir / "card-before-click.png"

    @property
    def detail_shot(self) -> Path:
        return self.browser_dir / "detail-after-click.png"


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


def load_handoff_item(handoff_path: Path) -> dict[str, Any]:
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    if handoff.get("actionable") is not True or not isinstance(handoff.get("item"), dict):
        raise RuntimeError("Handoff is not actionable.")
    return handoff["item"]


def _desk_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    feed = snapshot.get("feed") if isinstance(snapshot.get("feed"), dict) else {}
    desk = feed.get("desk") if isinstance(feed.get("desk"), list) else []
    return [row for row in desk if isinstance(row, dict)]


def _row_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "note_id": as_text(row.get("note_id") or row.get("desk_note_id")),
        "title": as_text(row.get("title") or row.get("title_pl")),
        "message_id": as_text(row.get("source_message_id") or row.get("message_id")),
        "signal_ids": as_list(row.get("source_signal_ids")),
        "engagement_id": as_text(row.get("engagement_id")),
        "case_id": as_text(row.get("case_id")),
    }


def _row_matches(identity: dict[str, Any], expected: dict[str, str]) -> bool:
    for expected_key, identity_key in EXACT_MATCH_FIELDS:
        wanted = expected[expected_key]
        if wanted and identity[identity_key] != wanted:
            return False
    signal_id = expected["signal_id"]
    if signal_id and signal_id not in identity["signal_ids"]:
        return False
    return True


def _empty_membership() -> dict[str, Any]:
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
        if not _row_matches(identity, expected):
            continue
        return {
            "found": True,
            "card_id": identity["note_id"],
            "title": identity["title"],
            "source_message_id": identity["message_id"],
            "source_signal_ids": identity["signal_ids"],
            "engagement_id": identity["engagement_id"],
            "case_id": identity["case_id"],
        }
    return _empty_membership()
