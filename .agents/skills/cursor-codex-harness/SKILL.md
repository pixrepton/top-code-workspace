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

## Execution / Proof Ladder

Use the lowest proof tier that can answer the current question.

### FAST

Use during diagnosis and implementation.

Prefer:

- source/static inspection;
- focused deterministic tests;
- stubs/fakes;
- controlled synthetic inputs;
- the smallest relevant regression.

FAST should answer whether the implementation or hypothesis is plausible before paying for live qualification.

### FOCUSED

Use when behavior crosses a real integration boundary that FAST cannot prove.

Prefer:

- one focused integration test;
- one contract boundary;
- one minimal live dependency when required.

Do not expand to a broad suite merely because the focused test is green.

### LIVE_DISCRIMINATING

Use one live case when the unresolved question depends on real runtime behavior.

A live case must have a specific hypothesis.

Before running it, state:

```text
HYPOTHESIS =
CHEAPEST_DISCRIMINATING_EXPERIMENT =
EXPECTED_EVIDENCE_IF_TRUE =
EXPECTED_EVIDENCE_IF_FALSE =
```

Do not rerun the same expensive live case with the same setup after failure.

A new run requires a new hypothesis, implementation change, controlled variable, or materially different evidence requirement.

### BOUNDED_QUALIFICATION

Use a small representative set only after the focused/live proof is green.

The bounded set is a qualification gate, not a debugging loop.

### FULL_QUALIFICATION

Use only after all cheaper required gates are green.

Full qualification is final evidence.

It is not the default mechanism for discovering root cause.

## Long-Running Jobs

When a command is expected to outlive the coding-agent command transport:

- launch it once with durable identity;
- persist PID or job identity;
- persist stdout/stderr or structured status;
- persist final result/exit state;
- do not restart it merely because the foreground agent command timed out;
- do not treat transport timeout as process failure;
- avoid frequent manual polling;
- inspect status at the coarsest interval justified by the expected state transition;
- prefer an existing completion/result signal when available.

Do not build a new job-runner service solely to satisfy this rule.

Use the simplest existing mechanism that provides durable identity and result.

## Time-Based Tests

Do not use real wall-clock waiting in deterministic tests when the condition under test can be injected, triggered, stubbed, or simulated.

Avoid development-loop patterns such as:

- `sleep 60`
- `sleep 180`
- `sleep 300`
- wait for real 15-minute timeout

when elapsed real time is not itself the subject of qualification.

Real long-duration waiting is acceptable only in an explicitly live/certification proof where actual elapsed behavior is part of the claim.

## Expensive Run Preflight

Before starting an expensive live experiment, cheaply verify:

- command parsing;
- argument binding;
- quoting;
- required environment;
- output path;
- process launch;
- trivial/stub invocation when practical.

Do not discover launcher mistakes after beginning a multi-minute qualification run.

## Validation

Harness docs/rules:

```powershell
python scripts/agent_harness_audit.py
python scripts/context_link_audit.py --scope workspace
```

Application changes: domain skill tests + repo Gate A from root `AGENTS.md`.

## Checklist

Before an expensive command, ask:

- What exactly am I trying to prove?
- Do I already have that evidence?
- What is the cheapest experiment that can distinguish the current hypotheses?
- Am I escalating proof because it is required, or only because it is available?
- Am I about to repeat a long run without any new information?
