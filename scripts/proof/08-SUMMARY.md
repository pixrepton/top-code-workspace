# Production Simulation Proof Pack — 2026-06-27

## Stage A1: Docker Rebuild

**Evidence files:**
- `01-before-rebuild.txt` — container agent_runtime listing (missing files: signal_registry.py, idempotency.py, ENTITY_REGISTRY_SCHEMA.sql, 003/004 migration SQLs)
- `02-after-rebuild.txt` — docker build log + new image digest

**Outcome:** IMAGE REBUILT SUCCESSFULLY
- Old image: `c916b2ebc292` (2026-06-24)
- New image: `2b1e899d16a2` (2026-06-27 14:33)
- signal_registry.py present: YES
- idempotency.py present: YES
- migration SQLs 003/004 present: YES

## Stage A2: SCENARIO 1 — New Cold Lead

**Evidence files:**
- `03-scenario1-response.json` — full /agent-chat response
- `04-scenario1-os-events.json` — OS events
- `07-health-endpoints.json` — health checks

**Results:**

| Check | Expected | Actual | Status |
|---|---|---|---|
| Signal created | signal_id starts with sig_ | sig_b2012b3d8177090a8c71148c | PASS |
| Engagement created | non-empty | stg_sig_b2012b3d | PASS |
| HITL required | true | true | PASS |
| Agent turns | >= 1 | 2 | PASS |
| Proposals generated | >= 1 | 0 | FAIL |
| HTTP status | 200 | 200 | PASS |

**Root cause of 0 proposals:**
The agent's first tool call (`extract_facts_from_text`) fails because all configured LLM providers return errors. The tool needs to extract structured HVAC facts from the lead text using an LLM, but all providers in the chain fail. The agent then calls `report_gaps_and_stop` and stops.

**Fixes applied during Stage A:**
1. Added `operator_scope` field to `SignalRuntimeContext` dataclass in `signal_reconciler.py`
2. Updated `AGENT_CONSTITUTION.md` to reference correct generic tool names
3. Updated `.env.local-vps` fallback model from `deepseek/deepseek-chat:free` to `deepseek/deepseek-chat`

**Remaining blocker:**
LLM provider chain fails for signal extraction. Needs configuration audit of `central_llm_stage.py` and provider keys.

## Stage A3: SCENARIO 2 — Follow-up

**Status:** CANCELLED (cannot be executed until SCENARIO 1 produces a case_id)

## Stage A4: Health Checks (SCENARIO 4)

| Endpoint | Expected | Actual | Status |
|---|---|---|---|
| GET /health (gmail-agent) | {"ok": true} | {"ok": true} | PASS |
| GET /health (RAG :8000) | {"status": "healthy"} | {"status": "healthy"} | PASS |
| GET /system/health/status | HTTP 200 | HTTP 500 | FAIL (known bug) |
| OS Events | non-empty | 3 events found | PASS |
