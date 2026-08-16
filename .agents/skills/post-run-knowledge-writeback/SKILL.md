---
name: post-run-knowledge-writeback
description: Use after a substantial coding, debugging, audit, repair, qualification, migration, or architecture session in top-code workspace to reconcile durable conclusions into canonical knowledge, current-state docs, backlog/decisions, and task checkpoints; supersede stale current claims while preserving historical evidence. Not for bulk documentation cleanup or starting new product work.
---

# Post-Run Knowledge Writeback

## Use When

- A substantial run/session has reached a material checkpoint or completion.
- New durable facts, decisions, baselines, closed blockers, residuals, contracts, or procedures were established.
- Before handing the workspace to another agent after significant work.
- The final chat report contains conclusions that should survive outside the chat.

## Do Not Use When

- The task is still actively debugging or the key conclusion is not proven yet.
- A trivial edit created no durable project knowledge.
- The goal is a workspace-wide documentation cleanup/resync rather than writeback from one completed run.
- You intend to fix newly discovered product residuals; record them, do not open new work here.

## Workspace bindings / Canonical SSOT

Load before writing:

1. root `AGENTS.md` and the owning repo `AGENTS.md`;
2. `.agents/AGENTS.md` when present;
3. current knowledge index/router (`knowledge/INDEX.md` or its current canonical replacement);
4. current task/checkpoint through `scripts/ai_os_task.py`;
5. the domain docs that already own the affected architecture/contract/procedure.

Detailed routing: [references/writeback-routing.md](references/writeback-routing.md)

## Non-negotiables

- Reconstruct truth from current source, tests, qualified artifacts, Git state, task state, and explicit operator decisions — not from the final narrative alone.
- Write only **durable** knowledge. Do not canonize hypotheses or transient diagnostics.
- Update the existing canonical owner; do not create duplicate sources of truth.
- Run a **supersession pass**: new current truth must replace stale current claims it invalidates.
- Preserve historical reports, frozen evidence, and old baselines as historical truth.
- Do not bulk-update Markdown or copy one final report into many files.
- Do not change `AGENTS.md`, `CLAUDE.md`, or skills unless the completed run actually changed a durable rule/procedure.
- Do not start new product debugging, refactors, Fresh38 runs, or architecture waves during writeback.
- The owning task/checkpoint must reflect the proven state before handoff.

## Procedure

1. **Reconstruct the run**
   - Read the material session outcome, current diff/commits, relevant tests/proofs/artifacts, and owning task/checkpoint.
   - Separate `PROVEN`, `DECISION`, `OPEN_RESIDUAL`, `HISTORICAL_ONLY`, and `HYPOTHESIS`.

2. **Build a knowledge-item manifest before editing**
   - For each durable conclusion record: `item → class → evidence → canonical owner → supersedes → action`.
   - Use the routing reference; discover the real current owner instead of assuming a path.

3. **Write to canonical owners only**
   - Current state, session handoff, decisions, backlog, architecture, contracts, procedures, tooling, measurement/capability state, or Git state only where genuinely affected.
   - Use `NOT_REQUIRED` rather than manufacturing edits.

4. **Supersede stale current truth**
   - Search active/canonical docs for claims invalidated by the new proof.
   - Correct or mark them superseded according to existing conventions.
   - Do not rewrite historically correct old run reports.

5. **Reconcile task/checkpoint state**
   - Close/supersede resolved blockers and stale `next_action` values through the canonical task workflow.
   - Prefer `scripts/ai_os_task.py`; do not hand-edit checkpoint JSON when the task engine supports the change.

6. **Review the writeback diff**
   - Preserve foreign dirty state.
   - Verify each changed file has a clear knowledge owner/reason.
   - Remove accidental duplication, narrative bloat, and unsupported claims.

7. **Leave a durable handoff**
   - The next agent must be able to recover the important current state, what was closed, what remains open, and what must not be re-investigated without reading the previous chat.

## Validation

Always:

```powershell
git diff --check
git status --short
```

For touched canonical docs, verify links/routes relevant to the changed files and search for superseded active claims.

If this writeback changes harness docs, skills, routers, `AGENTS.md`, or other agent-control-plane material, also run:

```powershell
python scripts/agent_harness_audit.py
python scripts/context_link_audit.py --scope workspace
```

Do not escalate to broad runtime/product qualification solely to validate documentation writeback.

## Report

- Durable conclusions written back.
- Files updated: knowledge class + why that file owns the information.
- Stale current claims superseded.
- Files intentionally left historical/unchanged.
- Task/checkpoint: previous → current state; blockers closed/open.
- Backlog: added / closed / superseded.
- Git: affected repo(s), foreign dirty state preserved, commit/push status.
- Next-agent handoff: current truth, open work, and what must not be re-investigated.
