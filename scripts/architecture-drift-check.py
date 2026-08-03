"""
Runtime artifact lint — sprawdza spójność wygenerowanych artefaktów w knowledge/runtime.

To nie jest pełny architecture drift check względem kodu/MCP/runtime — tylko lint
markdownowych artefaktów (obecność sekcji, słowa kluczowe, oczekiwane oznaczenia).

Usage:
    python scripts/architecture-drift-check.py

Zasada:
    Jesli artefakt i graf MCP sa sprzeczne: artefakt wymaga aktualizacji.
    Jesli artefakt i runtime sa sprzeczne: artefakt wymaga aktualizacji.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from architecture_drift_checks import (  # noqa: E402
    REPO_ROOT,
    run_checks,
    runtime_artifact_changes,
)

MAX_LISTED_FILES = 10


def _git_diff() -> tuple[list[str], str | None]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=30,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "git diff failed").strip()
            return [], detail
        return [f for f in result.stdout.split("\n") if f.strip()], None
    except Exception as exc:
        return [], str(exc)


def print_banner() -> None:
    timestamp = datetime.now().isoformat()[:19]
    print("=" * 60)
    print(f"RUNTIME ARTIFACT LINT — {timestamp}")
    print("=" * 60)


def _print_changed_files(changed_files: list[str]) -> None:
    print(f"\nZmienione pliki od ostatniego commita: {len(changed_files)}")
    for path in changed_files[:MAX_LISTED_FILES]:
        print(f"  {path}")
    if len(changed_files) > MAX_LISTED_FILES:
        print(f"  ... i {len(changed_files) - MAX_LISTED_FILES} wiecej")


def _print_runtime_changes(runtime_changes: list[str]) -> None:
    if not runtime_changes:
        return
    print("\nZmienione artefakty runtime (niezacommitowane):")
    for path in runtime_changes:
        print(f"  {path}")
    print("  Uwaga: po zmianach kodu wygeneruj artefakty przez generate-runtime-artifacts.js")


def print_worktree_section(changed_files: list[str], git_error: str | None) -> list[str]:
    """Print the worktree state and return findings that count towards the total."""
    if git_error:
        print(f"\nUWAGA: git diff nieudany: {git_error}")
        return [f"GIT: nie udalo sie odczytac diff ({git_error})"]
    if not changed_files:
        print("\nBrak zmian od ostatniego commita.")
        return []
    _print_changed_files(changed_files)
    _print_runtime_changes(runtime_artifact_changes(changed_files))
    return []


def print_findings(extra_findings: list[str], results: list[tuple[str, list[str]]]) -> None:
    for finding in extra_findings:
        print(f"  [GIT/WORKTREE] {finding}")
    for name, findings in results:
        for finding in findings:
            print(f"  [{name}] {finding}")


def print_summary(total_drifts: int, category_count: int) -> int:
    print("\n=== PODSUMOWANIE ===")
    print(f"  Lacznie ustalen lintu: {total_drifts}")
    print(f"  Przeskanowano: {category_count} kategorii")
    if total_drifts > 0:
        print("  Rekomendacja: zaktualizuj artefakty przez: node .cursor/hooks/generate-runtime-artifacts.js")
        return 1
    print("  Stan: OK")
    return 0


def main() -> int:
    changed_files, git_error = _git_diff()

    print_banner()
    extra_findings = print_worktree_section(changed_files, git_error)

    print("\n--- Artifact Lint Checks ---")
    total_drifts, results = run_checks()
    total_drifts += len(extra_findings)

    print_findings(extra_findings, results)
    if total_drifts == 0:
        print("  Wszystkie artefakty przeszly lint. Brak problemow.")

    return print_summary(total_drifts, len(results))


if __name__ == "__main__":
    sys.exit(main())
