---
name: agent-skill-quality-gate
description: Use when creating, editing, or reviewing workspace Agent Skills — activation triggers, description quality, SKILL.md length, references split, registry entry, and avoiding router bloat.
---

# Agent Skill Quality Gate

Source: adapted from `gmail-agent-legacy@f83845d`.

## Use When

- Creating, editing, or reviewing `.agents/skills/*`.
- Checking descriptions, activators, non-goals, references, or length.

## Do Not Use When

- Using an existing skill without changing it.

## Rules

- Descriptions must be specific enough to trigger only when relevant.
- `SKILL.md` concise; deep material in `references/`.
- Each skill: use, non-use, procedure, validation, report.
- Skills cannot weaken root `AGENTS.md`, SoT boundaries, or proof discipline.
- Cross-repo skills live at workspace `.agents/skills/` unless truly repo-only.

## Checklist

1. Frontmatter `name` and `description` present.
2. Concrete use / non-use cases.
3. No duplication of full Cursor rules.
4. Registered in `knowledge/system-atlas/tooling/agent-harness/AGENT_SKILLS_REGISTRY.md`.
5. Listed in `AGENT_HARNESS_MANIFEST.yaml` if core skill.
6. Workspace bindings section when paths differ from legacy monolith.
7. No stale monolith paths (`memory-bank`, embedded `Daszek/`).

## Validation

```powershell
python scripts/agent_harness_audit.py
python scripts/context_link_audit.py --scope workspace
```

## Report

- Skill name.
- Pass/fail per checklist item.
- Registry/manifest updated: yes/no.
