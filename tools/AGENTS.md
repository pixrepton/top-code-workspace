# AGENTS.md — tools

Status: **Typ B — root-owned**; shadow / legacy layout. **Default: STOP / read-only.**

## Role

Not the canonical source tree for gmail-agent tooling.

## Hard rules

1. Ecosystem rules: `../AGENTS.md` (L1)
2. Before any edit here: check whether this path is a symlink, junction, worktree, duplicate, or stale checkout.
3. Canonical gmail audit code lives in: `../gmail-agent/tools/gmail_audit/`
4. **Do not write here** when the owning copy exists under `gmail-agent`.
5. Cleanup of this shadow requires an explicit operator decision — do not “fix in silence”.

## Gate

Gate A always runs in **`gmail-agent`** (`python -m pytest tools/gmail_audit/tests -q` from that repo). Never claim proof from this folder alone.

## Commit

- If a tracked stub must change: repo **`workspace`**, path `tools/...` (allowlisted files only)

## Anti-goals

- Divergent edits in a shadow copy
- Treating `tools/gmail_audit` as SoT
