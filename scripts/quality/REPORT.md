# Code Quality Scan Report - `scripts/`

Generated: 2026-08-03
Scope: all Python files under `scripts/` (excluding `scripts/quality/` scan artifacts).
Status: scan-only - no production code modified.

## Ranking rule

Files are ordered worst-first using an ordinal priority, **not** a fake composite score:

1. CodeScene Code Health (lower worse; Red <4, Yellow 4.0-8.9, Green 9.0-9.9, Optimal 10.0).
2. Within similar health, CodeScene `analyze_change_set` verdict `degraded` ranks worse than `N/A`/absent.
3. Higher maximum Radon cyclomatic complexity.
4. Lower Radon Maintainability Index.
5. Bandit MEDIUM/HIGH count, then remaining Bandit findings.
6. Remaining static findings (Ruff; confirmed Vulture).

Where CodeScene health is `N/A`, sort uses boundary placeholder **9.0 only for ordering** (after all measured Yellow/Red); the table cell stays `N/A`. Change signal is `N/A` when the file is not in the branch diff vs `master` (not inferred as stable).

## Hotspot table

| Pri | File | Max CC | MI | CS Health | CS Change | Ruff | Vulture conf. | Bandit |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 1 | `scripts/ai_os_task.py` | 26 (D) | 0.00 | 3.98 | N/A | 92 | 0 | 9 |
| 2 | `scripts/ai_os_task_ownership.py` | 24 (D) | 17.64 | 6.74 | degraded | 41 | 0 | 6 |
| 3 | `scripts/rotate_google_token.py` | 29 (D) | 39.51 | 7.26 | N/A | 35 | 0 | 1 |
| 4 | `scripts/ai_os_claude_hook.py` | 18 (C) | 23.58 | 7.68 | degraded | 27 | 0 | 2 |
| 5 | `scripts/dev-tooling/cbm_mcp_diagnose.py` | 13 (C) | 30.99 | 8.11 | degraded | 11 | 0 | 5 |
| 6 | `scripts/row4a_browser_proof.py` | 21 (D) | 28.42 | 8.51 | N/A | 23 | 0 | 1 |
| 7 | `scripts/ai_os_codex_hook.py` | 11 (C) | 28.68 | 8.59 | N/A | 11 | 0 | 2 |
| 8 | `scripts/parse_transcript.py` | 17 (C) | 53.24 | 8.85 | N/A | 7 | 0 | 0 |
| 9 | `scripts/dev-tooling/cbm_index_repos.py` | 14 (C) | 37.38 | 8.95 | degraded | 6 | 0 | 4 |
| 10 | `scripts/architecture-drift-check.py` | 9 (B) | 38.09 | 8.95 | N/A | 10 | 0 | 3 |
| 11 | `scripts/case_os_master_harness.py` | n/a | 54.33 | N/A | N/A | 4 | 0 | 2 |
| 12 | `scripts/check_latest_turns_v2.py` | n/a | 56.36 | N/A | N/A | 8 | 0 | 0 |
| 13 | `scripts/rag-quality-proof.py` | 14 (C) | 43.21 | 9.24 | N/A | 3 | 0 | 1 |
| 14 | `scripts/dev-tooling/test_ai_os_git_control.py` | 8 (B) | 26.41 | 9.38 | N/A | 7 | 0 | 30 |
| 15 | `scripts/dev-tooling/test_ai_os_codex_hook.py` | 7 (B) | 24.67 | 9.38 | N/A | 5 | 0 | 26 |
| 16 | `scripts/report-risk-flags.py` | 20 (C) | 45.59 | 9.42 | N/A | 11 | 0 | 0 |
| 17 | `scripts/audit-rag-env.py` | 17 (C) | 50.69 | 9.48 | N/A | 2 | 0 | 0 |
| 18 | `scripts/dev-tooling/test_ai_os_parallel_tasks.py` | 9 (B) | 22.31 | 9.68 | N/A | 13 | 0 | 36 |
| 19 | `scripts/dev-tooling/test_mcp_configuration.py` | 6 (B) | 16.06 | 9.84 | degraded | 5 | 0 | 57 |
| 20 | `scripts/compile-world-state.py` | 14 (C) | 62.44 | 9.84 | N/A | 3 | 0 | 2 |
| 21 | `scripts/monthly_rule_review.py` | 8 (B) | 51.81 | 9.84 | N/A | 15 | 0 | 0 |
| 22 | `scripts/e2e_full_flow_proof.py` | 8 (B) | 68.54 | 9.84 | N/A | 5 | 0 | 4 |
| 23 | `scripts/cleanup-proof-risk-flag-cases.py` | 8 (B) | 47.61 | 10.00 | N/A | 5 | 0 | 3 |
| 24 | `scripts/e2e_full_flow.py` | 8 (B) | 48.05 | 10.00 | N/A | 17 | 0 | 6 |
| 25 | `scripts/dev-tooling/mcp_smoke_probe.py` | 7 (B) | 46.36 | 10.00 | N/A | 2 | 0 | 4 |
| 26 | `scripts/dev-tooling/test_agent_git_configuration.py` | 7 (B) | 46.74 | 10.00 | N/A | 4 | 0 | 13 |
| 27 | `scripts/cleanup-precedent-proof-data.py` | 6 (B) | 60.24 | 10.00 | N/A | 1 | 0 | 1 |
| 28 | `scripts/dev-tooling/test_ai_os_task.py` | 5 (A) | 22.64 | 10.00 | N/A | 4 | 0 | 32 |
| 29 | `scripts/dev-tooling/test_ai_os_claude_hook.py` | 4 (A) | 31.52 | 10.00 | N/A | 5 | 0 | 18 |
| 30 | `scripts/refactor_drive_ingest.py` | 4 (A) | 55.47 | 10.00 | N/A | 68 | 0 | 0 |
| 31 | `scripts/dev-tooling/test_git_change_control_rules.py` | 4 (A) | 61.57 | 10.00 | N/A | 0 | 0 | 4 |
| 32 | `scripts/push-operational-feed-now.py` | 4 (A) | 62.15 | 10.00 | N/A | 5 | 0 | 0 |
| 33 | `scripts/push-kalk-top-heartbeat.py` | 4 (A) | 64.12 | 10.00 | N/A | 2 | 0 | 1 |
| 34 | `scripts/audit_export_vs_db.py` | 4 (A) | 64.90 | 10.00 | N/A | 1 | 0 | 0 |
| 35 | `scripts/smoke-gmail-attachment-find-case.py` | 4 (A) | 67.98 | 10.00 | N/A | 1 | 0 | 0 |
| 36 | `scripts/dev-tooling/cbm_mcp_diagnose_one.py` | 4 (A) | 77.38 | 10.00 | N/A | 1 | 0 | 0 |
| 37 | `scripts/export_bootstrap_emails.py` | 3 (A) | 79.63 | 10.00 | N/A | 1 | 0 | 0 |
| 38 | `scripts/cleanup_old_events.py` | 2 (A) | 70.38 | 10.00 | N/A | 8 | 0 | 0 |

