# AGENTS.md — scripts

Status: **Typ B — root-owned workspace harness** (not an independent Git repository).

## Role

Cross-repo tooling: local stack sync/preflight/verify, session hooks, **`ai_os_task.py`** (checkpoint, ownership, gate, scoped commit), Codex/Claude hook adapters, **E2E proof scripts**.

See this directory’s README for the script catalog.

Notable E2E harnesses:

- `e2e_async_agent_chat.py` — Gate B async Agent Chat (Phase 6.2); track when committing `E2E-ASYNC-TRACK-01`
- `e2e_full_flow.py` — broader stack flow; known PARTIAL vs spine 6.3 (`E2E-FULLFLOW-*`)
- `preflight-local-stack.ps1` / `-FullStack` — Gate B preflight

## Owns / Must not

| Owns                                             | Must not                       |
| ------------------------------------------------ | ------------------------------ |
| Gate orchestration; task engine; path resolution | Case / RAG / HVAC domain logic |
| Scoped commit / ownership guards                 | Secrets committed into Git     |

## Read first

1. Root `../AGENTS.md` — Task and Git Control
2. `../knowledge/system-atlas/tooling/GIT_AND_CHANGE_CONTROL.md`
3. `../knowledge/system-atlas/tooling/CODEX_EXECUTION_MAP.md` when routing a task
4. Local README in this folder

## Rules

- Commit scope: **`workspace:scripts/...`**
- Changes to `ai_os_task*` are critical for agent hygiene — run harness audits after edits
- Default agent Git workflow is the task engine, not raw `git commit`
- Secrets via existing loaders/env — never commit tokens

## Gate

```powershell
python scripts/agent_harness_audit.py
python scripts/agent_map_audit.py
python -m py_compile scripts/ai_os_task.py
```

Gate B / `preflight-local-stack.ps1` only when runtime stack scripts or compose wiring changed.

## Anti-goals

- Copying gate procedures into `knowledge/` as a parallel system
- Domain business logic inside harness scripts
