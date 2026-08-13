# Workspace harness (`TOP_CODE_ROOT/scripts`)

Cross-repo PowerShell harness for local Docker stack. Versioned in the workspace root meta-repo (not inside `gmail-agent` / `rag-chat-asystent`).

## Scripts

| File                               | Purpose                                                                                                                          |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `resolve-paths.ps1`                | Sets `TOP_CODE_ROOT` and per-repo env paths (sourced by others)                                                                  |
| `sync-local-stack-env.ps1`         | Sync `.env.local-vps`, audit `.env`, Daszek `.env.daszek-local`, RAG wire                                                        |
| `preflight-local-stack.ps1`        | Health: Node B, RAG; `-FullStack` adds Daszek, kalk-top, PG                                                                      |
| `rag12-gate-b-rag-stack-smoke.ps1` | **RAG-12** bounded Gate B: Node B + RAG `/health` + GraphStore PG + `/rag_v2/status` (RAG-14); MinIO/Qdrant/Temporal honest SKIP |
| `verify-local-gates.ps1`           | Preflight + optional pytest smoke (Gate A+B)                                                                                     |
| `push-rag-system-health.ps1`       | W3: RAG health snapshot → Daszek + `rag.kb_health.snapshot` (cron/harness)                                                       |
| `preflight-workspace.ps1`          | Workspace-level checks                                                                                                           |
| `session-closeout.ps1`             | Session end checklist helper                                                                                                     |
| `compile-world-state.py`           | World-state compile helper                                                                                                       |
| `load-secrets.ps1`                 | Inject Bitwarden vault secrets into .env (Phase 1: cookies). Requires `BWS_ACCESS_TOKEN`.                                        |
| `ai_os_task.py`                    | Shared checkpoint, ownership, gate, task-branch and scoped local commit engine for Codex and Claude Code.                        |
| `ai_os_codex_hook.py`              | Codex lifecycle adapter for checkpoint refresh/resume.                                                                           |
| `ai_os_claude_hook.py`             | Claude Code write/Git guard and completion adapter.                                                                              |

## Agent task and Git workflow

All agent write tasks use the same engine:

```powershell
# Initialize exact repo:path scope and local-only publication
python scripts/ai_os_task.py task-start `
  --task-id RP-XX `
  --title "Bounded repair" `
  --class MEDIUM `
  --repo gmail-agent `
  --scope gmail-agent:path/to/file.py `
  --publication-mode LOCAL_ONLY

# Leave the default/protected branch before the first write
python scripts/ai_os_task.py task-branch `
  --repo gmail-agent `
  --name repair/RP-XX-bounded-repair

# Run the task-specific proof
python scripts/ai_os_task.py task-gate --gate-id focused --repo gmail-agent --scope path/to/file.py -- python -m pytest path/to/test.py -q

# Plan and create a scoped local commit without absorbing foreign staged state
python scripts/ai_os_task.py task-commit-plan --repo gmail-agent --json
python scripts/ai_os_task.py task-commit --repo gmail-agent --message "fix(scope): describe the completed result"

# Rerun final gates after the commit, then close
python scripts/ai_os_task.py task-checkpoint --status READY_TO_CLOSE --next=
python scripts/ai_os_task.py task-close --validate-only
python scripts/ai_os_task.py task-close --summary "Closed with final committed proof."
```

Proof phases should make escalation visible.

Prefer phase/gate names that distinguish:

- FAST
- FOCUSED
- LIVE_DISCRIMINATING
- BOUNDED_QUALIFICATION
- FULL_QUALIFICATION

For `task-checkpoint --phase` or `task-gate --gate-id`, prefer names that show the current proof tier, for example `FAST_ROOT_CAUSE`, `FOCUSED_REGRESSION`, `LIVE_CTX04`, `BOUNDED_FOUR_CASE`, `FULL_FRESH38_QUALIFICATION`. Do not force those exact names where they would be artificial.

Do not escalate to a more expensive proof tier until the previous tier has answered its intended question, unless the claim is impossible to evaluate at that tier.

