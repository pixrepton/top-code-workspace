---
name: code-intelligence-routing
description: Use when exploring code in top-code workspace — load before broad Read/Grep; route through GitNexus, CBM, Serena, or CodeScene per CODE_INTELLIGENCE_ROUTER.md; reindex via MCP tools after larger changes. Not for runtime proof or Gate B.
---

# Code Intelligence Routing

Source: workspace canonical router — do not duplicate `CODE_INTELLIGENCE_ROUTER.md`.

## Use When

- Exploring an unknown area, symbol, workflow, dependency, contract, or blast radius.
- Any code exploration where the default impulse is workspace-wide `Read` / `Grep` / `rg`.
- Before an edit, commit, or cross-repo change that depends on structure you have not routed yet.
- After a **larger change** in a repo — reindex that repo through MCP tools before the next exploration pass.

## Do Not Use When

- External library docs only → Context7 (see `.cursor/rules/40-context7-auto-docs.mdc`).
- Runtime or browser proof → tests, logs, Playwright, Gate A/B skills.
- Operator gave an exact file path and line range with no structural question.

## Canonical SSOT (load first)

1. This `SKILL.md`
2. `knowledge/system-atlas/tooling/CODE_INTELLIGENCE_ROUTER.md`
3. MCP policy: `knowledge/TOOLING_POLICY.md`
4. Thin table: root `AGENTS.md` §Code Intelligence Router

## Procedure

1. **Load SSOT** (steps above) — do not start with blind file reads or repo-wide grep.
2. **Classify the question** (area / symbol / impact / graph edge / API / quality / runtime).
3. **Prove freshness** (minimal — stop when sufficient):

   | Layer     | Fresh enough when                                                                                                |
   | --------- | ---------------------------------------------------------------------------------------------------------------- |
   | GitNexus  | MCP smoke OK; repo analyzed after last material change on that repo; cross-repo uses group `topinstal-workspace` |
   | CBM       | `index_status` / `get_graph_schema` for explicit `project=`; not a stale or missing `.db`                        |
   | Serena    | Project indexed from repo root; symbol search returns current file paths                                         |
   | CodeScene | `verify_installation` OK; on-demand only (no durable index)                                                      |

4. **Explore via MCP/graph** — pick **one** first tool from the router table; add a second only if high-risk or ambiguous.
5. **Read source narrowly** — only the files/symbols MCP narrowed; use `Grep`/`rg` for literals, dynamic dispatch, or gaps the graph cannot see.
6. **After larger changes** — reindex the touched repo via MCP index tools (GitNexus analyze, CBM `index_repository`, Serena `project index`); see `references/reindex-commands.md`.

## High-risk shortcut

Public API, DTO, DB, auth, policy/HITL, routing, cross-repo contract, or many consumers:

```text
GitNexus (process + impact) → Serena (references) → CBM (independent graph query if still ambiguous)
```

CodeScene judges maintainability, not architectural correctness.

## Reindex triggers (any one)

- You just landed a larger contract, topology, or multi-file change in a repo.
- Custom CBM query fails schema / empty graph after confirmed code exists.
- GitNexus `detect_changes` or impact clearly stale vs `git diff`.
- Preflight warns missing/stale unified GitNexus or Graphify (ops — see references).

Do **not** reindex: docs-only task, trivial one-line fix with no structural exploration, or “just in case”.

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

- Question type and chosen first MCP/graph tool.
- Freshness evidence (what you checked).
- Reindex run: yes/no, which repo, which MCP index path.
- Source reads: which files MCP routed you to (not a blind scan).
- Graph used as proof: **no** (structural hint only).
