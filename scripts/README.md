# Workspace harness (`TOP_CODE_ROOT/scripts`)

Cross-repo PowerShell harness for local Docker stack. Versioned in the workspace root meta-repo (not inside `gmail-agent` / `rag-chat-asystent`).

## Scripts

| File | Purpose |
|------|---------|
| `resolve-paths.ps1` | Sets `TOP_CODE_ROOT` and per-repo env paths (sourced by others) |
| `sync-local-stack-env.ps1` | Sync `.env.local-vps`, audit `.env`, Daszek `.env.daszek-local`, RAG wire |
| `preflight-local-stack.ps1` | Health: Node B, RAG; `-FullStack` adds Daszek, kalk-top, PG |
| `verify-local-gates.ps1` | Preflight + optional pytest smoke (Gate A+B) |
| `preflight-workspace.ps1` | Workspace-level checks |
| `session-closeout.ps1` | Session end checklist helper |
| `compile-world-state.py` | World-state compile helper |

## Operator workflow

```text
zmiana portów/kluczy → sync-local-stack-env.ps1 → recreate kontenerów jeśli tokeny
start sesji / proof     → preflight-local-stack.ps1 (-FullStack przed Gmail+Daszek)
większy gate            → verify-local-gates.ps1
```

After token sync (`DASZEK_NODE_B_SERVICE_TOKEN`, `NODE_B_REGISTRY_TOKEN`): recreate `gmail-agent-worker` and Daszek WP.

## References

- `knowledge/CONTROL_PLANE.md` — `proven_local` gate
- `knowledge/world-state.yaml` — endpoint ports
- `.cursor/rules/35-local-stack-harness-workflow.mdc` — agent workflow
