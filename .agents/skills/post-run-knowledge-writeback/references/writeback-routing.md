# Post-Run Writeback Routing

Use this reference only after reconstructing the completed run. Paths below are examples of common owners in `top-code workspace`; the current knowledge router and repo instructions outrank examples.

## Authority order

When sources disagree, prefer the strongest current evidence:

1. current source code and explicit runtime contracts;
2. current deterministic tests;
3. qualified live artifacts / manifests / receipts;
4. Git diff / commit identity;
5. active task/checkpoint state;
6. explicit operator decisions;
7. current canonical docs;
8. historical docs and chat narrative.

If current code violates an intended canonical contract, do **not** rewrite the contract to match the bug. Record the discrepancy as a residual.

## Knowledge classes and routing

| Class | Typical content | Route to |
|---|---|---|
| `CURRENT_STATE` | current baseline, program status, active blocker, current phase | current workspace/state SoT, commonly `knowledge/memory/ACTIVE_WORKSPACE.md` or current replacement |
| `SESSION_HISTORY` | what the completed run changed/proved, important handoff | session/handoff SoT, commonly `knowledge/memory/LAST_SESSION.md` |
| `DECISION` | durable operator/architecture decision, canonical choice, invalidated path | decision SoT, commonly `knowledge/memory/OPERATOR_DECISIONS.md` |
| `BACKLOG_RESIDUAL` | new open issue, resolved blocker, superseded work | canonical backlog, commonly `knowledge/memory/BACKLOG.md` |
| `ARCHITECTURE` | ownership, SoT boundary, ingress/egress, persistent topology | existing `knowledge/system-atlas/**`, `docs/**`, or repo architecture owner |
| `CONTRACT` | API/DTO/state/lifecycle/fail-closed invariant | existing contract owner; document `WHAT / WHY / OWNER / INVARIANT / FAILURE SEMANTICS` |
| `PROCEDURE` | reusable proof/debug/recovery/Git workflow | owning `.agents/skills/**`, `.claude/skills/**`, or tooling procedure |
| `TOOLING` | GitNexus/CBM/CodeScene/MCP/task engine/harness usage | current tooling/router docs and relevant skill |
| `TESTING_MEASUREMENT` | qualification state, measurement contract, proven harness invariant | canonical evaluation/Fresh38/measurement current-state owner; raw proof stays in artifacts |
| `CAPABILITY_PRODUCT_QUALITY` | valid current score, threshold, residual cases, component quality | current capability/product-quality owner |
| `REPO_GIT_STATE` | canonical branch, SHA, local-only/pushed where tracked | only docs/manifests that intentionally track repo state |
| `HISTORICAL_EVIDENCE` | frozen reports, old baselines, raw timelines | artifacts/history; normally no edit |
| `NO_DURABLE_WRITEBACK` | transient diagnostics, failed hypothesis, disposable launcher issue | nowhere; keep only where run artifacts already preserve it |

## Required classification discipline

Before editing, every material conclusion should be classified as one of:

```text
PROVEN
DECISION
OPEN_RESIDUAL
SUPPORTED_NOT_CANONICAL
HYPOTHESIS
HISTORICAL_ONLY
```

Only `PROVEN`, `DECISION`, and real `OPEN_RESIDUAL` items normally create durable writeback.

`SUPPORTED_NOT_CANONICAL` may be reported but should not silently become current truth.

`HYPOTHESIS` never becomes canonical truth.

## Supersession pass

For each new current-state fact ask:

```text
WHAT ACTIVE CURRENT CLAIM DOES THIS INVALIDATE?
```

Examples:

```text
new: FRESH38_MEASUREMENT_QUALIFICATION = REQUALIFIED
old active claim: NOT_REQUALIFIED
→ update the active current-state owner
```

```text
new: CTX-04 lifecycle blocker = CLOSED
old active claim: CTX-04 = BLOCKED
→ close/supersede in current state, backlog, and owning checkpoint as applicable
```

```text
new: current capability baseline = 27/38
old historical report: 13 Aug baseline = 23/38
→ DO NOT alter historical report; only replace a document that incorrectly labels 23/38 as current
```

