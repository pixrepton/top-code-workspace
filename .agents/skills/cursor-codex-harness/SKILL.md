---
name: cursor-codex-harness
description: Use when creating Cursor/Codex execution briefs, read orders, Definition of Done, anti-drift instructions, validation commands, or evidence-first reports in top-code workspace.
---

# Cursor / Codex Harness

Source: adapted from `gmail-agent-legacy@f83845d`.

## Use When

- Writing implementation prompts, task specs, or handoff prompts.
- Defining read order, Definition of Done, validation commands, or final report format.
- Auditing agent workflow and anti-drift instructions.

## Do Not Use When

- A domain skill already covers execution and no prompt design is needed.

## Workspace bindings

- Constitution: root `AGENTS.md`
- Harness index: `knowledge/system-atlas/tooling/agent-harness/AGENT_DEVELOPMENT_HARNESS.md`
- Task/git: `scripts/ai_os_task.py` per `knowledge/system-atlas/tooling/GIT_AND_CHANGE_CONTROL.md`
- Default runtime: local Docker only unless operator overrides

## Autonomy

- Continue through ordinary technical decisions without operator checkpoints.
- Stop only for: business/policy choice, external activation (VPS/prod/customer mail), irreversible risk, or missing secrets.
- Do not stop between normal implementation steps to ask permission.

## Prompt contract

Every serious implementation prompt should include:

- goal
- scope and non-goals
- read order (max 8-12 sources)
- likely files/repos
- architecture constraints (SoT boundaries)
- Definition of Done
- validation commands (Gate A minimum)
- evidence-first report format

## Anti-patterns

- "Read/review everything" without a reason.
- Pasting full history or doc trees into context.
- Duplicating skill bodies into Cursor rules.
- Claiming runtime proof from a plan or MCP output.

## Minimal procedure

1. Classify task domain and owning repo(s).
2. Pick 1-3 skills from `AGENT_SKILLS_REGISTRY.md`.
3. Start or resume `ai_os_task` checkpoint for MEDIUM+ writes.
4. Write scoped reads and stop conditions.
5. Attach commands that prove the change class.
6. Close with PASS/PARTIAL/FAIL and proof labels.

## Validation

Harness docs/rules:

```powershell
python scripts/agent_harness_audit.py
python scripts/context_link_audit.py --scope workspace
```

Application changes: domain skill tests + repo Gate A from root `AGENTS.md`.
