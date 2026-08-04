# Green CodeScene status — `scripts/`

Generated: 2026-08-03 after SCRIPTS-GREEN-QUALITY-1

## Goal

CodeScene Code Health **≥ 9.0** (Green/Optimal) for production Python under `scripts/` (excl. `scripts/quality/` tooling).

## Gate A

```text
python -m pytest scripts/dev-tooling -q
→ 85 passed, 3 skipped
```

Label: `confirmed by local tests`

## Hotspot outcomes (former Red/Yellow)

| File                          |        Before |    After |
| ----------------------------- | ------------: | -------: |
| `ai_os_task.py`               |          3.72 |  **9.5** |
| `ai_os_task_ownership.py`     |          6.31 | **9.68** |
| `ai_os_task_commit.py`        | (in monolith) | **10.0** |
| `ai_os_task_lifecycle.py`     | (in monolith) | **10.0** |
| `ai_os_task_gates.py`         | (in monolith) | **10.0** |
| `ai_os_task_state.py`         | (in monolith) | **9.38** |
| `rotate_google_token.py`      |          7.26 | **10.0** |
| `ai_os_claude_hook.py`        |          7.57 | **10.0** |
| `ai_os_codex_hook.py`         |          8.59 | **9.38** |
| `cbm_mcp_diagnose.py`         |          8.11 | **10.0** |
| `row4a_browser_proof.py`      |          8.43 | **10.0** |
| `parse_transcript.py`         |          8.83 | **10.0** |
| `architecture-drift-check.py` |          8.88 | **10.0** |

## Method

Karpathy surgical extraction: split cohesive modules, break Complex Method / Bumpy Road / Large Method, preserve CLI and soft-ownership warning contract.

## N/A CodeScene

`ai_os_task_constants.py`, `ai_os_task_errors.py` — tool could not score (data/exception-only modules). Treated as non-blocking.

## Soft-ownership

Unchanged: owned path conflict with successful isolated states → **warning**, not hard BLOCK.
