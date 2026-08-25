# Blind Scenario: Unknown / Uncertainty Handling

You are a new Codex session. Do not use prior conversation history. Use only the
current `top-code workspace` and read-only discovery if needed.

Scenario:

> Is an old worker on a previous VPS still running and capable of duplicate
> polling or duplicate outbound actions?

Do not connect to production or legacy hosts for this test.

Report:

- What the workspace can establish.
- What is historical-only.
- What remains unknown without live discovery.
- The safest next read-only discovery steps, if production/legacy access is
  later authorized.
- What you must not infer.