Per-symbol max-CC detail: `hotspot-table.json`.
## Deep-review selection

Selected **10** files with measured CodeScene health **< 9.0** (Yellow/Red). Clear cutoff before Green (>=9.24).
Files with CS Health `N/A` (`case_os_master_harness.py`, `check_latest_turns_v2.py`) were **not** deep-reviewed: no reliable CodeScene value and no elevated CC/security signal justifying an exception.
`test_mcp_configuration.py` is change-set `degraded` but Green (9.84) and was not deep-reviewed.

Selected:
- P1: `scripts/ai_os_task.py` (CS Health 3.98)
- P2: `scripts/ai_os_task_ownership.py` (CS Health 6.74)
- P3: `scripts/rotate_google_token.py` (CS Health 7.26)
- P4: `scripts/ai_os_claude_hook.py` (CS Health 7.68)
- P5: `scripts/dev-tooling/cbm_mcp_diagnose.py` (CS Health 8.11)
- P6: `scripts/row4a_browser_proof.py` (CS Health 8.51)
- P7: `scripts/ai_os_codex_hook.py` (CS Health 8.59)
- P8: `scripts/parse_transcript.py` (CS Health 8.85)
- P9: `scripts/dev-tooling/cbm_index_repos.py` (CS Health 8.95)
- P10: `scripts/architecture-drift-check.py` (CS Health 8.95)

