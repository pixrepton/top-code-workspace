#!/usr/bin/env python3
"""Run CBM diagnose for one project with immediate stdout."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "dev-tooling"))

from cbm_mcp_diagnose import list_index_files, summarize_report, timed_session  # noqa: E402


def main() -> int:
    project = sys.argv[1] if len(sys.argv) > 1 else "gmail-audit"
    label = sys.argv[2] if len(sys.argv) > 2 else project
    runs = []
    for run_index in (1, 2):
        report = timed_session(project, label, run_index)
        runs.append(summarize_report(report))
        print(json.dumps(runs[-1], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
