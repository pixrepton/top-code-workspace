# AGENTS.md — TOP-INSTAL Ecosystem Router

Status: active workspace router for `top-code workspace`.
Keep this file short. Deep docs live in `knowledge/` and per-repo `AGENTS.md`.

## What this workspace is

Multi-repo TOP-INSTAL AI-OS: HVAC automation across WordPress (Node A), backends (Node B / RAG), and cross-repo contracts.

**OS guide:** `knowledge/docs/OS_README.md`
**AI-DEV onboarding:** `knowledge/docs/ai-dev-onboarding-path.md`
**Stan dla zewnętrznych asystentów:** `knowledge/memory/ACTIVE_WORKSPACE.md`
**Atlas (cross-repo):** `knowledge/SYSTEM_ATLAS.md`
**Operator environment:** `knowledge/docs/AGENT_OPERATOR_ENVIRONMENT.md`
**Active decisions (read first):** `knowledge/memory/OPERATOR_DECISIONS.md`
**Doc policy (how to write/update docs):** `knowledge/DOCUMENTATION_POLICY.md`
**MCP policy (how/when to use MCP servers):** `knowledge/MCP_POLICY.md`
**Plugin policy (how/when to use plugins):** `knowledge/PLUGIN_POLICY.md`
**Error handling policy (debug/escalate/report):** `knowledge/ERROR_HANDLING_POLICY.md`
**Security policy (secrets/tokens/creds):** `knowledge/SECURITY_POLICY.md`
**Session memory policy (cross-session persistence):** `knowledge/SESSION_MEMORY_POLICY.md`
**Workspace lifecycle policy (start/maintain/stop):** `knowledge/WORKSPACE_LIFECYCLE_POLICY.md`
**Code intelligence (grafy):** `knowledge/docs/CODE_INTELLIGENCE_STACK.md`

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

| Product              | Folder                  | Node | Entry AGENTS                                                                                                                                                                                    |
| -------------------- | ----------------------- | ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| gmail-agent AI       | `gmail-agent/`          | B    | `gmail-agent/AGENTS.md` — enterprise hardening closed (exceptions, logging, LLM resilience, write safety, distributed tracing, circuit breakers); details in `knowledge/memory/LAST_SESSION.md` |
| Daszek UI            | `daszek/`               | A    | [`daszek/README-DASZEK.md`](daszek/README-DASZEK.md) §16 — includes Tasks view (3 sections: pending/active/agent-suggested)                                                                     |
| RAG backend          | `rag-chat-asystent/`    | B    | `rag-chat-asystent/AGENTS.md` (Graph RAG: `docs/GRAPH_RAG_RUNTIME.md`)                                                                                                                          |
| RAG widget WP        | `rag-widget/`           | A    | `rag-widget/AGENTS.md`                                                                                                                                                                          |
| WP mail bridge       | `wp-bridges/`           | A    | `wp-bridges/AGENTS.md`                                                                                                                                                                          |
| kalk-top             | `kalk-top/`             | A    | `kalk-top/AGENTS.md`                                                                                                                                                                            |
| Cieplo worker        | `cieplo-orchestrator/`  | B    | `cieplo-orchestrator/AGENTS.md`                                                                                                                                                                 |
| Generator            | `top-instal-generator/` | A    | `top-instal-generator/AGENTS.md`                                                                                                                                                                |
| fast-kalk            | `fast-kalk/`            | A    | `fast-kalk/AGENTS.md`                                                                                                                                                                           |
| Cross-repo knowledge | `knowledge/`            | meta | `knowledge/PROJECT_README.md`                                                                                                                                                                   |

## Latest closure state (2026-07-04)

Enterprise hardening sprint across gmail-agent (mail + chat agent) is closed.
Proof gates: exception taxonomy, structured logging w/ correlation context,
LLM resilience (timeout + circuit breaker), write-path idempotency, chat-agent
enterprise (prompt injection guard, self-diagnosis, cross-session memory),
mailbox store split into 4 modules, 113/113 tests PASS.

Full session-by-session detail: `knowledge/memory/LAST_SESSION.md`
Do not re-read the raw session log here — it lives there by design
(see `knowledge/SESSION_MEMORY_POLICY.md`).

## Cold-start

1. **`knowledge/INDEX.md`** — jedyny punkt startowy (zawiera prawidlowy cold-start)
2. This file (AGENTS.md) — router ekosystemu
3. Target repo `AGENTS.md` + `memory-bank/last-agent-handoff.md`
4. GitNexus MCP — `query` / `impact` only
5. Serena MCP — symbol navigation / refactors
6. Source + tests

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

Labels: `proven_local` | `confirmed by local tests` | `historical` | `not proven`

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
- **Code detail (VIEW):** `knowledge/docs/CODEBASE_SNAPSHOT.md`
- **Graphify:** `knowledge/graphify/`
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

| Scope              | Where                                                                   |
| ------------------ | ----------------------------------------------------------------------- |
| Operator decisions | `knowledge/memory/OPERATOR_DECISIONS.md`                                |
| Session engram     | `top-code-memory/` (auto-archived) + `knowledge/memory/LAST_SESSION.md` |
| Single repo        | `<repo>/memory-bank/agent-handover.md`                                  |
| Cross-repo         | `knowledge/timeline/YYYY-MM.md`                                         |

See `knowledge/MEMORY_GOVERNANCE.md`

## Agent rules

- Git commit/push: only when operator explicitly asks
- No secrets in chat or commits
- Surgical diffs; match repo conventions
- `karpathy-guidelines` for implementation
- **Browser:** Firefox first for opening URLs and Playwright (see `OPERATOR_DECISIONS` §2026-06-18; `.cursor/mcp.json` playwright `--browser=firefox`)

## Architectural gaps (do not fix silently)

D1 RAG ∉ Cieplo pipeline · D2 mail → no OfferDTO · ~~D3 dual Gmail pollers~~ (RESOLVED 2026-07-02: signal_worker consolidated, cieplo poller disabled) · D4 Daszek = projection

## Repo cleanup (2026-07-02)

Freed ~3.5 GB across repos (model caches, proof script sprawl, nested duplicates, `__pycache__`). ~166 tracked files removed from gmail-agent alone. Details: `knowledge/timeline/2026-07.md`.

Evolution: `knowledge/EVOLUTION_BOUNDARIES.md`
