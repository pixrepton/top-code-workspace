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

# This workspace cites canonical routes as backticked paths far more often than as
# markdown links (e.g. `knowledge/system-atlas/tooling/GIT_AND_CHANGE_CONTROL.md`).
# LINK_RE alone therefore reported broken=0 while six canonical routes were dead.
BACKTICK_PATH_RE = re.compile(
    r"`([A-Za-z0-9_.\-/]+\.(?:md|mdc|ya?ml|py|ps1|json|rules))`"
)

# Fenced blocks hold commands and illustrative paths, not routing claims.
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

# Illustrative or templated citations are not routing claims either.
PLACEHOLDER_MARKERS = ("path/to/", "...", "<", ">", "*", "{", "}", "$", "|")

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
        # "cross_repo" excuses a missing target, so it may only apply when the
        # repository genuinely is not checked out here. When the repo IS present,
        # a missing file is a dead route and must fail. Without this guard the
        # audit silently forgave every dead knowledge/... route.
        repo = normalized.split("/", 1)[0]
        if not (WORKSPACE_ROOT / repo).is_dir():
            return "cross_repo"
        return "unresolved_missing"
    return "unresolved_missing"


def _resolve_relative(rel_path: str, raw: str) -> str:
    return os.path.normpath(os.path.join(os.path.dirname(rel_path), raw)).replace("\\", "/")


def scan_backtick_paths(root: Path, rel_path: str, text: str, known: set[str]) -> list[Finding]:
    """Audit backticked path citations, the dominant routing form in this workspace.

    A backticked path may be written relative to the citing document
    (`../knowledge/...`) or relative to the workspace root
    (`knowledge/system-atlas/...`). Either resolution counts as valid; only a
    citation that resolves to nothing is a dead route.
    """
    findings: list[Finding] = []
    prose = CODE_FENCE_RE.sub("", text)
    seen: set[str] = set()
    for match in BACKTICK_PATH_RE.finditer(prose):
        raw = match.group(1).strip()
        if raw in seen:
            continue
        seen.add(raw)
        if any(marker in raw for marker in PLACEHOLDER_MARKERS):
            continue
        # A bare filename (`SKILL.md`, `world-state.yaml`) is a name mentioned in
        # prose, not a route. Only citations carrying a path are routing claims.
        if "/" not in raw:
            continue
        relative = _resolve_relative(rel_path, raw)
        # Must strip the "./" prefix, not the character set: str.lstrip("./")
        # would turn ".cursor/rules/x.mdc" into "cursor/rules/x.mdc".
        root_relative = raw[2:] if raw.startswith("./") else raw
        if relative in known or root_relative in known:
            findings.append(Finding(rel_path, raw, "local"))
        elif (root / relative).is_file() or (root / root_relative).is_file():
            findings.append(Finding(rel_path, raw, "local_abs"))
        else:
            findings.append(Finding(rel_path, raw, classify_missing(raw)))
    return findings


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
        resolved = _resolve_relative(rel_path, raw)
        if resolved in known:
            findings.append(Finding(rel_path, raw, "local"))
        elif (root / resolved).is_file():
            findings.append(Finding(rel_path, raw, "local_abs"))
        else:
            findings.append(Finding(rel_path, raw, classify_missing(raw)))
    findings.extend(scan_backtick_paths(root, rel_path, text, known))
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
