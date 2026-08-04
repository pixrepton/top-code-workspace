"""Tests for manifest-driven workspace agent_harness_audit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
AUDIT = WORKSPACE / "scripts" / "agent_harness_audit.py"


def test_agent_harness_audit_passes():
    proc = subprocess.run(
        [sys.executable, str(AUDIT)],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
