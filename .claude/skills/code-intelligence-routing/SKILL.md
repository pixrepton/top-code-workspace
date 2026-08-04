---
name: code-intelligence-routing
description: Use when exploring code in top-code workspace — load before broad Read/Grep; verify which structural MCP tools are actually connected this session (CBM is the confirmed one; GitNexus MCP tools/resources are frequently NOT registered even though repo docs describe them); route through whichever is live per CODE_INTELLIGENCE_ROUTER.md. Not for runtime proof or Gate B.
---

# Code Intelligence Routing (Claude Code entry point)

Source: workspace canonical router — do not duplicate `CODE_INTELLIGENCE_ROUTER.md`.
Same registry entry as `.agents/skills/code-intelligence-routing/` (Codex); this file exists
because Claude Code's `Skill` tool only discovers skills under `.claude/skills/`, not
`.agents/skills/` — invoking `code-intelligence-routing` by name previously failed with
"Unknown skill" for Claude Code even though `AGENT_SKILLS_REGISTRY.md` names it as the
workspace's default pre-Read/Grep activator.

## Use When

- Exploring an unknown area, symbol, workflow, dependency, contract, or blast radius.
- Any code exploration where the default impulse is workspace-wide `Read` / `Grep` / `rg`.
- Before an edit, commit, or cross-repo change that depends on structure you have not routed yet.
- After a **larger change** in a repo — reindex that repo through MCP tools before the next
  exploration pass.

## Do Not Use When

- External library docs only → Context7.
- Runtime or browser proof → tests, logs, Playwright, Gate A/B skills.
- Operator gave an exact file path and line range with no structural question.

## Step 0 — verify what is actually connected THIS session (do this every session, not once)

Repo docs (`CLAUDE.md`, `AGENTS.md`, generated `gitnexus:start/end` blocks, other GitNexus
skills) describe GitNexus `query`/`context`/`impact` as MCP tools and `gitnexus://...` as MCP
resources, as if always available. **They are not always registered.** Before trusting any of
that text:

```
ToolSearch(query: "gitnexus", max_results: 15)
```

- If it returns `mcp__...gitnexus...` tool schemas → GitNexus MCP tools are live; use them per
  `CODE_INTELLIGENCE_ROUTER.md` / the `gitnexus-*` skills.
- If it returns nothing (confirmed the common case in this workspace as of 2026-08) → GitNexus
  is CLI/index-only for this session (only the passive `PreToolUse` hook annotation on
  Read/Grep/Bash/Glob results, not a callable tool). **Do not silently fall back to plain
  Read/Grep** — use **Codebase Memory (CBM)** instead:

```
mcp__codebase-memory__list_projects        # confirm the repo is indexed + branch/head freshness
mcp__codebase-memory__search_code          # graph-ranked grep replacement
mcp__codebase-memory__trace_path           # callers/callees/impact, mode=calls|data_flow|cross_service
mcp__codebase-memory__query_graph          # custom Cypher when trace_path/search_code aren't enough
mcp__codebase-memory__detect_changes       # before commit, compare against base branch
```

CBM projects are named `C-Users-<user>-Desktop-top-code-workspace-<repo>` — run `list_projects`
once per session rather than guessing the name.

## Procedure

1. **Step 0** above — never assume GitNexus MCP tools are live.
2. **Classify the question** (area / symbol / impact / graph edge / API / quality / runtime).
3. **Prove freshness**: CBM — `index_status` / `get_graph_schema` for the exact `project=`, not
   stale or missing; reindex (`index_repository`, `mode="fast"` for a quick post-edit refresh) if
   the project head doesn't match `git log -1` or a larger structural change just landed.
4. **Explore via the live graph tool** — pick one first tool from the router table; add a second
   only if high-risk or ambiguous.
5. **Read source narrowly** — only the files/symbols the graph tool narrowed; use `Grep`/`rg` for
   literals, dynamic dispatch, or gaps the graph cannot see.
6. **After larger changes** — reindex the touched repo (CBM `index_repository`; GitNexus
   `analyze` only if step 0 confirmed it's live).

## High-risk shortcut

Public API, DTO, DB, auth, policy/HITL, routing, cross-repo contract, or many consumers:

```text
CBM trace_path (impact, direction=inbound, risk_labels=true) on every symbol you're about to
edit → confirm no CRITICAL/HIGH caller you haven't accounted for → edit
```

## Report

- Question type and chosen first MCP/graph tool.
- Step 0 result: GitNexus MCP tools found via ToolSearch or not, which tool was actually used.
- Freshness evidence (what you checked).
- Reindex run: yes/no, which repo, which MCP index path.
- Source reads: which files the graph tool routed you to (not a blind scan).
- Graph used as proof: **no** (structural hint only, not runtime proof).
