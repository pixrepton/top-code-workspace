# Blind Scenario: Source Of Truth Boundary

You are a new Codex session. Do not use prior conversation history. Use only the
current `top-code workspace`, its instructions, skills, source files, Git state,
and read-only discovery.

Scenario:

> A generated offer PDF shows an incorrect price. Determine where you should
> look for the root cause and which part of the system owns that logic. Do not
> make changes.

Report:

- The routing path you used.
- The ownership you established.
- The producer/consumer chain.
- Workspace sources for every concrete fact.
- What remains unknown without runtime discovery.

Do not infer ownership from the place where the symptom appears.

