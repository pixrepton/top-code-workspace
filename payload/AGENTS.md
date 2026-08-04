# AGENTS.md — payload

Status: **Typ B — root-owned** local payloads / scratch fixtures. **Not SoT.**

## Role

Temporary request bodies and samples for local smoke/proof.

## Rules

- Ecosystem rules: `../AGENTS.md` (L1)
- No secrets, tokens, customer data, or full mailbox dumps
- Contents are **not** canonical documentation (`knowledge/` wins)
- Durable fixtures belong in the owning product repo’s tests
- Most payload files should stay gitignored; commit only deliberate allowlisted files (e.g. this `AGENTS.md`)
- Not a document store, RAG corpus, or case database

## Gate

No product Gate A here. Owner-repo tests and smokes remain authoritative.

## Commit

- Repo: **`workspace`**, path `payload/AGENTS.md` only (unless operator expands allowlist)

## Anti-goals

- Second RAG corpus or case DB here
- Committing PII “for convenience”
