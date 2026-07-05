#!/usr/bin/env python3
"""E2E Full Flow Proof Gate — weryfikuje cały system.

Uruchamia scripts/e2e_full_flow.py i raportuje wynik.
Ten skrypt jest formalnym proof gatem: wypisuje E2E_FULL_FLOW_PROOF_OK
na stdout przy sukcesie, exit code 0.

Uruchomienie:
    python scripts/e2e_full_flow_proof.py [--no-docker-check]

Wymaga:
    - Uruchomionego stacka Docker (gmail-agent, RAG, Daszek, kalk-top)
    - MAILBOX_MEMORY_DATABASE_URL w środowisku
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
E2E_SCRIPT = WORKSPACE / "scripts" / "e2e_full_flow.py"

PROOF_MARKER = "E2E_FULL_FLOW_PROOF_OK"

# Szybkie testy kondycji endpointów przed pełnym E2E
HEALTH_CHECKS = [
    ("gmail-agent", "http://localhost:8766/system/health/status"),
    ("RAG", "http://localhost:8000/health"),
]


def check_docker_stack() -> bool:
    """Sprawdza czy niezbędne kontenery są uruchomione."""
    import json

    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(f"  DOCKER: docker ps failed — {result.stderr.strip()}")
            return False
        names = result.stdout.strip().splitlines()
        required = ["gmail-agent", "rag", "postgres"]
        missing = [r for r in required if not any(r in n for n in names)]
        if missing:
            print(f"  DOCKER: brakujące kontenery: {missing}")
            return False
        print(f"  DOCKER: wszystkie kontenery uruchomione ({len(names)} znalezionych)")
        return True
    except FileNotFoundError:
        print("  DOCKER: docker nie jest zainstalowany lub nie w PATH")
        return False
    except subprocess.TimeoutExpired:
        print("  DOCKER: timeout na docker ps")
        return False


def main() -> int:
    print(f"=== E2E Full Flow Proof Gate ===")
    print()

    # Krok 1: Sprawdź Docker
    print("[1/3] Sprawdzam stack Docker...")
    if not check_docker_stack():
        print("  FAILED — stack Docker nie jest gotowy.")
        print("  Uruchom: docker compose -f docker-compose.daszek-local.yml up -d")
        return 1

    # Krok 2: Sprawdź czy skrypt E2E istnieje
    print(f"\n[2/3] Szukam {E2E_SCRIPT}...")
    if not E2E_SCRIPT.is_file():
        print(f"  NOT FOUND: {E2E_SCRIPT}")
        print("  Ten proof gate wymaga scripts/e2e_full_flow.py")
        return 1
    print(f"  OK: znaleziono {E2E_SCRIPT}")

    # Krok 3: Uruchom E2E
    print(f"\n[3/3] Uruchamiam E2E full flow...")
    print(f"  (to może potrwać do 120 sekund)")
    print()

    result = subprocess.run(
        [sys.executable, str(E2E_SCRIPT)],
        cwd=str(WORKSPACE),
        capture_output=True, text=True, timeout=180,
    )

    # Wypisz output
    if result.stdout:
        print("  stdout:")
        for line in result.stdout.strip().splitlines():
            print(f"    {line}")
    if result.stderr:
        print("  stderr:")
        for line in result.stderr.strip().splitlines():
            print(f"    {line}")

    # Wynik
    if result.returncode == 0:
        print(f"\n  {PROOF_MARKER}")
        print(f"  E2E full flow PASSED (exit code 0)")
        return 0

    print(f"\n  E2E FAILED (exit code {result.returncode})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
