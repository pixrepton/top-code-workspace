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
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from collections.abc import Callable


REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = REPO_ROOT / "knowledge" / "runtime"
RUNTIME_ARTIFACT_NAMES = {
    "API_INGRESS.md",
    "DATABASE_OWNERSHIP.md",
    "FEATURE_FLAGS.md",
    "EVENT_SPINE_GRAPH.md",
    "WRITE_EXECUTOR_GRAPH.md",
    "AGENT_CAPABILITY_MATRIX.md",
    "BOUNDARY_MAP.md",
    "SOT_MATRIX.md",
    "OWNERSHIP_GRAPH.md",
    "REPOSITORY_MAP.md",
}
GMAIL_AGENT_DIR = REPO_ROOT / "gmail-agent"
RAG_DIR = REPO_ROOT / "rag-chat-asystent"


def _read_artifact(filename: str) -> str:
    path = RUNTIME_DIR / filename
    if not path.exists():
        return ""
    return path.read_text("utf-8", errors="replace")


def _read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text("utf-8", errors="replace")


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


def _runtime_artifact_changes(changed_files: list[str]) -> list[str]:
    return sorted(
        path
        for path in changed_files
        if Path(path).name in RUNTIME_ARTIFACT_NAMES
        or path.replace("\\", "/").startswith("knowledge/runtime/")
    )


def _check_exists(name: str) -> list[str]:
    if not (RUNTIME_DIR / name).exists():
        return [f"BRAK: {name} nie istnieje"]
    return []


def check_api_ingress() -> list[str]:
    findings = _check_exists("API_INGRESS.md")
    if findings:
        return findings
    artifact = _read_artifact("API_INGRESS.md")
    if "ORPHANED" not in artifact:
        findings.append("OSTRZEZENIE: API_INGRESS.md nie zawiera oznaczen ORPHANED")
    if "USUNIETY" not in artifact:
        findings.append("OSTRZEZENIE: API_INGRESS.md nie odnotowuje usunietych endpointow")
    return findings


def check_database_ownership() -> list[str]:
    findings = _check_exists("DATABASE_OWNERSHIP.md")
    if findings:
        return findings
    artifact = _read_artifact("DATABASE_OWNERSHIP.md")
    if "Chroma" in artifact or "chroma" in artifact:
        findings.append("DRIFT: DATABASE_OWNERSHIP.md wciaz wspomina ChromaDB (migracja do pgvector)")
    if "pgvector" not in artifact:
        findings.append("DRIFT: DATABASE_OWNERSHIP.md nie wspomina pgvector")
    if "Storage Contracts" not in artifact:
        findings.append("DRIFT: DATABASE_OWNERSHIP.md brak sekcji Storage Contracts")
    return findings


def check_feature_flags() -> list[str]:
    findings = _check_exists("FEATURE_FLAGS.md")
    if findings:
        return findings
    artifact = _read_artifact("FEATURE_FLAGS.md")
    if "EVENT_SPINE_PROCESSOR_MODE" not in artifact:
        findings.append("DRIFT: FEATURE_FLAGS.md brak flagi EVENT_SPINE_PROCESSOR_MODE")
    if "USE_PGVECTOR" not in artifact:
        findings.append("DRIFT: FEATURE_FLAGS.md brak flagi USE_PGVECTOR")
    if "Feature Flag Impact Graph" not in artifact:
        findings.append("DRIFT: FEATURE_FLAGS.md brak sekcji Feature Flag Impact Graph")
    return findings


def check_event_spine_graph() -> list[str]:
    findings = _check_exists("EVENT_SPINE_GRAPH.md")
    if findings:
        return findings
    artifact = _read_artifact("EVENT_SPINE_GRAPH.md")
    if "MODE=active" not in artifact:
        findings.append("DRIFT: EVENT_SPINE_GRAPH.md nie odzwierciedla trybu active")
    if "rag.query" not in artifact:
        findings.append("DRIFT: EVENT_SPINE_GRAPH.md brak eventow rag.query.*")
    if "agent.run" not in artifact:
        findings.append("DRIFT: EVENT_SPINE_GRAPH.md brak eventow agent.run.*")
    if "agent.tool" not in artifact:
        findings.append("DRIFT: EVENT_SPINE_GRAPH.md brak eventow agent.tool.*")
    if "Event Ownership" not in artifact:
        findings.append("DRIFT: EVENT_SPINE_GRAPH.md brak sekcji Event Ownership")
    return findings


def check_write_executors() -> list[str]:
    findings = _check_exists("WRITE_EXECUTOR_GRAPH.md")
    if findings:
        return findings
    artifact = _read_artifact("WRITE_EXECUTOR_GRAPH.md")
    # Check if artifact mentions the standard operations count
    if "17 operacji" not in artifact and "17 write" not in artifact.lower():
        findings.append("DRIFT: WRITE_EXECUTOR_GRAPH.md moze byc nieaktualny")
    return findings