Goal:

```text
NO_CONTRADICTORY_CURRENT_TRUTH
```

## Architecture / contract writeback test

Update architecture or contract docs only when at least one is true:

- ownership changed or was durably clarified;
- a canonical path replaced another path;
- a producer/consumer contract changed;
- a state/lifecycle invariant changed;
- future agents would make a wrong design decision without the new durable explanation.

When updating, explain:

```text
WHAT
WHY
OWNER
BOUNDARY
WHAT MUST NOT DUPLICATE IT
WHAT IT SUPERSEDES
```

Do not document implementation line-by-line; code intelligence tools own that level of detail.

## AGENTS / CLAUDE / skill gate

Change agent-control-plane files only when the completed run changed the reusable rule itself.

Examples that justify a skill/rule writeback:

- a proof sequence was proven unsafe and replaced;
- a recurring agent anti-pattern now has a durable prevention rule;
- the canonical tool routing changed;
- a new mandatory closure invariant was established.

A normal bugfix, new baseline, or one-off runtime incident usually does not justify these edits.

## Task / checkpoint reconciliation

The owning task should not retain stale state such as:

```text
BLOCKED
IN_PROGRESS
next_action = investigate X
```

when X is proven closed.

Prefer the task engine to represent:

- completed phase;
- resolved/superseded blockers;
- final proof/gate identity;
- true next action;
- local commit/push state where the task schema tracks it.

Preserve historical decisions/gates rather than deleting them.

## Historical evidence rule

Never rewrite frozen proof to make history resemble the present.

Keep old:

- evaluation results;
- postmortems;
- experiment manifests;
- qualification reports;
- frozen artifacts.

A historical statement may remain true even when it is no longer current.

## Scope guard

Post-run writeback may discover more work. Route it; do not execute it.

Allowed:

```text
identify residual → add/update backlog → continue reconciliation
```

Not allowed:

```text
identify residual → start debugging/fixing → expand session
```

The only implementation changes in this phase should be direct documentation/control-plane corrections necessary for truthful writeback.

## Minimal knowledge-item manifest

Before editing, prepare internally:

| Knowledge item | Class | Evidence | Canonical owner | Supersedes | Action |
|---|---|---|---|---|---|
| current qualified baseline | CURRENT_STATE / TESTING | qualified artifact | current-state + measurement owner | prior current baseline | UPDATE |
| durable lifecycle invariant | CONTRACT | regression + live proof | measurement contract owner | invalid old assumption | UPDATE |
| raw timeline | HISTORICAL_EVIDENCE | artifact | artifact only | none | NO WRITE |
| newly exposed product residual | BACKLOG_RESIDUAL | qualified product result | backlog / quality owner | none | ADD |

## Completion questions

Before final report answer:

```text
NEW_DURABLE_KNOWLEDGE_IDENTIFIED = YES/NO
CURRENT_STATE_UPDATED = YES/NO/NOT_REQUIRED
SESSION_HISTORY_UPDATED = YES/NO/NOT_REQUIRED
BACKLOG_UPDATED = YES/NO/NOT_REQUIRED
DECISIONS_UPDATED = YES/NO/NOT_REQUIRED
ARCHITECTURE_UPDATED = YES/NO/NOT_REQUIRED
CONTRACT_DOCS_UPDATED = YES/NO/NOT_REQUIRED
PROCEDURES_UPDATED = YES/NO/NOT_REQUIRED
TOOLING_DOCS_UPDATED = YES/NO/NOT_REQUIRED
CAPABILITY_STATE_UPDATED = YES/NO/NOT_REQUIRED
TASK_CHECKPOINT_UPDATED = YES/NO/NOT_REQUIRED
STALE_CURRENT_CLAIMS_SUPERSEDED = YES/NO
HISTORICAL_EVIDENCE_PRESERVED = YES/NO
CONTRADICTORY_CURRENT_TRUTH_REMAINING = 0/N
FOREIGN_DIRTY_STATE_PRESERVED = YES/NO
```

`NOT_REQUIRED` is valid. Do not create edits merely to turn it into `YES`.
