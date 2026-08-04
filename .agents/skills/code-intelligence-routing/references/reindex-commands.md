# Reindex via MCP tools (targeted)

After **larger code changes** in a repo, refresh that repo's indexes through MCP-capable tooling **before** the next exploration pass. Run from workspace root unless noted. Refresh **one** repo or the minimum set the task touches.

## Preflight (warnings only)

```powershell
.\scripts\preflight-workspace.ps1
```

## GitNexus — per-repo + group sync

```powershell
.\knowledge\gitnexus\reindex-workspace.ps1
```

Single repo (example `gmail-agent`):

```powershell
gitnexus analyze --force --skip-git --index-only --name gmail-agent "C:\Users\compg\Desktop\top-code workspace\gmail-agent"
.\knowledge\gitnexus\sync-group.ps1 -RunSync
```

Unified graph (heavy — only when cross-repo process map requires it):

```powershell
.\knowledge\gitnexus\reindex-workspace.ps1 -Unified
```

Config repair:

```powershell
.\knowledge\gitnexus\set-gitnexus-cursor-config.ps1
.\knowledge\gitnexus\verify-knowledge.ps1 -FixConfig
```

**Note:** GitNexus embeddings remain disabled per `CODE_INTELLIGENCE_ROUTER.md` until upstream fix is proven.

## CBM — per-repo index

```powershell
python scripts/dev-tooling/cbm_index_repos.py gmail-agent
```

All nested repos (long):

```powershell
python scripts/dev-tooling/cbm_index_repos.py
```

Diagnose:

```powershell
python scripts/dev-tooling/cbm_mcp_diagnose.py
```

Always pass explicit `project=` in MCP queries — no workspace-root meta graph.

## Serena — per-repo

From repo directory:

```powershell
$env:PYTHONUTF8 = "1"
cd gmail-agent
serena project index
```

## MCP smoke

```powershell
python scripts/dev-tooling/test_mcp_configuration.py -q
```

## Evidence order on conflict

Runtime/test → current code → Serena/LSP → fresh GitNexus → fresh CBM → historical docs.
