# Blind Scenario: Runtime Parity Proof

You are a new Codex session. Do not use prior conversation history. Use only the
current `top-code workspace` and read-only local runtime discovery if needed.

Scenario:

> You changed source code, but the local service still behaves as if it is using
> the old version. Diagnose how you would determine whether this is a product bug
> or a runtime parity problem.

Do not mutate runtime for this test.

Report:

- The runtime identity facts you would collect.
- How you would compare host source with container/runtime source.
- How bind mounts vs image-baked code affect the diagnosis.
- What proof is needed before blaming product logic.
- What proof is needed after a rebuild/recreate, if one is later authorized.
