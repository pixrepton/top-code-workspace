---
name: policy-action-gates
description: Use when implementing or auditing policy_engine, DecisionCandidate, PolicyDecision, APv2 intent, ToolPlan, HITL, reply drafts, send/archive actions, cooldowns, or execution permissions in gmail-agent.
---

# Policy Action Gates

Source: adapted from `gmail-agent-legacy@f83845d`.

## Use When

- Policy engine, action proposals, drafts, send/archive/delete, cooldowns, approval rules.
- AI-OS pipeline: DecisionCandidate → PolicyDecision → APv2 → ToolPlan → execution → HITL.

## Do Not Use When

- Passive classification or projection with no action/policy decision.

## Model (current)

```text
DecisionCandidate
  → PolicyDecision
  → APv2 intent
  → ToolPlan
  → APv1 / materialized execution
  → HITL when required
  → ExecutionResult
```

## Rules

- Do not relax policy gates silently.
- Separate recommendation, draft, approval, and execution.
- Destructive or external actions need explicit policy and proof.
- Unknown policy status is an alarm in runtime proof.
- `/tasks*` write routes remain fail-closed.

## Checklist

1. Identify action class and risk.
2. Confirm approval/HITL requirement.
3. Confirm cooldown/idempotency (`decision_key`, idempotency keys).
4. Add tests for allow/block/unknown paths.
5. Gate A: targeted pytest in `tools/gmail_audit/tests/`.

## Report

- Action class.
- Gate decision.
- Tests run.
- Residual risk.
- SoT: Node B only — Daszek does not execute policy.
