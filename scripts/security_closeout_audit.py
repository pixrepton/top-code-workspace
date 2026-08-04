#!/usr/bin/env python3
"""Phase 0 security closeout audit for the workspace shell.

Scans git-tracked files for secret-like content and forbidden env paths.
Does not mutate git state. Intended for LOCAL_ONLY closeout before fresh-38 runs.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]

if str(WORKSPACE / "scripts") not in sys.path:
    sys.path.insert(0, str(WORKSPACE / "scripts"))

from ai_os_task_constants import SECRET_CONTENT_PATTERNS, SECRET_PATH_PATTERNS  # noqa: E402

STILL_EXPOSED_PATTERN = re.compile(r"STILL\s+EXPOSED", re.I)

ALLOWLIST_PATH_FRAGMENTS = (
    ".env.example",
    ".env.sample",
    ".env.template",
    ".example",
    "security_closeout_audit.py",
    "test_ai_os_task.py",
    "test_ai_os_git_control.py",
    "ai_os_task_constants.py",
    "scripts/dev-tooling/",
)


def _git_tracked_files(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [item.decode("utf-8") for item in proc.stdout.split(b"\0") if item]


def _is_allowlisted(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").lower()
    return any(fragment in normalized for fragment in ALLOWLIST_PATH_FRAGMENTS)


def _scan_path_issues(rel_path: str) -> list[str]:
    if _is_allowlisted(rel_path):
        return []
    issues: list[str] = []
    for pattern in SECRET_PATH_PATTERNS:
        if pattern.search(rel_path):
            issues.append(f"sensitive tracked path: {rel_path}")
    return issues


def _scan_content_issues(rel_path: str, content: bytes) -> list[str]:
    if _is_allowlisted(rel_path):
        return []
    issues: list[str] = []
    for label, pattern in SECRET_CONTENT_PATTERNS:
        if pattern.search(content):
            issues.append(f"{rel_path}: detected {label}")
    if STILL_EXPOSED_PATTERN.search(content.decode("utf-8", errors="ignore")):
        issues.append(f"{rel_path}: contains STILL EXPOSED marker")
    return issues


def audit_repository(repo_root: Path) -> dict:
    repo_name = repo_root.name
    path_issues: list[str] = []
    content_issues: list[str] = []
    scanned = 0

    for rel in _git_tracked_files(repo_root):
        scanned += 1
        path_issues.extend(_scan_path_issues(rel))
        file_path = repo_root / rel
        if not file_path.is_file():
            continue
        try:
            raw = file_path.read_bytes()
        except OSError as exc:
            content_issues.append(f"{rel}: unreadable ({exc})")
            continue
        if len(raw) > 2_000_000:
            continue
        content_issues.extend(_scan_content_issues(rel, raw))

    issues = sorted(set(path_issues + content_issues))
    return {
        "repo": repo_name,
        "root": str(repo_root),
        "tracked_files_scanned": scanned,
        "issues": issues,
        "verdict": "PASS" if not issues else "FAIL",
    }


def discover_nested_repos(workspace: Path) -> list[Path]:
    repos = [workspace]
    for child in sorted(workspace.iterdir()):
        if not child.is_dir():
            continue
        if (child / ".git").is_dir():
            repos.append(child)
    return repos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Security closeout audit (tracked files only).")
    parser.add_argument("--workspace", default=str(WORKSPACE))
    parser.add_argument("--repo", action="append", help="Limit to one nested repo name (repeatable).")
    parser.add_argument("--json-out", default="", help="Optional JSON report path.")
    args = parser.parse_args(argv)

    workspace = Path(args.workspace).resolve()
    repos = discover_nested_repos(workspace)
    if args.repo:
        allowed = set(args.repo)
        repos = [repo for repo in repos if repo.name in allowed or repo == workspace and "workspace" in allowed]

    reports = [audit_repository(repo) for repo in repos]
    payload = {
        "workspace": str(workspace),
        "verdict": "PASS" if all(item["verdict"] == "PASS" for item in reports) else "FAIL",
        "repositories": reports,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
