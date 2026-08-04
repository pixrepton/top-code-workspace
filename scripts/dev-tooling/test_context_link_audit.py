"""Tests for workspace context_link_audit."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
AUDIT = WORKSPACE / "scripts" / "context_link_audit.py"


def test_context_link_audit_workspace_scope():
    proc = subprocess.run(
        [sys.executable, str(AUDIT), "--scope", "workspace"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_context_link_audit_gmail_agent_scope():
    proc = subprocess.run(
        [sys.executable, str(AUDIT), "--scope", "gmail-agent"],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
