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

The workspace contains independent Git repositories. Resolve and operate on the
exact repository root for every status, branch, diff, gate, commit and remote
action. Never infer nested repository state from workspace-root Git.

For every task that writes files:

1. Start or resume the Wave 01 checkpoint with exact `repo:path` scope.
2. Capture and preserve the pre-existing staged, unstaged and untracked state.
3. Create a task branch before the first write when the current branch is the
   default/protected branch.
4. Use the shared task engine for write guards, gates, commit planning and
   commits.
5. Finish with no task-owned residue and with every created commit recorded.

An operator request to fix, implement, migrate, configure, update or complete a
repair package authorizes safe local branch creation and scoped local commits
needed to finish that task. The agent does not ask separately for every local
commit.

Local commit authorization does not authorize push, PR creation, merge,
deployment, VPS work or any other external/live write. Publication mode is
recorded in the checkpoint:

- `LOCAL_ONLY` — local branch and local commits only; default.
- `PUBLISH` — push and draft PR are in scope; merge is not.
- `SHIP` — prepare and verify a merge-ready PR; merge and deployment remain
  separate operator-approved actions.

Do not use raw `git add` or `git commit` for agent work. Use:

- `scripts/ai_os_task.py task-commit-plan --repo <repo> --json`
- `scripts/ai_os_task.py task-commit --repo <repo> --message "<message>"`

The wrapper must isolate task-owned content, preserve foreign staged state,
block secrets and ownership conflicts, verify the final commit paths and record
the resulting SHA in the checkpoint.

Do not run:

- `git reset`;
- `git clean`;
- destructive `git restore` or `git checkout -- <path>`;
- force push;
- stash deletion;
- forced branch deletion;
- history rewriting or automatic amend/rebase cleanup.

Do not overwrite, revert, stage or commit changes you did not create or
explicitly adopt. When multiple agents share one working tree, the main agent
owns staging and commits. A subagent may commit only in an explicitly isolated
worktree and branch.

Read the canonical procedure in:

`knowledge/system-atlas/tooling/GIT_AND_CHANGE_CONTROL.md`

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
`knowledge/system-atlas/tooling/CODE_INTELLIGENCE_ROUTER.md`,
and the relevant maintained tool instructions.
CLAUDE.md files are Claude Code adapters, not canonical project policy.

Treat `knowledge/`, especially `knowledge/gitnexus/`, and maintained code-intelligence indexes such as Codebase Memory MCP as operational support for routing, impact analysis and cross-repo discovery. Their results stay advisory until freshness is proved and the result is verified in current source.

For known files, configuration and documentation, direct file reads are appropriate.

For proof, prefer deterministic commands and existing repository gates over narrative confidence.

After substantial code, contract, topology or workflow changes, explicitly assess whether GitNexus indexes/group views, Codebase Memory indexes/graphs and affected maintained files in `knowledge/` need refresh.

If refresh is feasible within the current local scope, perform the minimal required refresh or update and report what was refreshed, what remains stale and what is still only advisory.

If a specialized tool is unavailable, stale or incomplete, state that explicitly before using a fallback.

## Code Intelligence Router

Do not explore code randomly and do not query every MCP tool “just in case”.
First classify the question, then take the canonical route.

Full route tables and high-risk protocol:
`knowledge/system-atlas/tooling/CODE_INTELLIGENCE_ROUTER.md`

### Roles

- **GitNexus** — architecture, processes, clusters, dependencies, blast radius, API and cross-repo contracts.
- **Codebase Memory (CBM)** — raw structural graph, call graph, types, routes, infrastructure, custom graph queries.
- **Serena** — IDE semantics: symbols, declarations, implementations, references, rename and precise edits.
- **CodeScene** — maintainability, Code Health, qualitative risk and pre-commit quality gate.
- **Tests/runtime** — only proof of actual system behavior.

### Choose the route

| Need                                        | First tool                                            | Next step                                    |
| ------------------------------------------- | ----------------------------------------------------- | -------------------------------------------- |
| Unknown area or concept                     | GitNexus `query`                                      | process / cluster / context                  |
| Architecture / workflow                     | GitNexus resources / process                          | Serena for key symbols                       |
| Concrete symbol                             | Serena `find_symbol`                                  | `find_referencing_symbols`                   |
| Dependencies / blast radius                 | GitNexus `impact`                                     | Serena references                            |
| Exact call graph / custom edges             | CBM `get_graph_schema` → `trace_path` / `query_graph` | Serena for code                              |
| Public API / MCP tool / cross-repo contract | GitNexus `route_map` / `tool_map` / group contracts   | `shape_check` / `api_impact` + contract test |
| Type / interface / DTO                      | Serena                                                | CBM `IMPLEMENTS` / `USES_TYPE` at high risk  |
| Refactor                                    | CodeScene review + GitNexus impact                    | edit via Serena                              |
| Rename                                      | Serena rename                                         | GitNexus rename only as fallback             |
| Debugging                                   | GitNexus query / trace                                | Serena → CBM → runtime                       |
| Before commit                               | tests → GitNexus `detect_changes`                     | CodeScene `pre_commit_code_health_safeguard` |

### Standard change path

1. Resolve owning repository and Source of Truth.
2. GitNexus for process, area and blast radius.
3. Serena for exact symbols and semantic references.
4. CBM only for raw graph, exact call graph, cross-service edges or a custom query.
5. For refactor: CodeScene `code_health_review` before editing.
6. Edit symbolically via Serena when the change is symbol-scoped.
7. Run required tests and runtime proof.
8. GitNexus `detect_changes`.
9. CodeScene `pre_commit_code_health_safeguard`.
10. Do not declare success from a graph or Code Health alone.

### High-risk and boundaries

For public API, DTO, data, auth, policy/HITL, cross-repo contract or side effects require GitNexus impact/contract tools, Serena references, CBM as independent graph confirmation, plus test or runtime proof.

CodeScene is not a dependency oracle. Graphs are not runtime proof. Do not run four tools when one canonical answer is clear. When tools disagree, verify current code and runtime.

### Index scope (do not invent one mega-index)

- **CBM:** per-repo graphs only; always pass explicit `project=` (path-derived IDs on this host). No `workspace-root` meta-index.
- **GitNexus:** true Git repos + root shell; cross-repo via group `topinstal-workspace`. Embeddings temporarily `DISABLED_DUE_TO_UPSTREAM_BUG` on 1.6.9. `wp-bridges` is not a separate GitNexus project.
- **Serena:** per-repo `.serena/project.yml`; root is only `top-code-workspace-shell`.
- **CodeScene:** no durable index; on-demand quality analysis.

Full mapping and freshness rules: `knowledge/system-atlas/tooling/CODE_INTELLIGENCE_ROUTER.md`.

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