def check_agent_capability() -> list[str]:
    findings = _check_exists("AGENT_CAPABILITY_MATRIX.md")
    if findings:
        return findings
    artifact = _read_artifact("AGENT_CAPABILITY_MATRIX.md")
    if "Capability Matrix" not in artifact:
        findings.append("DRIFT: AGENT_CAPABILITY_MATRIX.md — brak macierzy")
    if "Write Executors" not in artifact:
        findings.append("DRIFT: AGENT_CAPABILITY_MATRIX.md — brak sekcji Write Executors")
    if "Konstytucyjne allowlisty" not in artifact:
        findings.append("DRIFT: AGENT_CAPABILITY_MATRIX.md — brak allowlist konstytucyjnych")
    return findings


def check_bounded_contexts() -> list[str]:
    findings = _check_exists("BOUNDARY_MAP.md")
    if findings:
        return findings
    artifact = _read_artifact("BOUNDARY_MAP.md")
    if "Context Responsibilities" not in artifact:
        findings.append("DRIFT: BOUNDARY_MAP.md brak sekcji Context Responsibilities")
    return findings


def check_sot_matrix() -> list[str]:
    findings = _check_exists("SOT_MATRIX.md")
    if findings:
        return findings
    artifact = _read_artifact("SOT_MATRIX.md")
    if "macierz" not in artifact.lower() and "Macierz" not in artifact:
        findings.append("DRIFT: SOT_MATRIX.md — brak macierzy SoT")
    return findings


def check_ownership_graph() -> list[str]:
    findings = _check_exists("OWNERSHIP_GRAPH.md")
    if findings:
        return findings
    artifact = _read_artifact("OWNERSHIP_GRAPH.md")
    if "Context Responsibilities" not in artifact:
        findings.append("DRIFT: OWNERSHIP_GRAPH.md brak sekcji Context Responsibilities")
    return findings


def check_repository_map() -> list[str]:
    findings = _check_exists("REPOSITORY_MAP.md")
    if findings:
        return findings
    return []


def run_checks() -> tuple[int, list[tuple[str, list[str]]]]:
    checks: list[tuple[str, Callable[[], list[str]]]] = [
        ("API_INGRESS", check_api_ingress),
        ("DATABASE_OWNERSHIP", check_database_ownership),
        ("FEATURE_FLAGS", check_feature_flags),
        ("EVENT_SPINE", check_event_spine_graph),
        ("WRITE_EXECUTORS", check_write_executors),
        ("AGENT_CAPABILITY", check_agent_capability),
        ("BOUNDARY_CONTEXTS", check_bounded_contexts),
        ("SOT_MATRIX", check_sot_matrix),
        ("OWNERSHIP_GRAPH", check_ownership_graph),
        ("REPOSITORY_MAP", check_repository_map),
    ]

    results: list[tuple[str, list[str]]] = []
    total = 0
    for name, fn in checks:
        findings = fn()
        if findings:
            total += len(findings)
        results.append((name, findings))
    return total, results


def main() -> int:
    changed_files, git_error = _git_diff()
    runtime_changes = _runtime_artifact_changes(changed_files)
    timestamp = datetime.now().isoformat()[:19]
    extra_findings: list[str] = []

    print("=" * 60)
    print(f"RUNTIME ARTIFACT LINT — {timestamp}")
    print("=" * 60)

    if git_error:
        extra_findings.append(f"GIT: nie udalo sie odczytac diff ({git_error})")
        print(f"\nUWAGA: git diff nieudany: {git_error}")
    elif changed_files:
        print(f"\nZmienione pliki od ostatniego commita: {len(changed_files)}")
        for f in changed_files[:10]:
            print(f"  {f}")
        if len(changed_files) > 10:
            print(f"  ... i {len(changed_files) - 10} wiecej")
        if runtime_changes:
            print("\nZmienione artefakty runtime (niezacommitowane):")
            for path in runtime_changes:
                print(f"  {path}")
            print("  Uwaga: po zmianach kodu wygeneruj artefakty przez generate-runtime-artifacts.js")
    else:
        print("\nBrak zmian od ostatniego commita.")

    print("\n--- Artifact Lint Checks ---")
    total_drifts, results = run_checks()
    total_drifts += len(extra_findings)

    for finding in extra_findings:
        print(f"  [GIT/WORKTREE] {finding}")

    for name, findings in results:
        if findings:
            for f in findings:
                print(f"  [{name}] {f}")

    if total_drifts == 0:
        print("  Wszystkie artefakty przeszly lint. Brak problemow.")

    print("\n=== PODSUMOWANIE ===")
    print(f"  Lacznie ustalen lintu: {total_drifts}")
    print(f"  Przeskanowano: {len(results)} kategorii")
    if total_drifts > 0:
        print("  Rekomendacja: zaktualizuj artefakty przez: node .cursor/hooks/generate-runtime-artifacts.js")
        return 1

    print("  Stan: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