Low-ranked files were not manually reviewed. Exception: none beyond the cross-file lock/staging risk between `ai_os_task.py` and `ai_os_task_ownership.py` (both selected).
## Deep-review findings

Evidence-backed semantic findings only. Style/Ruff issues omitted.

### Cross-file: `ai_os_task.py` <-> `ai_os_task_ownership.py`

- **Problem:** `RegistryLock` covers `task-start`/`task-close`, but checkpoint RMW (`task-checkpoint`, `task-gate`, post-commit checkpoint write) and ownership snapshot reads during commit are not under the same lock; `RepoCommitLock` serializes commit/branch only.
- **Impact:** Parallel Claude/Codex hooks can last-writer-wins overwrite checkpoint JSON; ownership baseline can race with commit staging.
- **Fix:** Per-task file lock (or broaden registry lock) around every checkpoint RMW; keep commit under both repo lock and task lock.

### `scripts/ai_os_task.py`

#### DR-1 - `RegistryLock.__enter__` stale unlock TOCTOU
- **Function:** `RegistryLock.__enter__` (~186-190)
- **Problem:** After `REGISTRY_LOCK_STALE_SECONDS`, any waiter may `unlink` the lock file without proving the owner process is dead.
- **Evidence:** age-based `self.path.unlink()` then retry `O_EXCL` create.
- **Impact:** Two agents can believe they hold exclusive registry access -> conflicting task-start/close.
- **Fix:** PID + liveness check / heartbeat, or OS advisory lock; never steal without verifying owner.

#### DR-2 - Inconsistent lock failure policy (`RegistryLock` vs `RepoCommitLock`)
- **Functions:** `RegistryLock.__enter__`, `RepoCommitLock.__enter__` (~1109-1115)
- **Problem:** Registry lock steals after 30s; git commit lock never recovers - crash leaves permanent blocker.
- **Impact:** Operator stuck on `git-*.lock`, or false exclusivity on registry.
- **Fix:** One PID/heartbeat strategy for both locks.

#### DR-3 - `commit_task` non-atomic finalize after Git commit
- **Function:** `commit_task` (~1166-1194)
- **Problem:** After successful `git commit`, real-index restore (`_set_index_state` post_index) and checkpoint append are outside a single failure boundary; unexpected paths raise *after* HEAD moved.
- **Impact:** Local commit with checkpoint missing SHA, or partially restored index for foreign staged paths.
- **Fix:** Record SHA immediately after commit; restore index in `try/finally` with residue report; explicit recovery path.

#### DR-4 - `load_checkpoint` migrates legacy without registry lock
- **Function:** `load_checkpoint` -> `migrate_legacy_checkpoint` (~261-262)
- **Problem:** Migration also runs from unlocked readers while `new_checkpoint` migrates under lock.
- **Impact:** Race on `shutil.move` of legacy checkpoint.
- **Fix:** Migrate only under `RegistryLock`.

### `scripts/ai_os_task_ownership.py`

#### DR-5 - Commit content taken from worktree, not index
- **Function:** `prepare_owned_commit_states` (~384-395)
- **Problem:** `combined = _state_from_worktree(...)`; staged-only deltas can diverge from owned staged state.
- **Impact:** Commit may omit or include different content than the staging plan implies.
- **Fix:** Require worktree==index for owned paths, or explicitly merge index+worktree policy.

#### DR-6 - Ownership baseline directories lack lifecycle cleanup
- **Function:** `create_baseline_storage` (~74-78)
- **Problem:** Snapshot dirs under `state_dir` are created per capture; close/replace paths do not reliably delete them.
- **Impact:** Growing scratch usage; stale snapshots if path retained in JSON.
- **Fix:** Delete `snapshot_directory` on close/replace/cleanup.

#### DR-7 - Soft ownership conflicts still allow `COMMIT_READY`
- **Functions:** `assess_ownership` vs commit-plan path in `ai_os_task.py` (~966-971)
- **Problem:** Some ownership conflicts become warnings while assess still lists them as conflicts.
- **Impact:** False sense of isolation safety under multi-agent dirty trees.
- **Fix:** Ownership conflicts block commit unless explicitly adopted.

### `scripts/rotate_google_token.py`

