# Post-repair re-scan comparison — `scripts/`

Generated: 2026-08-03 (after commits `22b21ea`, `726abd4`, `15db2ae`/`4dddc78`)

Baseline scan: pre-repair hotspot table / CodeScene scores from the first session scan.
Rescan: fresh ruff/radon/vulture/bandit + CodeScene `code_health_score` + `analyze_change_set(base_ref=master)`.

## Headline

| Signal | Before | After | Delta |
| --- | ---: | ---: | --- |
| Ruff findings (scripts/, excl. quality) | 469 | 431 | -38 |
| Bandit findings (all severities) | 273 | 265 | -8 |
| Bandit MEDIUM/HIGH | 10 | **0** | -10 |
| Vulture hits (≥80%) | 2 | 1 | -1 (still FP: `__exit__` `exc_type`) |
| CodeScene `analyze_change_set` quality_gates | failed | **failed** | unchanged vs `master` |
| Top hotspot `ai_os_task.py` CS Health | 3.98 | **3.72** | -0.26 (worse) |
| Top hotspot `ai_os_task_ownership.py` CS Health | 6.74 | **6.31** | -0.43 (worse) |

**Verdict:** mechanical security/static debt improved (Bandit MEDIUM cleared; Ruff down). CodeScene **does not** show the AI-OS hotspots as “okay” — absolute Code Health on the critical files is flat-to-worse because correctness fixes added lock/guard complexity. `analyze_change_set` vs `master` still **fails** gates with mostly `degraded` on touched scripts (expected for a repair branch that grew LOC/CC versus old `master`).

## CodeScene health — former top-10 hotspots

| File | Before | After | Delta | Change-set vs master |
| --- | ---: | ---: | ---: | --- |
| `scripts/ai_os_task.py` | 3.98 | 3.72 | -0.26 | degraded |
| `scripts/ai_os_task_ownership.py` | 6.74 | 6.31 | -0.43 | degraded |
| `scripts/rotate_google_token.py` | 7.26 | 7.26 | 0.00 | (not listed / N/A in subset) |
| `scripts/ai_os_claude_hook.py` | 7.68 | 7.57 | -0.11 | degraded |
| `scripts/dev-tooling/cbm_mcp_diagnose.py` | 8.11 | 8.11 | 0.00 | degraded |
| `scripts/row4a_browser_proof.py` | 8.51 | 8.43 | -0.08 | degraded |
| `scripts/ai_os_codex_hook.py` | 8.59 | 8.59 | 0.00 | stable |
| `scripts/parse_transcript.py` | 8.85 | 8.83 | -0.02 | degraded |
| `scripts/dev-tooling/cbm_index_repos.py` | 8.95 | 8.79 | -0.16 | degraded |
| `scripts/architecture-drift-check.py` | 8.95 | 8.88 | -0.07 | degraded |

Notable positive change-set signal: `scripts/dev-tooling/test_ai_os_codex_hook.py` → **improved** (duplication fixed). Absolute score 9.38 → **10.0**.

## Interpretation (facts vs conclusions)

**Facts**

- Fresh deterministic scans completed; 38 Python files under `scripts/` (excl. `scripts/quality/`).
- CodeScene MCP invoked for per-file scores and branch change-set.
- Bandit MEDIUM/HIGH is now zero across `scripts/`.
- Hotspot Code Health scores remain Yellow/Red for AI-OS core files.

**Conclusions**

- Repair prioritized **correctness / concurrency / security**, not CodeScene smell minimization.
- Adding `FilePidLock`, commit finalize paths, and ownership guards increased cyclomatic complexity → CodeScene treats that as degradation vs `master`.
- “CodeScene okay” is **not** achieved for `ai_os_task.py` / ownership; further health gains need deliberate complexity extraction (separate from the correctness pass).

## Vulture triage (rescan)

| Symbol | Location | Verdict |
| --- | --- | --- |
| `exc_type` | `ai_os_task.py` `FilePidLock.__exit__` | false positive (`__exit__` protocol) |

## Scan limitations (this rescan)

- `analyze_change_set` compares current branch to `master`, not “pre-repair tip vs post-repair tip”; therefore degraded includes all unmerged work on the branch, not only the quality repair delta.
- `code_health_score` still **N/A** for `case_os_master_harness.py` and `check_latest_turns_v2.py`.
- Absolute health comparison uses the session’s first-scan `codescene-health` snapshot preserved as `codescene-health.before-repair.json`.

## Artifacts refreshed

- `ruff.json`, `radon-cc.json`, `radon-cc-full.json`, `radon-mi.json`, `vulture.txt`, `bandit.json`
- `codescene-health.json`, `codescene-change-set.json`
- `hotspot-table.before-repair.json` (frozen pre-repair ranking)
- `COMPARISON.md` (this file)
