-- Read-only diagnostic role for Claude Code access to gmail-agent mailbox-memory Postgres.
--
-- Scope: SELECT-only, current schema objects + future tables (via default privileges).
-- No INSERT/UPDATE/DELETE/DDL/superuser. No password stored here — set it out-of-band
-- (e.g. env var, local .env.mailbox-memory, not committed to git).
--
-- Usage (against the mailbox-memory-db service defined in
-- gmail-agent/docker-compose.mailbox-memory.yml):
--   docker exec -i gmail-agent-mailbox-memory psql -U mailbox_memory -d mailbox_memory \
--     -v role_password="'REPLACE_ME_LOCALLY'" -f create-readonly-postgres-role.sql
--
-- This script is idempotent (safe to re-run).

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'claude_readonly') THEN
    CREATE ROLE claude_readonly WITH LOGIN PASSWORD :role_password NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END
$$;

-- Explicit connect-only, no ability to create objects in the database.
REVOKE ALL ON DATABASE mailbox_memory FROM claude_readonly;
GRANT CONNECT ON DATABASE mailbox_memory TO claude_readonly;

GRANT USAGE ON SCHEMA public TO claude_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO claude_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO claude_readonly;

-- Cover tables created after this script runs (migrations), without re-granting manually.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO claude_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO claude_readonly;

-- Defense in depth: statement timeout + no superuser bypass, in case the role is ever
-- reused somewhere idle-in-transaction could matter.
ALTER ROLE claude_readonly SET statement_timeout = '30s';
ALTER ROLE claude_readonly SET idle_in_transaction_session_timeout = '30s';
