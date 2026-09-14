---
name: ai-os-execution
description: Use in top-code workspace for mutating or proof-bearing agent work. Canonical Execution Plane V1.1 workflow (start/resume → repo → exec → gate → commit → FINAL_HEAD → close). Do not use for read-only discovery or outside this workspace.
---

# AI-OS Execution (V1.1)

Workspace SoT. Host copies (Codex/Cursor/Claude) are pointers to this file.

## Use When

- Starting or resuming a mutating / proof-bearing task in `top-code workspace`.
- Choosing how to run tests, gates, commits, or close proof.

## Do Not Use When

- Read-only discovery with no writes and no close proof.
- Outside this workspace.
- Product-domain questions that do not need the task engine.

## Canonical workflow

NEW:

```text
start → repo → exec → gate → commit → FINAL_HEAD → close
```

EXISTING:

```text
resume → repo → exec → gate → commit → FINAL_HEAD → close
```

```powershell
python scripts/ai_os_task.py start --task-id <ID> --title "<t>" --class MEDIUM --repo <repo> --scope <repo:path>
python scripts/ai_os_task.py task-repo --repo <repo>
python scripts/ai_os_task.py exec --repo <repo> -- <command>
python scripts/ai_os_task.py task-gate --gate-id <id> --repo <repo> -- -- <command>
python scripts/ai_os_task.py task-commit-plan --repo <repo> --json
python scripts/ai_os_task.py task-commit --repo <repo> --message "<msg>"
python scripts/ai_os_task.py task-gate --gate-id FINAL_HEAD_GATE --repo <repo> --final-head -- -- <command>
python scripts/ai_os_task.py task-close --validate-only
```

RECOVERY: explicit `execution-takeover` (never from session-start).
CLEANUP: `execution-destroy`.
COLD START: `session-start` (projection only; does not takeover).

## Workspace modes

Default daily work is **DIRECT_CANONICAL**: `task-repo` is the desktop checkout
`C:\Users\compg\Desktop\top-code workspace\<repo>`. Edit, test, and commit there.
Session-scratch holds logs/proof, not a newer copy of the product.

**ISOLATED_WORKTREE** is opt-in (or automatic for TEST/BENCHMARK/REPLAY/PROOF):
benchmark, replay, high-risk experiment, parallel conflicting tasks, historical
as-of, or explicit `--workspace-mode ISOLATED_WORKTREE`. Isolated
`PASS + COMMIT_NOW` closeout **promotes** the worktree into the desktop checkout.
Do not finish with accepted product code only in session-scratch.

## Hard rules

- Mutating task without Execution Plane = FAIL CLOSED.
- DIRECT_CANONICAL: mutate the desktop checkout named by `task-repo`. Do not redirect ordinary work into a hidden session-scratch worktree.
- ISOLATED_WORKTREE: mutate that worktree, then promote on accepted closeout.
- Proof-critical commands go through mediated `exec` / trusted `task-gate`.
- Raw shell is OK for discovery. Raw pytest/build is not close proof.
- TAINTED is not PASS. Receipts from a previous generation are invalid.
- Image proof must come from the bundle checkout (`task-repo`).
- Legacy (`--legacy`) only where the task-engine allows SMALL + DOCS/STATIC/READ_ONLY_LOCAL.
- Transcripts and old plans are HISTORICAL_CONTEXT, never CURRENT_INSTRUCTION.
- Coding reports start with `## Zmienione pliki` (desktop paths only); commit SHA is secondary; GitHub only on PUBLISH/SHIP.
- `kontynuuj` binds to the open user goal in the current thread — not archived task IDs / MEMORY NEXT.

## Current state

Session-start / `session-start` injects current task, execution, generation, worktree HEAD, taint, latest trusted receipt, FINAL_HEAD, NEXT. Do not reconstruct that from chat history.

## Validation

```powershell
python scripts/ai_os_task.py session-start
python -m pytest scripts/test_ai_os_execution_plane.py -q
```
