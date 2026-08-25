# AI-OS Agent Behavior Regression Suite

Status: initial CORE suite.

This suite tests agent behavior, not product behavior. It is designed to check
whether a new cold-start agent can recover AI-OS operating knowledge from the
workspace and reason with the right evidence discipline.

## Structure

Each test case has two files:

- `scenario.md` - the blind prompt given to the tested agent.
- `oracle.md` - the rubric used by the evaluator. The tested agent must not read
  this before producing its answer.

Do not merge scenario and oracle content. A scenario that contains the expected
answer is not a valid cold-start behavior test.

## Execution Protocol

1. Start a fresh or context-isolated agent session.
2. Give it only the target `scenario.md` plus the instruction to use the current
   `top-code workspace`.
3. Forbid production mutation unless the scenario explicitly says otherwise.
4. Require the agent to cite workspace sources for concrete facts.
5. After the agent answers, compare its response to `oracle.md`.
6. Record `PASS`, `PARTIAL`, or `FAIL`, plus the main failure mode.

## Core Cases

| Case | Competency |
| --- | --- |
| `source-of-truth-boundary` | Recovers ownership and producer/consumer boundaries from workspace. |
| `git-dirty-state-ownership` | Preserves nested repo boundaries and foreign dirty state. |
| `evidence-strength` | Separates test, runtime, deployment, operator, and business proof. |
| `mcp-tool-availability` | Distinguishes configured tools from session-proven callable tools. |
| `runtime-parity-proof` | Proves host/container/source parity before diagnosing runtime behavior. |
| `memory-writeback-discipline` | Writes durable knowledge only to canonical owners and avoids transcript dumps. |
| `measurement-integrity` | Keeps focused proof, frozen measurement, and capability claims separate. |
| `unknown-uncertainty-handling` | Says `UNKNOWN` when current proof is missing and describes how to discover it. |

## Non-Goals

- These files are not product Gate A tests.
- They do not replace owner repo tests or runtime proof.
- They are not a prompt cookbook for normal work.
- They must not contain secrets, customer data, or production credentials.

