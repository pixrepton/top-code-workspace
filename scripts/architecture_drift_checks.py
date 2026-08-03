"""Lint rules for the generated runtime artifacts in knowledge/runtime."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


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


def _check_exists(name: str) -> list[str]:
    if not (RUNTIME_DIR / name).exists():
        return [f"BRAK: {name} nie istnieje"]
    return []


def runtime_artifact_changes(changed_files: list[str]) -> list[str]:
    return sorted(
        path
        for path in changed_files
        if Path(path).name in RUNTIME_ARTIFACT_NAMES
        or path.replace("\\", "/").startswith("knowledge/runtime/")
    )


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
    for event in ("rag.query", "agent.run", "agent.tool"):
        if event not in artifact:
            findings.append(f"DRIFT: EVENT_SPINE_GRAPH.md brak eventow {event}.*")
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


CHECKS: tuple[tuple[str, Callable[[], list[str]]], ...] = (
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
)


def run_checks() -> tuple[int, list[tuple[str, list[str]]]]:
    results: list[tuple[str, list[str]]] = []
    total = 0
    for name, check in CHECKS:
        findings = check()
        total += len(findings)
        results.append((name, findings))
    return total, results
