---
name: gmail-agent-proof-run
description: Node B gmail-agent intake, workers, doctor, replay, Daszek bridge, policy, Gate A/B in local Docker. Use for runtime or deployment claims in gmail-agent. Not for pure Node A UI without Node B claim.
---

# gmail-agent Proof Run

Source: adapted from `gmail-agent-legacy@f83845d`.

## Use When

- Auditing or running Node B intake, workers, doctor, replay, bridge drain, policy.
- Classifying or collecting Gate A vs Gate B evidence.
- Verifying local Docker stack health for gmail-agent changes.

## Do Not Use When

- Pure Daszek styling with no Node B runtime claim.

## STOP

- Do not claim live/VPS success without explicit operator scope (local-only default).
- Do not paste `.env`, keys, or full customer bodies.
- Stop replay cohort if runbook says halt on unexplained `unknown`.

## Workspace bindings

- Repo root: `gmail-agent/`
- Gate A: `python -m pytest tools/gmail_audit/tests -q` (from `gmail-agent/`)
- Stack preflight: `pwsh -File scripts/preflight-local-stack.ps1` (workspace root)
- Full gates: `pwsh -File scripts/verify-local-gates.ps1`
- VPS/prod: explicit operator request only

## Non-negotiables

- Node B is operational SoT for cases and execution.
- Keep local, fixture, Docker, and operator proof **separate** in reports.
- Image-baked code requires rebuild/recreate before runtime claims.

## Expand

- Commands and proof storage: [references/commands-and-local.md](references/commands-and-local.md)
- Gate framing: [references/README.md](references/README.md)

## Report (minimal)

- Ran: commands + environment intent.
- Result: pass/fail/skipped + artifact paths.
- Not proven: external or operator gaps.
- Label: `confirmed by local tests` / `proven_local` / `not proven` / `historical`
