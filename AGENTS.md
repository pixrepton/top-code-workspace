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

| Product              | Folder                  | Node | Entry AGENTS                                                                                                |
| -------------------- | ----------------------- | ---- | ----------------------------------------------------------------------------------------------------------- |
| gmail-agent AI       | `gmail-agent/`          | B    | `gmail-agent/AGENTS.md` (Quality Sprint F1-F5 complete — exceptions, logging, LLM resilience, write safety) |
| Daszek UI            | `daszek/`               | A    | [`daszek/README-DASZEK.md`](daszek/README-DASZEK.md) §16 (new: Tasks view with 3 sections)                  |
| RAG backend          | `rag-chat-asystent/`    | B    | `rag-chat-asystent/AGENTS.md` (Graph RAG: `docs/GRAPH_RAG_RUNTIME.md`)                                      |
| RAG widget WP        | `rag-widget/`           | A    | `rag-widget/AGENTS.md`                                                                                      |
| WP mail bridge       | `wp-bridges/`           | A    | `wp-bridges/AGENTS.md`                                                                                      |
| kalk-top             | `kalk-top/`             | A    | `kalk-top/AGENTS.md`                                                                                        |
| Cieplo worker        | `cieplo-orchestrator/`  | B    | `cieplo-orchestrator/AGENTS.md`                                                                             |
| Generator            | `top-instal-generator/` | A    | `top-instal-generator/AGENTS.md`                                                                            |
| fast-kalk            | `fast-kalk/`            | A    | `fast-kalk/AGENTS.md`                                                                                       |
| Cross-repo knowledge | `knowledge/`            | meta | `knowledge/PROJECT_README.md`                                                                               |

## Quality Sprint 2026-07-03 podsumowanie

Dwie sesje: pierwsza (2026-07-02 20:30-11:55) Quality Sprint 1-5 + 18 zadan; druga (2026-07-03 11:56-19:10) dogrywka + fazy D/E/F.

### Sesja 1 7h25min

- Exception hierarchy (exceptions.py) 33 klas
- Structured logging (log_config.py) JSON + correlation context
- LLM resilience timeout 45s/30s/60s circuit breaker
- Write safety auto-commit atomic transakcje idempotency
- Tasks UI widok Zadania w Daszku
- 18 zadan produkcyjnych action proposal validation structured logging
- Docker fix gmail-agent-worker restart loop

### Sesja 2 7h15min

- Phase 1 Exception Taxonomy +14 klas aplikacja catch-all w 8 plikach
- Phase 2 Structured Logging 4 pliki get_logger 3 pliki z dodanym loggerem
- Phase 3 LLM Resilience \_call_with_retry() 60s + exponential backoff
- Phase 4 Business Logic Safety agent_goals.yaml env vars guardy biznesowe
- Phase 5 Type Safety Pydantic schemas Protocols conn:Any poprawione
- Phase D-F UnderstandingOutput/IntakeSnapshot/MemoryRecord modele 21 testow Write Safety Audit
- Docker rebuild gmail-agent-nodeb-api

### Enterprise Closeout 2026-07-04

