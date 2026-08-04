#!/usr/bin/env python3
"""Workspace-aware markdown link audit for agent control-plane surfaces.

Source lineage: gmail-agent-legacy support/context_pack_audit.py, multi-scope rewrite.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#]+)(?:#[^)]+)?\)")

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

SCOPE_PREFIXES: dict[str, list[str]] = {
    "workspace": [
        ".cursor/rules/",
        ".agents/",
        "knowledge/system-atlas/tooling/agent-harness/",
        "AGENTS.md",
        "CLAUDE.md",
    ],
    "gmail-agent": [
        "gmail-agent/.cursor/rules/",
        "gmail-agent/AGENTS.md",
    ],
}

IGNORE_SUFFIXES = {".pyc", ".png", ".jpg", ".gif", ".zip"}
IGNORE_DIRS = {".git", "node_modules", ".artifacts", "__pycache__", ".pytest_cache"}


@dataclass
class Finding:
    source: str
    target: str
    resolved_as: str


def collect_files(root: Path, prefixes: list[str]) -> set[str]:
    known: set[str] = set()
    for prefix in prefixes:
        base = root / prefix.replace("/", os.sep)
        if base.is_file():
            known.add(prefix)
            continue
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                rel = path.relative_to(root).as_posix()
                if any(part in IGNORE_DIRS for part in path.parts):
                    continue
                if path.suffix.lower() in IGNORE_SUFFIXES:
                    continue
                known.add(rel)
    return known


def classify_missing(target: str) -> str:
    normalized = target.replace("\\", "/")
    while normalized.startswith("../"):
        normalized = normalized[3:]
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("http") or "://" in normalized:
        return "external"
    if normalized.startswith("gmail-agent/") or normalized.startswith("knowledge/"):
        return "cross_repo"
    return "unresolved_missing"


def scan_links(root: Path, rel_path: str, known: set[str]) -> list[Finding]:
    path = root / rel_path
    if not path.is_file() or path.suffix.lower() not in {".md", ".mdc"}:
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    findings: list[Finding] = []
    for match in LINK_RE.finditer(text):
        raw = match.group(1).strip()
        if not raw or "://" in raw or raw.startswith("mailto:"):
            continue
        resolved = os.path.normpath(os.path.join(os.path.dirname(rel_path), raw)).replace("\\", "/")
        if resolved in known:
            findings.append(Finding(rel_path, raw, "local"))
        elif (root / resolved).is_file():
            findings.append(Finding(rel_path, raw, "local_abs"))
        else:
            findings.append(Finding(rel_path, raw, classify_missing(raw)))
    return findings


def audit_scope(scope: str) -> dict:
    prefixes = SCOPE_PREFIXES.get(scope)
    if not prefixes:
        return {"scope": scope, "error": "unknown scope"}

    known = collect_files(WORKSPACE_ROOT, prefixes)
    # Also allow workspace files as link targets from gmail-agent rules
    if scope == "gmail-agent":
        known |= collect_files(WORKSPACE_ROOT, SCOPE_PREFIXES["workspace"])

    findings: list[Finding] = []
    for rel in sorted(known):
        if not rel.endswith((".md", ".mdc")):
            continue
        findings.extend(scan_links(WORKSPACE_ROOT, rel, known))

    broken_active = [
        f for f in findings
        if f.resolved_as in {"unresolved_missing"}
    ]
    cross_repo = [f for f in findings if f.resolved_as == "cross_repo"]
    external = [f for f in findings if f.resolved_as == "external"]

    return {
        "scope": scope,
        "scanned_files": len([k for k in known if k.endswith((".md", ".mdc"))]),
        "broken_active": [
            {"source": f.source, "target": f.target, "as": f.resolved_as}
            for f in broken_active
        ],
        "cross_repo_refs": len(cross_repo),
        "external_refs": len(external),
        "verdict": "FAIL" if broken_active else "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Context link audit")
    parser.add_argument(
        "--scope",
        choices=sorted(SCOPE_PREFIXES),
        action="append",
        required=True,
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    reports = [audit_scope(s) for s in args.scope]
    fails = sum(len(r.get("broken_active", [])) for r in reports)
    payload = {"verdict": "FAIL" if fails else "PASS", "reports": reports}

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"context_link_audit — {payload['verdict']}")
        for r in reports:
            print(f"  scope={r['scope']} scanned={r.get('scanned_files', 0)} broken={len(r.get('broken_active', []))}")
            for b in r.get("broken_active", []):
                print(f"    [FAIL] {b['source']} -> {b['target']} ({b['as']})")

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
