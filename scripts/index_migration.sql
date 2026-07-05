-- =============================================================================
-- Indeksy wydajnościowe (2026-07-03)
--
-- Uruchomić na bazie mailbox_memory:
--   psql postgresql://mailbox_memory:memorka@localhost:54129/mailbox_memory -f scripts/index_migration.sql
-- =============================================================================

-- 1. cases(stage) — szybkie filtrowanie spraw według etapu
CREATE INDEX IF NOT EXISTS idx_cases_stage
    ON mailbox_memory_cases (stage);

-- 2. cases(engagement_id) — szybkie wyszukanie sprawy po engagement
CREATE INDEX IF NOT EXISTS idx_cases_engagement_id
    ON mailbox_memory_cases (engagement_id);

-- 3. agent_proposal_records(engagement_id, status, created_at DESC)
--    — szybkie pobranie ostatnich propozycji dla engagement
CREATE INDEX IF NOT EXISTS idx_proposals_engagement_status_created
    ON agent_proposal_records (engagement_id, status, created_at DESC);

-- 4. operator_memory(session_id, created_at DESC)
--    — szybkie pobranie ostatnich tur w sesji operatora
CREATE INDEX IF NOT EXISTS idx_operator_memory_session_created
    ON operator_memory (session_id, created_at DESC);

-- 5. agent_runtime_turns(engagement_id, created_at ASC)
--    — szybkie pobranie tur agenta dla engagement (turn_journal list_turns)
CREATE INDEX IF NOT EXISTS idx_runtime_turns_engagement_created
    ON agent_runtime_turns (engagement_id, created_at ASC);

-- 6. unified_os_events(engagement_id, occurred_at DESC)
--    — szybkie pobranie timeline zdarzeń dla engagement
CREATE INDEX IF NOT EXISTS idx_os_events_engagement_occurred
    ON unified_os_events (engagement_id, occurred_at DESC);

-- 7. learning_rule_candidates(status, supporting_count DESC)
--    — szybkie pobranie kandydatów do przeglądu
CREATE INDEX IF NOT EXISTS idx_learning_candidates_status_count
    ON learning_rule_candidates (status, supporting_count DESC);

-- 8. mailbox_memory_cases(status) — szybkie filtrowanie dla feeda (open cases)
CREATE INDEX IF NOT EXISTS idx_cases_status
    ON mailbox_memory_cases (status);

-- 9. unified_os_events(processing_status, created_at DESC)
--    — szybkie claimowanie batchy przez EventProcessor
CREATE INDEX IF NOT EXISTS idx_os_events_processing_status
    ON unified_os_events (processing_status, created_at DESC);

-- 10. worker_heartbeat — DDL dla Fazy 0b (health endpoint workera)
CREATE TABLE IF NOT EXISTS worker_heartbeat (
    worker_id TEXT PRIMARY KEY,
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    iteration_count INT NOT NULL DEFAULT 0,
    last_error TEXT,
    loop_mode TEXT,
    last_message_id TEXT,
    last_replayed_signal_id TEXT
);

-- 11. llm_response_cache — cache odpowiedzi LLM dla temperature=0 (Krok 5)
CREATE TABLE IF NOT EXISTS llm_response_cache (
    query_hash TEXT PRIMARY KEY,
    stage_name TEXT NOT NULL DEFAULT '',
    response TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'groq',
    model TEXT NOT NULL DEFAULT '',
    temperature REAL NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '24 hours'
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_expires ON llm_response_cache(expires_at);

-- 12. operator_memory — dodanie operator_id dla izolacji miedzy operatorami (Krok A2)
ALTER TABLE IF EXISTS operator_memory ADD COLUMN IF NOT EXISTS operator_id TEXT NOT NULL DEFAULT 'default';
DROP INDEX IF EXISTS IF EXISTS idx_opmem_type_key;
CREATE INDEX IF NOT EXISTS idx_opmem_operator ON operator_memory(operator_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_opmem_operator_type_key ON operator_memory(operator_id, memory_type, key);

-- 13. learning_rule_candidates(status, pattern_key) — szybkie wyszukanie kandydatow pattern learnera
CREATE INDEX IF NOT EXISTS idx_learning_pattern
    ON learning_rule_candidates (status, pattern_key);

-- Weryfikacja: po uruchomieniu sprawdź czy indeksy są używane:
--   EXPLAIN ANALYZE SELECT * FROM mailbox_memory_cases WHERE stage = 'NEW_LEAD';
--   EXPLAIN ANALYZE SELECT * FROM agent_proposal_records WHERE engagement_id = 'xxx' ORDER BY created_at DESC LIMIT 10;
