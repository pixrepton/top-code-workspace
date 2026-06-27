"""Save audit evidence checkpoint."""
import json, os

evidence = {
    "timestamp": "2026-06-27T12:00:00Z",
    "git_head": {
        "commit": "0cbef0778163d172fad869ed207ed79cb5fef063",
        "date": "2026-06-18 05:37:37 +0200",
        "message": "chore(harness): W3 RAG health push script and agent-owned closure rules"
    },
    "docker_image": {
        "name": "gmail-agent-runtime:local",
        "digest": "sha256:c916b2ebc292103b3cae9948a45148f294839255ade2c0e037a63c218b950dbb",
        "created": "2026-06-24T00:26:14.775310504Z",
        "architecture": "linux/amd64"
    },
    "container_created": "2026-06-24T00:28:53.402045651Z",
    "runtime_drift": {
        "files_in_repo_not_in_container": [
            {"name": "signal_registry.py", "size": 1417, "session": "0992e694"},
            {"name": "idempotency.py", "size": 3681, "session": "0992e694"},
            {"name": "ENTITY_REGISTRY_SCHEMA.sql", "size": 824},
            {"name": "migrations/003_idempotency_log.sql", "size": 541, "session": "0992e694"},
            {"name": "migrations/004_snapshot_storage_optimization.sql", "size": 974, "session": "0992e694"}
        ]
    },
    "health_type_error": {
        "file": "event_spine/health_monitor.py",
        "line": 212,
        "error": "TypeError: '>' not supported between instances of 'datetime.datetime' and 'str'",
        "root_cause": "comp['last_heartbeat'] stored as string via .isoformat() on line 213, compared as datetime on line 212"
    },
    "chroma_state": {
        "collection": "hvac_knowledge",
        "chunks": 115,
        "dimension": 768,
        "documents": 28
    },
    "filesKonrad_status": "OUT_OF_SCOPE",
    "filesKonrad_count": 8,
    "feature_flags": {
        "AGENT_RUNTIME_ENABLED": "1",
        "AGENT_RUNTIME_MODE": "prep",
        "AGENT_CONSTITUTION_RAG_ENABLED": "1",
        "SIGNAL_RUNTIME_MODE": "active",
        "EVENT_SPINE_PROCESSOR_ENABLED": "0",
        "MAILBOX_MEMORY_VECTOR_ENABLED": "1",
        "DECISION_PIPELINE_ENABLED": "1",
        "AGENT_MAX_ROUNDS": "12"
    },
    "known_defects": [
        "signal_registry.py missing from Docker image",
        "idempotency.py missing from Docker image",
        "ENTITY_REGISTRY_SCHEMA.sql missing from Docker image",
        "health_monitor.py TypeError on line 212",
        "RAG retrieval returns 0 sources for domain queries"
    ]
}

os.makedirs("scripts/proof", exist_ok=True)
with open("scripts/proof/audit-evidence-2026-06-27.json", "w", encoding="utf-8") as f:
    json.dump(evidence, f, indent=2, ensure_ascii=False)
print("Written: scripts/proof/audit-evidence-2026-06-27.json")
