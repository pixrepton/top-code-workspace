# AGENTS.md — TOP-INSTAL Ecosystem Router

Status: active workspace router for `top-code workspace`.
Keep this file short. Deep docs live in `knowledge/` and per-repo `AGENTS.md`.

## What this workspace is

Multi-repo TOP-INSTAL AI-OS: HVAC automation across WordPress (Node A), backends (Node B / RAG), and cross-repo contracts.

**OS guide:** `knowledge/OS_README.md`
**AI-DEV onboarding (full system path):** `knowledge/docs/ai-dev-onboarding-path.md` · prompt `knowledge/prompts/ai-dev-session-start.md`
**Stan dla zewnętrznych asystentów:** `knowledge/docs/current-state-for-assistants.md` · sesja `knowledge/docs/session-summary-2026-06-25.md`
**Atlas (cross-repo):** `knowledge/SYSTEM_ATLAS.md`
**Operator environment:** `knowledge/AGENT_OPERATOR_ENVIRONMENT.md`
**Active decisions (read first):** `knowledge/memory/OPERATOR_DECISIONS.md`
**Code intelligence (grafy):** `knowledge/docs/CODE_INTELLIGENCE_STACK.md` · skill `code-intelligence-router`

## Deployment model

| Tier            | Meaning                                                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **active**      | Local Docker — `:8766` gmail-agent Node B, `:8090` Daszek, `:8091` kalk-top, `:8000` RAG, `:54129` mailbox PG, `:54130` GraphStore PG |
| **production**  | **Suspended** (2026-06-17) — firma w zawieszeniu; brak VPS. Agent nie pracuje nad prod deploy dopóki operator nie powiadomi.          |
| **legacy_prod** | Historical dual VPS — do not use for new proof                                                                                        |
| **target_prod** | One unified VPS (frozen future) — `knowledge/rfc/single-unified-vps.md`                                                               |

**Agent default:** work to Gate B locally. No SSH/VPS/prod deploy unless operator explicitly resumes business and asks.

Machine map: `ECOSYSTEM_MAP.yaml`

## Logical products

| Product              | Folder                  | Node | Entry AGENTS                                                           |
| -------------------- | ----------------------- | ---- | ---------------------------------------------------------------------- |
| gmail-agent AI       | `gmail-agent/`          | B    | `gmail-agent/AGENTS.md`                                                |
| Daszek UI            | `daszek/`               | A    | [`daszek/README-DASZEK.md`](daszek/README-DASZEK.md) §16               |
| RAG backend          | `rag-chat-asystent/`    | B    | `rag-chat-asystent/AGENTS.md` (Graph RAG: `docs/GRAPH_RAG_RUNTIME.md`) |
| RAG widget WP        | `rag-widget/`           | A    | `rag-widget/AGENTS.md`                                                 |
| WP mail bridge       | `wp-bridges/`           | A    | `wp-bridges/AGENTS.md`                                                 |
| kalk-top             | `kalk-top/`             | A    | `kalk-top/AGENTS.md`                                                   |
| Cieplo worker        | `cieplo-orchestrator/`  | B    | `cieplo-orchestrator/AGENTS.md`                                        |
| Generator            | `top-instal-generator/` | A    | `top-instal-generator/AGENTS.md`                                       |
| fast-kalk            | `fast-kalk/`            | A    | `fast-kalk/AGENTS.md`                                                  |
| Cross-repo knowledge | `knowledge/`            | meta | `knowledge/PROJECT_README.md`                                          |

## Cold-start read order

1. This file
2. `knowledge/world-state.yaml` — ownership, proof, open_p0/p1, gaps, boundaries **(kanoniczny model strukturalny)**
3. `knowledge/CONTROL_PLANE.md` — 5 warstw epistemicznych (`proven_local` vs `vision`)
4. `knowledge/memory/OPERATOR_DECISIONS.md` (all `[ACTIVE]`)
5. `knowledge/BACKLOG_ARCHITECTURE_REVIEW_2026-06.md` — priorytety otwartej pracy (lokalnie); skrót: `BACKLOG_ROADMAP_2026-06.md`
6. `knowledge/AGENT_OPERATOR_ENVIRONMENT.md` if runtime/deploy
7. `knowledge/SYSTEM_ATLAS.md` §0–§4 + `TOPINSTAL-KERNEL-GRAPH.yaml`
8. Target repo `AGENTS.md` + `memory-bank/last-agent-handoff.md`
9. GitNexus MCP — `query` / `impact` only (po freshness check; nie full analyze w chacie)
10. Serena MCP — symbol navigation / refactors (`initial_instructions` first call per session)
11. Source + tests

`knowledge/CODEBASE_SNAPSHOT.md` — VIEW (ładuj na żądanie po krokach 2–3, nie domyślnie). Do not read all Markdown flat. Do not load full repos into context.

## Modes (`knowledge/.cursorrules`)

- **Execution:** respect As-Is; no new HTTP edges without approval; report contract impact
- **Discovery:** RFC in `knowledge/rfc/` before cross-repo code

## Ownership (non-negotiable)

- `OfferDTO` / HVAC → **kalk-top**
- Mailbox case / policy → **gmail-agent**
- Operator UI projection → **daszek** (not SoT)
- RAG retrieval / ingest → **rag-chat-asystent** (not widget)
- RAG chat UI on WWW → **rag-widget** (HTTP client only)
- Cieplo workflow → **cieplo-orchestrator** (separate DB)
- PDF/DOCX → **top-instal-generator**