| Co                                  | Efekt                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Distributed tracing                 | 8 faz pokryte przez ContextVar w log_config.py                                                                                                                                                                                                                                                                                                                                               |
| Graceful shutdown                   | SIGTERM handler w signal_worker                                                                                                                                                                                                                                                                                                                                                              |
| Connection pool + circuit breaker   | daszek_client (pool 20, 3 fail cooldown 120s)                                                                                                                                                                                                                                                                                                                                                |
| CAS retry + rate limiting LLM       | materialize_bridge + central_llm_stage Semaphore(2)                                                                                                                                                                                                                                                                                                                                          |
| Feed cache + concurrency control    | daszek_v3_feed_runtime + graph.py Semaphore(1)                                                                                                                                                                                                                                                                                                                                               |
| Health endpoint workera             | /system/worker/health                                                                                                                                                                                                                                                                                                                                                                        |
| Trace endpoint                      | /system/trace                                                                                                                                                                                                                                                                                                                                                                                |
| Migracje + cleanup                  | correlation_registry + cleanup_old_events.py                                                                                                                                                                                                                                                                                                                                                 |
| Rotacja tokenow Daszek              | --service daszek                                                                                                                                                                                                                                                                                                                                                                             |
| Testy integracyjne                  | 13/13 PASS                                                                                                                                                                                                                                                                                                                                                                                   |
| Backlog resolved                    | P0.1-P0.3 zamkniete                                                                                                                                                                                                                                                                                                                                                                          |
| Dokumentacja core                   | LLM_PROVIDER_MAP, INTAKE_TRACKS, EVENT_CATALOG, AUTHZ_SCOPE_MAP, DIVERGENCE_LOOP_COVERAGE                                                                                                                                                                                                                                                                                                    |
| Chat-agent enterprise               | 16 luk zamknietych: prompt injection, operator_id, redaction BP, logowanie chat, metryki BP, TOOL_EXECUTED duration, TTL memory, connection pool, testy (29/29 PASS), personality.yaml, auto-briefing, feedback loop, request_human_handoff, cross-session memory, self-diagnosis /system/agent-health                                                                                       |
| Pipeline mailowy domkniecie         | Graceful shutdown, connection pool, circuit breaker, CAS retry, indeksy, fix 19 importow, checkpoint workera, LLM cost metrics, parallel downstream, async push, LLM caching z temperature guard, incremental feed, CI/CD workflow, agent checkpoint co ture                                                                                                                                 |
| Chat-agent enterprise (Sprint 120%) | structured logging ~32 plikow, type safety settings: Any→Settings 17 plikow, conn: Any→DatabaseConnection 9 plikow, mailbox store rozbity 2545L→4 moduly, big files refactor (intake, drive, reconciler, parser), drive/calendar/spine hardening, except:pass=0, 113/113 testow PASS. Bugi: business_pulse logger, api_app timedelta/column, status_filter. Model: deepseek→openrouter/free. |

Szczegoly knowledge/memory/LAST_SESSION.md

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

## Recent changes (2026-07-01/02)

### ETAP 1 — Infrastructure

- **D3 resolved:** Dual Gmail pollers consolidated into single signal_worker; cieplo-orchestrator poller disabled (`CIEPLO_GMAIL_POLL_ENABLED=0`)
- **Event Spine:** Enabled locally in shadow mode (`EVENT_SPINE_PROCESSOR_ENABLED=1`)
- **Decision Queue:** New `/system/decision-queue` endpoint with SLA (4h warning, 24h critical)
- **Business Dictionary:** New module `business_dictionary/` — PostgreSQL + Neo4j glossary of HVAC terms
- **System View:** Widok "System" w Daszku pokazuje health dashboard + constitution + rule candidates

### ETAP 2 — Chat Agent & Memory

- **Chat agent UI:** Zakładka "Czat" w Daszku — interfejs konwersacyjny z cyfrowym wspólnikiem
- **Operator Memory (L0):** Tabela `operator_memory` w PG — pamięta rozmowy, preferencje, klientów
- **Personalities:** Chat-agent (cyfrowy wspólnik) i mail-agent (wspólnik operacyjny) mają osobowości
- **Briefing:** Automatyczny briefing NL na starcie czatu (`/system/briefing`)

### ETAP 3 — Business Intelligence

- **9 Business Pulse tools:** pipeline, client health, daily delta, win rate, top clients, revenue forecast, system health, signals, agent activity
- **Cost tracking:** `/system/cost-summary` — tokeny i koszt dzien/tydzien
- **Quality scoring:** `/system/quality-summary` — jakosc decyzji agenta (exact/divergent rate)

### CLEANUP 2026-07-02 — Repo cleanup across all repositories

- **gmail-agent:** Usunięto 166 plików (1.2 GB model_cache, 82 proof scripts, 11 deploy scripts, 23 auxiliary scripts, 10 orphans). ~3,432 lines added (new code), ~1,026,351 removed.
- **rag-chat-asystent:** Usunięto 2.2 GB duplikat `backend/backend/` (nested model_cache).
- **7 small repos:** Usunięto `.gitnexus/` cache (~350 MB), `.venv` w cieplo-orchestrator (89 MB), `tmp/pdfs` + `backup-tekstowe` w kalk-top (51 MB), 367 `__pycache__` katalogów.
- **Nowe .gitignore:** top-instal-generator (Python/IDE/OS), wp-bridges (IDE/OS).
- **Total freed:** ~3.5 GB dysku, ~166 tracked files removed.

Evolution: `knowledge/EVOLUTION_BOUNDARIES.md`
