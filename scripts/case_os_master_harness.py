"""Case OS Master Harness — run all *_proof.py scripts and report failures."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent

# Scan directories likely to contain proof scripts
PROOF_DIRS = [
    WORKSPACE / "gmail-agent" / "scripts",
    WORKSPACE / "gmail-agent" / "tools" / "gmail_audit" / "scripts",
    WORKSPACE / "rag-chat-asystent" / "backend" / "scripts",
    WORKSPACE / "rag-chat-asystent" / "scripts",
]

proofs: list[Path] = []
for d in PROOF_DIRS:
    if d.is_dir():
        for f in sorted(d.glob("*_proof.py")):
            proofs.append(f)

if not proofs:
    print("MASTER_HARNESS_NO_PROOFS: no *_proof.py found in any proof dir")
    sys.exit(1)

print(f"MASTER_HARNESS_START: {len(proofs)} proofs discovered")
proofs.sort()

failures: list[Path] = []
for p in proofs:
    rel = p.relative_to(WORKSPACE) if p.is_relative_to(WORKSPACE) else p
    print(f"  RUNNING: {rel}")
    cwd = p.parent
    result = subprocess.run(
        [sys.executable, str(p)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        print(f"  FAILED ({result.returncode}): {rel}")
        if result.stdout:
            print("    stdout (last 20 lines):\n" + "\n".join(result.stdout.strip().splitlines()[-20:]))
        if result.stderr:
            print("    stderr (last 20 lines):\n" + "\n".join(result.stderr.strip().splitlines()[-20:]))
        failures.append(p)
    else:
        print(f"  OK: {rel}")

if failures:
    print(f"MASTER_HARNESS_FAILED: {len(failures)}/{len(proofs)} failures:")
    for f in failures:
        rel = f.relative_to(WORKSPACE) if f.is_relative_to(WORKSPACE) else f
        print(f"  - {rel}")
    sys.exit(1)

print(f"MASTER_HARNESS_OK: {len(proofs)}/{len(proofs)}")