## Local endpoints

```text
gmail-agent API   http://127.0.0.1:8766   # host port; container listens on 8765; 8765 if GMAIL_AGENT_NODEB_PORT unset
RAG backend       http://127.0.0.1:8000
Daszek sandbox    http://127.0.0.1:8090
kalk-top runtime  http://127.0.0.1:8091
Postgres mailbox  localhost:54129         # gmail-agent / mailbox_memory
Postgres GraphStore localhost:54130       # rag-chat-asystent graphstore-postgres
rag-widget dev    API URL → http://127.0.0.1:8000
```

Preflight: `scripts/preflight-local-stack.ps1`

**Harness workflow (cross-repo, versioned in workspace root git):**

```text
zmiana portów/kluczy → scripts/sync-local-stack-env.ps1 → recreate worker+Daszek jeśli tokeny
start sesji / proof     → scripts/preflight-local-stack.ps1 (-FullStack = cały stack)
większy gate            → scripts/verify-local-gates.ps1
agent closure           → build/recreate + proof script samemu; raport dopiero po *_PROOF_OK
```

Details: `scripts/README.md` · agent rules `35-local-stack-harness-workflow.mdc` (§ Agent-owned closure), `92-proof-gate-discipline.mdc`

## Proof tiers

| Tier   | Meaning                                                            |
| ------ | ------------------------------------------------------------------ |
| Gate A | pytest / npm test / compileall                                     |
| Gate B | local smoke (`_local_smoke_run.py`, doctor, preflight-local-stack) |
| Gate C | VPS — **disabled by default**                                      |

Labels: `confirmed locally` | `confirmed by local tests` | `historical` | `not proven`

**Master proof (2026-06-20):** `MAX_STACK_10_PROOF_OK` via `gmail-agent/tools/gmail_audit/scripts/verify-max-stack.ps1` (requires `GRAPHSTORE_DSN` for temporal sub-proofs).

## Cross-repo routing

| Task                 | Start in            | Also read                    |
| -------------------- | ------------------- | ---------------------------- |
| Mail case, Skrzat    | gmail-agent         | daszek if UI                 |
| Daszek feed/bridge   | daszek              | gmail-agent runbooks         |
| Calculator, OfferDTO | kalk-top            | docs/contracts               |
| Cieplo → PDF         | cieplo-orchestrator | kalk-top contracts           |
| RAG ingest/retrieval | rag-chat-asystent   | not rag-widget               |
| RAG widget UI        | rag-widget          | WIDGET_BACKEND_COMPATIBILITY |
| New HTTP edge        | knowledge/rfc/      | SYSTEM_ATLAS                 |

After REST contract changes: `gitnexus group sync topinstal-workspace --verbose` (operator/agent terminal)

## Knowledge (docs + code map)

- **Agent canon (SoT):** `knowledge/world-state.yaml` → `knowledge/CONTROL_PLANE.md`
- **Code detail (VIEW):** `knowledge/CODEBASE_SNAPSHOT.md` — load on demand, not by default
- **Graphify** (offline MCP): `knowledge/graphify/build-knowledge-graph.ps1` — artifact at `graphify-out/graph.json`
- **Understand Anything** (static graph): `.understand-anything/knowledge-graph.json` — check `meta.json` for freshness

## Serena MCP (symbolic code / LSP)

Active for the **whole monorepo** via `serena` in root `.cursor/mcp.json` (`--context ide --project ${workspaceFolder}`).

- Project config: `.serena/project.yml` (languages: python, typescript, php, powershell)
- Cache: `.serena/cache/` (gitignored); memories: `.serena/memories/` (commit conventions only when useful)
- Use Serena for **symbol navigation**, **cross-file rename**, **replace_symbol_body**, **references**, **diagnostics** on real product code
- Keep Cursor built-ins for trivial one-line edits; do not index `_graphify-corpus/` or `_md_audit/`
- After MCP reload, call `initial_instructions` once per session if tools are not auto-loaded
- Governance: `gmail-agent/docs/dev/MCP_OPERATING_MODEL.md` (Serena = allowed for this workspace)

## Memory writes

| Scope              | Where                                           |
| ------------------ | ----------------------------------------------- |
| Operator decisions | `knowledge/memory/OPERATOR_DECISIONS.md`        |
| Session engram     | `knowledge/memory/engrams/` + `LAST_SESSION.md` |
| Single repo        | `<repo>/memory-bank/agent-handover.md`          |
| Cross-repo         | `knowledge/timeline/YYYY-MM.md`                 |

See `knowledge/MEMORY_GOVERNANCE.md`

## Agent rules

- Git commit/push: only when operator explicitly asks
- No secrets in chat or commits
- Surgical diffs; match repo conventions
- `karpathy-guidelines` for implementation
- **Browser:** Firefox first for opening URLs and Playwright (see `OPERATOR_DECISIONS` §2026-06-18; `.cursor/mcp.json` playwright `--browser=firefox`)

## Architectural gaps (do not fix silently)

D1 RAG ∉ Cieplo pipeline · D2 mail → no OfferDTO · D3 dual Gmail pollers · D4 Daszek = projection

Evolution: `knowledge/EVOLUTION_BOUNDARIES.md`