#### DR-8 - Revoke before obtaining replacement refresh token
- **Function:** `main` (~318-323)
- **Problem:** Valid access token is revoked before device-code flow completes for a new refresh token.
- **Impact:** Partial rotation; if OAuth fails, operator may be left mid-flow with confusing revoke messaging.
- **Fix:** Obtain + persist + test new refresh first; revoke old credentials last.

#### DR-9 - Non-atomic `.env` secret write
- **Function:** `write_env` (~68)
- **Problem:** Direct `Path.write_text` of secrets.
- **Impact:** Crash mid-write can corrupt `.env`.
- **Fix:** Write temp file + `os.replace`.

#### DR-10 - `test_token` passes empty `client_secret`
- **Function:** `test_token` (~169)
- **Evidence:** `refresh_token(client_id, "", refresh_token)`.
- **Impact:** False FAIL after successful rotation for confidential clients.
- **Fix:** Pass the real `client_secret`.

### `scripts/ai_os_claude_hook.py`

#### DR-11 - `handle_post_write` swallows all exceptions
- **Function:** `handle_post_write` (~196-203)
- **Problem:** Bare `except Exception: return 0`.
- **Impact:** Silent checkpoint drift after edits.
- **Fix:** Log to stderr; distinguish timeout vs hard failure.

#### DR-12 - Unknown commit-plan verdict falls through to close
- **Function:** `handle_task_completed` (~216-225)
- **Problem:** Only `COMMIT_READY`/`BLOCKED` are handled; missing/unknown verdict proceeds to `task-close --validate-only`.
- **Impact:** Damaged plan output can hide commit-plan failure.
- **Fix:** Default-deny unless verdict in known set and process rc==0.

### `scripts/dev-tooling/cbm_mcp_diagnose.py`

#### DR-13 - JSON-RPC read without request-id match / process poll
- **Function:** `read_json_line` (~57-69)
- **Problem:** First JSON line returned; notifications can be mistaken for tool results; dead process busy-waits.
- **Impact:** False diagnose results.
- **Fix:** Filter by `id`; check `proc.poll()`.

#### DR-14 - `stderr=PIPE` without drain
- **Function:** `timed_session` (~96-104)
- **Problem:** Unread stderr pipe can fill and deadlock the MCP child.
- **Impact:** Hung diagnose session.
- **Fix:** `DEVNULL`, reader thread, or bounded drain.

### `scripts/row4a_browser_proof.py`

#### DR-15 - Diagnostics written only on happy path
- **Function:** `main` (~272-284)
- **Problem:** `network.json` / console dumps occur after success path; early timeout/assert skips artifacts.
- **Impact:** Failed proofs lack the evidence needed to debug.
- **Fix:** Persist collected logs in `finally`.

#### DR-16 - Exit 0 despite failed semantic anchors
- **Function:** `main` (~261-262, return 0)
- **Problem:** `live_response_ok` and similar flags are recorded but not enforced as process failure.
- **Impact:** Green exit with red proof content.
- **Fix:** Fail when critical anchors are false.

### `scripts/ai_os_codex_hook.py`

#### DR-17 - Soft-miss policy diverges from Claude hook
- **Function:** `checkpoint_state` (~72-78)
- **Problem:** Multi-active / no-active task messaging is not mapped like Claude soft-miss; Claude blocks writes more aggressively.
- **Impact:** Inconsistent workspace protection across agent hosts.
- **Fix:** Share one soft/hard miss taxonomy.

#### DR-18 - Corrupt checkpoint: SessionStart continues, PreCompact stops
- **Functions:** `handle_session_start` (~158-159), PreCompact path (~182-183)
- **Problem:** Inconsistent severity for the same corrupt state.
- **Impact:** Session runs on broken checkpoint until compaction.
- **Fix:** Single policy (prefer stop/quarantine).

### `scripts/parse_transcript.py`

#### DR-19 - Hardcoded absolute transcript paths
- **Module constants** (~7-8)
- **Problem:** One-shot paths baked into source; no CLI args.
- **Impact:** Accidental run reads/writes unrelated session artifacts.
- **Fix:** Require argv paths; fail closed.

### `scripts/architecture-drift-check.py`

