# CLAUDE.md - thin router

This file is a router, not policy.
Read root `AGENTS.md` first.
Use `knowledge/INDEX.md` for cold-start and knowledge routing.
For repo work, read the target repo `AGENTS.md` and only the routed local docs.
Repo-local `CLAUDE.md` files are adapters only and do not outrank `AGENTS.md`.

Claude Code lifecycle enforcement is configured in `.claude/settings.json` and
uses the same `scripts/ai_os_task.py` checkpoint, ownership, branch and commit
engine as Codex. Do not create a separate Claude-only Git workflow.
