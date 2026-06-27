-- GraphStore namespace migration
-- Creates separate schemas for temporal and RAG policy data

CREATE SCHEMA IF NOT EXISTS temporal;
CREATE SCHEMA IF NOT EXISTS rag_policy;

-- Migrate existing temporal tables
ALTER TABLE entity_facts SET SCHEMA temporal;
ALTER TABLE entity_edges SET SCHEMA temporal;
ALTER TABLE entity_resolution SET SCHEMA temporal;

-- Migrate existing RAG policy tables
ALTER TABLE policy_rules SET SCHEMA rag_policy;
ALTER TABLE rag_chunks SET SCHEMA rag_policy;