#### DR-20 - Declared architecture check is mostly markdown substring lint
- **Functions:** e.g. `check_api_ingress` (~59-68)
- **Problem:** Checks look for tokens like `ORPHANED` in docs rather than comparing code/MCP/runtime.
- **Impact:** Exit code gives false confidence of drift detection.
- **Fix:** Rename to artifact-lint or implement real code comparison.

#### DR-21 - `_git_diff` ignores returncode and does not drive verdict
- **Function:** `_git_diff` (~42-50)
- **Problem:** Git failures become empty lists; changed-file list is ornamental.
- **Impact:** Silent blind spots.
- **Fix:** Check `returncode`; use changed set or remove.

### `scripts/dev-tooling/cbm_index_repos.py`

#### DR-22 - `ROOT` resolves to `scripts/`, not workspace
- **Module** (~15)
- **Evidence:** `Path(__file__).resolve().parents[1]` from `scripts/dev-tooling/` -> `scripts/`.
- **Impact:** MCP cwd wrong vs `cbm_mcp_diagnose.py` (`parents[2]`); relative resolution drift.
- **Fix:** Use `parents[2]`.

#### DR-23 - `call_tool` drops `req_id` when reading response
- **Function:** `call_tool` (~51-61)
- **Problem:** `read_json_line(proc, timeout)` without `req_id=` even though reader supports it.
- **Impact:** Notifications can be treated as `index_repository` results.
- **Fix:** Pass `req_id=req_id`.

#### DR-24 - `stderr=PIPE` without drain + no cache lock
- **Function:** process spawn (~76-84) and index path
- **Problem:** Same stderr deadlock risk as diagnose; shared `CBM_CACHE_DIR` has no lock.
- **Impact:** Hang or corrupted CBM cache under parallel runs.
- **Fix:** Drain/DEVNULL + file lock around index.

## Vulture triage

| Symbol | Location | Verdict | Reason |
| --- | --- | --- | --- |
| `exc_type` | `ai_os_task.py:196`, `:1119` | **false positive** | Required unused args of `__exit__` protocol (`RegistryLock`, `RepoCommitLock`). |

Confirmed dead-code count used in ranking: **0** for all files.

## Scan limitations

- Tools were not preinstalled; installed for this scan: `ruff 0.16.1`, `radon 6.0.1`, `vulture 2.16`, `bandit 1.9.4` (Python 3.12.2).
- Initial PowerShell `>` redirection wrote UTF-16; scans were re-run with explicit UTF-8 writers. Final artifacts are UTF-8.
- `analyze_change_set(base_ref=main)` failed: `fatal: ambiguous argument 'main': unknown revision`. Retried successfully with `master`.
- `analyze_change_set` only scores files differing from `master`; unchanged scripts have CS Change = `N/A`.
- `code_health_score` returned **N/A** for `scripts/case_os_master_harness.py` and `scripts/check_latest_turns_v2.py` (tool: "Could not determine Code Health score.").
- Commanded `radon cc ... -n B` kept as `radon-cc.json`; table Max CC uses supplemental `radon-cc-full.json` (no `-n` filter) so every analyzable file has a numeric max. Files with no Radon blocks show `n/a`.
- Bandit totals include many LOW findings in tests (`assert_used`, `subprocess`); MEDIUM findings are mostly B310 urllib / B608 SQL string construction in ops scripts.
- `scripts/quality/` scan outputs excluded from the hotspot table to avoid self-scanning the report tree.
- Deep review is semantic judgment on top of tools; it does not replace Gate A/B runtime proof.

## Artifacts

| File | Role |
| --- | --- |
| `ruff.json` | Ruff E,F,W,B,C90,SIM,UP |
| `radon-cc.json` | Radon CC with `-n B` (as commanded) |
| `radon-cc-full.json` | Radon CC all ranks (table input) |
| `radon-mi.json` | Radon MI |
| `vulture.txt` / `vulture-triage.json` | Dead code + FP triage |
| `bandit.json` | Bandit |
| `codescene-health.json` | Per-file `code_health_score` |
| `codescene-change-set.json` | `analyze_change_set` vs master (scripts subset) |
| `hotspot-table.json` | Machine-readable ranked table |
| `scan-summary.json` | Intermediate aggregates |
| `REPORT.md` | This report |

