-- =============================================================================
-- Rollback indeksów z scripts/index_migration.sql (2026-07-03)
--
-- Uruchomić w razie problemów wydajnościowych:
--   psql postgresql://mailbox_memory:memorka@localhost:54129/mailbox_memory -f scripts/index_rollback.sql
-- =============================================================================

DROP INDEX IF EXISTS idx_cases_stage;
DROP INDEX IF EXISTS idx_cases_engagement_id;
DROP INDEX IF EXISTS idx_proposals_engagement_status_created;
DROP INDEX IF EXISTS idx_operator_memory_session_created;
DROP INDEX IF EXISTS idx_runtime_turns_engagement_created;
DROP INDEX IF EXISTS idx_os_events_engagement_occurred;
DROP INDEX IF EXISTS idx_learning_candidates_status_count;

-- Weryfikacja: po rollbacku sprawdź czy indeksy zniknęły:
--   SELECT indexname FROM pg_indexes WHERE tablename IN ('mailbox_memory_cases', 'agent_proposal_records', 'operator_memory', 'agent_runtime_turns', 'unified_os_events', 'learning_rule_candidates');
