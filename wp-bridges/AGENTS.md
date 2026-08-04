# AGENTS.md — wp-bridges

Status: **Typ B — root-owned folder** (not an independent Git repository).

## Role

Thin local WordPress bridge surface (Node A) for integration-seam audit and PHP verification.

## Rules

- Commit / branch / `ai_os_task` scope: repo **`workspace`**, path `wp-bridges/...`
- Ecosystem rules: `../AGENTS.md` (L1)
- Case/decision semantics: `../gmail-agent`
- Operator UI: `../daszek`
- Default: local-only — not an automatic production WP deploy surface

## Gate

```powershell
php -l path\to\changed-file.php
```

Run `php -l` on each PHP file you changed. Add contract/smoke checks when the change is an integration seam, not for docs-only stubs.

## Anti-goals

- Second case SoT or memory-bank here
- Independent Git lifecycle for this folder
- Domain Case OS logic living only in bridges
