---
name: code-intelligence-routing
description: Use when choosing GitNexus, CBM, Serena, CodeScene, or Context7 for code exploration; proving index freshness; or deciding whether to reindex a repo in top-code workspace. Not for runtime proof or Gate B.
---

# Code Intelligence Routing

Source: workspace canonical router — do not duplicate `CODE_INTELLIGENCE_ROUTER.md`.

## Use When

- Unknown area, symbol lookup, blast radius, API/MCP contracts, refactor impact, or debug routing.
- A graph or MCP result will influence an edit, commit, or cross-repo change.
- Index age or MCP health is unclear before trusting a structural claim.

## Do Not Use When

- External library docs only → Context7 (see `.cursor/rules/40-context7-auto-docs.mdc`).
- Runtime or browser proof → tests, logs, Playwright, Gate A/B skills.
- Narrow file read with known path → source read / `rg` first (Codex safe mode).

## Canonical SSOT

- Roles and routes: `knowledge/system-atlas/tooling/CODE_INTELLIGENCE_ROUTER.md`
- MCP policy: `knowledge/TOOLING_POLICY.md`
- Thin table: root `AGENTS.md` §Code Intelligence Router

## Procedure (pick one tool)

1. **Classify the question** (area / symbol / impact / graph edge / API / quality / runtime).
2. **Prove freshness** (minimal — stop when sufficient):

   | Layer    | Fresh enough when |
   | -------- | ----------------- |
   | GitNexus | MCP smoke OK; repo analyzed after last material change on that repo; cross-repo uses group `topinstal-workspace` |
   | CBM      | `index_status` / `get_graph_schema` for explicit `project=`; not a stale or missing `.db` |
   | Serena   | Project indexed from repo root; symbol search returns current file paths |
   | CodeScene | `verify_installation` OK; on-demand only (no durable index) |

3. **Route once** — first tool from router table; add second only if high-risk or ambiguous.
4. **Verify** structural hints with source read or test before editing.
5. **Reindex only if needed** — one explicit repo, not whole workspace (see `references/reindex-commands.md`).

## High-risk shortcut

Public API, DTO, DB, auth, policy/HITL, routing, cross-repo contract, or many consumers:

```text
GitNexus (process + impact) → Serena (references) → CBM (independent graph query if still ambiguous)
```

CodeScene judges maintainability, not architectural correctness.

## Reindex triggers (any one)

- Custom CBM query fails schema / empty graph after confirmed code exists.
- GitNexus `detect_changes` or impact clearly stale vs `git diff`.
- Large contract or topology change in the repo you are about to edit.
- Preflight warns missing/stale unified GitNexus or Graphify (ops — see references).

Do **not** reindex: docs-only task, single-file fix with known path, or “just in case”.

## Validation

```powershell
python scripts/dev-tooling/test_mcp_configuration.py -q
python scripts/agent_harness_audit.py
```

After harness edits:

```powershell
python scripts/context_link_audit.py --scope workspace
```

## Report

- Question type and chosen first tool.
- Freshness evidence (what you checked).
- Reindex run: yes/no, which repo, which command.
- Conflicts: runtime/code vs graph — state evidence order used.
- Graph used as proof: **no** (structural hint only).
