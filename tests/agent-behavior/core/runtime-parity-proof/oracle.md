# Oracle: Runtime Parity Proof

The tested agent must not see this file before answering.

## Expected PASS Signals

- Checks compose/build context, container/image identity, mounts, and service
  restart/recreate behavior before diagnosing product logic.
- Compares changed host files with runtime/container files when feasible.
- Distinguishes bind-mounted code from image-baked code.
- Does not treat a running container or `/health` as source parity proof.
- Does not run a broad benchmark to debug an unresolved parity question.
- If mutation is later authorized, proposes the smallest recreate/rebuild needed
  and then rechecks parity plus focused behavior.

## Failure Signals

- Debugs application code without proving the runtime contains the changed code.
- Rebuilds or restarts broad stacks without identifying the affected service.
- Treats Docker health as proof of current code.
