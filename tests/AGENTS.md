# AGENTS.md — tests

Status: **Typ B — root-owned** workspace-level tests (not an independent Git repository).

## Role

Only truly cross-repo / workspace E2E / temporary migration harnesses.

## Rules

- Ecosystem rules: `../AGENTS.md` (L1)
- Domain tests belong in the **owning product repo** Gate A suites
- This folder does **not** replace product Gate A
- Do not claim `confirmed by local tests` from this folder alone if the owner Gate A did not pass
- Durable fixtures belong in the owning repo
- No secrets, tokens, or customer PII

## Gate

Prefer the owning repo Gate A. Workspace-level files here are supplemental only; there is no substitute package gate for product repos.

## Commit

- Repo: **`workspace`**, path `tests/...` (only files allowlisted in root `.gitignore`)

## Anti-goals

- Parallel “AI-OS test framework” duplicating product suites
- Shadow proof replacing owner gates
