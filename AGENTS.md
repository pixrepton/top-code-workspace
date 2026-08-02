# AGENTS.md — TOP-INSTAL Workspace Router

Status: active router for `top-code workspace`.

This workspace contains nested, independent Git repositories.

Treat the root workspace Git state and every nested repository Git state separately.

## Core Invariants

- `gmail-agent` / Node B is the operational Source of Truth for cases, engagements, mailbox policy and runtime truth.
- `daszek` is projection-only UI and bounded HITL. It is not a write Source of Truth.
- `kalk-top` owns HVAC logic and `OfferDTO`. Do not duplicate `OfferDTO`, sizing, pricing or HVAC decision logic elsewhere.
- `cieplo-orchestrator` is a separate worker and pipeline with its own database. It is not a second Source of Truth for cases.
- Current proven runtime evidence and executable behavior win over stale documentation.
- A currently running behavior may still be a bug. Treat runtime as evidence of what happens, not automatic proof of what should happen.
- Do not claim success without current, reproducible proof.
- Default operational scope is local Docker only.
- No VPS, SSH, production mutation, deploy or legacy host work unless explicitly requested by the operator.
- The active stability freeze defined in `knowledge/memory/OPERATOR_DECISIONS.md` remains binding.

## Cold-Start

The canonical cold-start order lives exclusively in:

`knowledge/INDEX.md` §Cold-Start

Follow that sequence.

Do not duplicate or recreate the cold-start sequence in this file or elsewhere.

Manual session start:

`scripts/run-session-start-hooks.ps1`

Then read:

`C:\top-code-session-scratch\SESSION_START_CONTEXT.md`

unless `TOP_CODE_SESSION_SCRATCH` overrides that location.

## Memory

Persistent project memory lives only in:

- `knowledge/memory/OPERATOR_DECISIONS.md`
- `knowledge/memory/BACKLOG.md`
- `knowledge/memory/ACTIVE_WORKSPACE.md`
- `knowledge/memory/LAST_SESSION.md`

Do not create or restore:

- `top-code-memory/`
- repo-local `memory-bank/`
- autonomous memory stores,
- transcript stores,
- reflection stores,
- shadow backlogs,
- parallel decision logs.

Do not write new persistent memory without an explicit operator instruction.

## Repo Routing

- `gmail-agent/` — Node B; mailbox/case runtime; operational Source of Truth for cases, decisions and execution.
- `daszek/` — Node A; operator projection UI and bounded HITL.
- `kalk-top/` — owner of HVAC logic, sizing, pricing and `OfferDTO`.
- `cieplo-orchestrator/` — separate Cieplo pipeline and worker with its own database.
- `rag-chat-asystent/` — RAG backend, ingest and retrieval.
- `rag-widget/` — WordPress RAG surface and adapters.
- `top-instal-generator/` — PDF/DOCX generation.

If a task crosses repository boundaries:

1. Identify the affected contracts.
2. State which component owns each piece of data or logic.
3. Preserve existing Source of Truth boundaries.
4. Avoid duplicating domain logic across services.
5. Verify the cross-service flow, not only isolated unit behavior.

## Workspace and Git Discipline

The workspace may already contain unrelated or pre-existing changes.

Always separate your edits from existing modifications.

Do not treat the workspace as a monorepo for status, diff review or history analysis.

Check Git state in the specific repository being modified.

Do not run unless explicitly requested:

- `git reset`
- `git clean`
- `git commit`
- `git push`
- production deploys
- destructive workspace cleanup

Do not overwrite or revert changes you did not create unless the operator explicitly requests it.

## Stability and Change Discipline

Prefer the smallest correct change.

For protected or stability-sensitive runtime, use:

diagnosis → root cause → RED proof → minimal fix → GREEN proof → relevant regression → full required gates → runtime proof / parity → review.

Do not use a passing unit test as proof of end-to-end correctness when the affected behavior crosses services, databases, workers or UI projections.

Do not expand a fix into an architectural redesign unless the existing architecture is itself the demonstrated root cause.

Classify newly discovered problems as:

- required blocker for the current task,
- or backlog item.

Fix only blockers needed to complete the current scope.

## Evidence Hierarchy

When sources disagree, reason explicitly from the strongest available evidence.

Prefer, in order of relevance:

1. current reproducible runtime evidence,
2. executable tests and deterministic proofs,
3. current implementation and configuration,
4. active operator decisions,
5. current canonical documentation,
6. stale historical documentation.

Runtime evidence describes what the system actually does.

It does not automatically prove that the behavior is correct.

Never silently reconcile conflicting sources by guessing.

## Tool Discipline

Use specialized tools when they provide materially better information than raw file scanning.

For code discovery, architecture, dependencies, call paths and impact analysis,
follow the applicable repository AGENTS.md,
`knowledge/system-atlas/tooling/CODEX_EXECUTION_MAP.md`,
and the relevant maintained tool instructions.
CLAUDE.md files are Claude Code adapters, not canonical project policy.

Treat `knowledge/`, especially `knowledge/gitnexus/`, and maintained code-intelligence indexes such as Codebase Memory MCP as operational support for routing, impact analysis and cross-repo discovery. Their results stay advisory until freshness is proved and the result is verified in current source.

For known files, configuration and documentation, direct file reads are appropriate.

For proof, prefer deterministic commands and existing repository gates over narrative confidence.

After substantial code, contract, topology or workflow changes, explicitly assess whether GitNexus indexes/group views, Codebase Memory indexes/graphs and affected maintained files in `knowledge/` need refresh.

If refresh is feasible within the current local scope, perform the minimal required refresh or update and report what was refreshed, what remains stale and what is still only advisory.

If a specialized tool is unavailable, stale or incomplete, state that explicitly before using a fallback.

## Scope Boundary

The default task boundary is the current request.

Do not:

- redesign adjacent systems without necessity,
- introduce new infrastructure for hypothetical future problems,
- add parallel workflow systems,
- create new memory layers,
- perform production work without authorization.

When a better long-term solution exists but exceeds current scope, record it only in the canonical backlog and only when explicitly instructed to update project memory.

## Completion Standard

A task is not complete merely because code was changed.

Completion requires the level of proof appropriate to the change.

For stability-sensitive work, report clearly:

- what changed,
- root cause,
- tests executed,
- regressions checked,
- runtime or integration proof,
- remaining uncertainty,
- final status: PASS, PARTIAL or FAIL.

Never report PASS when required proof is missing.
