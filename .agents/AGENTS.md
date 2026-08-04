# AGENTS.md — .agents

Status: **Typ B — root-owned** procedural skills pack.

## Role

`skills/` describe **how** to execute certain work. They do **not** replace:

- root `../AGENTS.md` (L1)
- product-repo `AGENTS.md` (L2)
- GitNexus / CBM / generated structure maps

Control-plane map: `../knowledge/system-atlas/tooling/agent-harness/AGENT_DEVELOPMENT_HARNESS.md`  
Registry: `../knowledge/system-atlas/tooling/agent-harness/AGENT_SKILLS_REGISTRY.md`

## Rules

- Load **1–3** relevant skills per task — not the whole pack
- Commit scope: **`workspace:.agents/...`**
- Skills are procedures, not a second memory bank or backlog

## Gate

After skill/harness edits:

```powershell
python scripts/agent_harness_audit.py
python scripts/agent_map_audit.py
```

## Anti-goals

- Using skills as an alternate constitution
- Loading every skill on every task
