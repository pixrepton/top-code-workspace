# Workspace harness (`TOP_CODE_ROOT/scripts`)

Cross-repo PowerShell harness for local Docker stack. Versioned in the workspace root meta-repo (not inside `gmail-agent` / `rag-chat-asystent`).

## Scripts

| File                         | Purpose                                                                                   |
| ---------------------------- | ----------------------------------------------------------------------------------------- |
| `resolve-paths.ps1`          | Sets `TOP_CODE_ROOT` and per-repo env paths (sourced by others)                           |
| `sync-local-stack-env.ps1`   | Sync `.env.local-vps`, audit `.env`, Daszek `.env.daszek-local`, RAG wire                 |
| `preflight-local-stack.ps1`  | Health: Node B, RAG; `-FullStack` adds Daszek, kalk-top, PG                               |
| `verify-local-gates.ps1`     | Preflight + optional pytest smoke (Gate A+B)                                              |
| `push-rag-system-health.ps1` | W3: RAG health snapshot → Daszek + `rag.kb_health.snapshot` (cron/harness)                |
| `preflight-workspace.ps1`    | Workspace-level checks                                                                    |
| `session-closeout.ps1`       | Session end checklist helper                                                              |
| `compile-world-state.py`     | World-state compile helper                                                                |
| `load-secrets.ps1`           | Inject Bitwarden vault secrets into .env (Phase 1: cookies). Requires `BWS_ACCESS_TOKEN`. |

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
```

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