Canonical proof-economy invariant: root `AGENTS.md`. Execution ladder: `.agents/skills/cursor-codex-harness/SKILL.md`.

Do not use raw `git add` or raw `git commit` for agent work. The canonical
policy is `knowledge/system-atlas/tooling/GIT_AND_CHANGE_CONTROL.md`.

## MAX-STACK master proof (gmail-agent)

```powershell
$env:GRAPHSTORE_DSN="postgresql://postgres:postgres@127.0.0.1:54130/graphstore"
cd gmail-agent/tools/gmail_audit
./scripts/verify-max-stack.ps1   # MAX_STACK_10_PROOF_OK
```

Nightly CI: `.github/workflows/max-stack-nightly.yml` · Roadmap: `knowledge/docs/max-stack-roadmap-2026-06.md`

## Workflow startowy (nowy komputer / fresh session)

```powershell
# 1. Załaduj sekrety z Bitwarden (jeśli BWS_ACCESS_TOKEN ustawiony)
powershell -File scripts/load-secrets.ps1

# 2. Sync portów i tokenów
powershell -File scripts/sync-local-stack-env.ps1

# 3. Sprawdź stack
powershell -File scripts/preflight-local-stack.ps1 -FullStack

# 3b. RAG-12 bounded Gate B (≠ full ecosystem): Node B + RAG + GraphStore + adapter status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag12-gate-b-rag-stack-smoke.ps1
```

`rag12-gate-b-rag-stack-smoke.ps1` writes a JSON matrix under `.artifacts/rag12-gate-b-smoke-*.json`. Optional live listeners (MinIO `:9000`, Qdrant `:6333`, Temporal `:7233`) report **SKIP** when down — do not invent those stacks. Use `-RequireLiveAdapters` only when you intentionally require them. If `/rag_v2/status` is 404 (stale `rag-backend` image vs RAG-14), the script falls back to host `collect_rag_v2_adapter_status` and returns **PARTIAL**.

## Daszek System proofs (Gate B)

Run from `gmail-agent/` after `preflight-local-stack.ps1 -FullStack` and Daszek recreate if UI assets changed.

Po edycji diagramów lub opisów UX — najpierw sync z jednego pliku źródłowego:

```powershell
python daszek/scripts/sync_system_diagrams_manifest.py
python daszek/scripts/sync_system_diagrams_manifest.py --check   # DASZEK_SYSTEM_DIAGRAMS_MANIFEST_SYNC_OK
```

Źródło kanoniczne: `knowledge/docs/daszek-system-diagrams.md`

```powershell
python tools/gmail_audit/scripts/daszek_system_observability_proof.py   # DASZEK_SYSTEM_OBSERVABILITY_PROOF_OK
python tools/gmail_audit/scripts/daszek_system_diagrams_proof.py        # DASZEK_SYSTEM_DIAGRAMS_PROOF_OK
```

Recreate Daszek WP after `index.php` / plugin mount issues or po sync `system-diagrams-manifest.js`:

```powershell
docker compose -f docker-compose.daszek-local.yml up -d --force-recreate wordpress
```

Proof pack: `knowledge/artifacts/proof-packs/daszek-system-ui-diagrams-2026-06-18.md`

## Operator workflow

```text
zmiana portów/kluczy → sync-local-stack-env.ps1 → recreate kontenerów jeśli tokeny
start sesji / proof     → preflight-local-stack.ps1 (-FullStack przed Gmail+Daszek)
większy gate            → verify-local-gates.ps1
```

After token sync (`DASZEK_NODE_B_SERVICE_TOKEN`, `NODE_B_REGISTRY_TOKEN`): recreate `gmail-agent-worker` and Daszek WP.

After Daszek UI changes (`app.js`, `index.php`, `style.css`): `docker compose -f docker-compose.daszek-local.yml up -d --force-recreate wordpress`

## References

- `knowledge/CONTROL_PLANE.md` — `proven_local` gate
- `knowledge/world-state.yaml` — endpoint ports
- `.cursor/rules/35-local-stack-harness-workflow.mdc` — agent workflow
