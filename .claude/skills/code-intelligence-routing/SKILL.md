---
name: code-intelligence-routing
description: Use when exploring code in top-code workspace — load before broad Read/Grep; verify which structural MCP tools are connected this session; route through GitNexus or CBM per CODE_INTELLIGENCE_ROUTER.md. Not for runtime proof or Gate B.
---

# Code Intelligence Routing

Explore via MCP/graph before broad Read/Grep. Full route table: `knowledge/system-atlas/tooling/CODE_INTELLIGENCE_ROUTER.md`.

Source: workspace canonical router — do not duplicate `CODE_INTELLIGENCE_ROUTER.md`.

Mirror: `.claude/skills/code-intelligence-routing/` (Claude Code discovery); keep content in sync with this file.

## Use When

- Exploring an unknown area, symbol, workflow, dependency, contract, or blast radius.
- Any code exploration where the default impulse is workspace-wide `Read` / `Grep` / `rg`.
- Before an edit, commit, or cross-repo change that depends on structure you have not routed yet.
- After a **larger change** in a repo — reindex that repo through MCP tools before the next exploration pass.

## Do Not Use When

- External library docs only → Context7.
- Runtime or browser proof → tests, logs, Playwright, Gate A/B skills.
- Operator gave an exact file path and line range with no structural question.

## Step 0 — verify what is connected THIS session

Repo docs describe GitNexus MCP tools as always available — **verify per session** (Cursor: MCP catalog / `GetMcpTools`; Claude Code: `ToolSearch(query: "gitnexus")`).

- **GitNexus MCP live** → use `list_repos`, `query`, `context`, `impact`, `detect_changes` per `knowledge/system-atlas/tooling/CODE_INTELLIGENCE_ROUTER.md`.
- **GitNexus not in catalog** → CLI/index only; route through **Codebase Memory (CBM)**:

```text
search_code      # graph-ranked search (project= required)
trace_path       # callers/callees/impact
query_graph      # custom graph queries
get_architecture # package/service overview
detect_changes   # before commit
index_repository # after larger edits (mode=fast)
```

CBM project names follow `C-Users-<user>-Desktop-top-code-workspace-<repo>` (derive from workspace path; do not guess).

## Procedure

1. **Step 0** — never assume GitNexus MCP is live.
2. **Classify the question** (area / symbol / impact / graph edge / API / quality / runtime).
3. **Prove freshness**: GitNexus `list_repos` → `commitsBehind`; CBM via successful `search_code` on a known symbol + compare repo HEAD if needed; reindex if stale.
4. **Explore via the live graph tool** — one first tool from the router table; second only if high-risk or ambiguous.
5. **Read source narrowly** — only files/symbols the graph narrowed; `Grep`/`rg` for literals and gaps.
6. **After larger changes** — reindex touched repo (GitNexus `analyze` / CBM `index_repository`).

## High-risk shortcut

Public API, DTO, DB, auth, policy/HITL, routing, cross-repo contract, or many consumers:

```text
impact / trace_path (inbound, risk_labels=true) on every symbol you will edit
→ confirm no unaccounted CRITICAL/HIGH callers → edit
```

## Report

- Question type and chosen first MCP/graph tool.
- Step 0 result: which server/tools were actually used.
- Freshness evidence (`commitsBehind`, index dates, or HEAD comparison).
- Reindex: yes/no, which repo.
- Source reads: which files the graph routed you to.
- Graph used as proof: **no** (structural hint only).
