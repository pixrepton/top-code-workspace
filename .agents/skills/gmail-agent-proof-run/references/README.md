# References — gmail-agent proof

- **Local commands:** [commands-and-local.md](commands-and-local.md)

## Gate A vs Gate B

| Gate  | Meaning in this workspace                                                  |
| ----- | -------------------------------------------------------------------------- |
| **A** | Repo tests, compileall, static checks, doctor with available deps          |
| **B** | Stack smoke: `preflight-local-stack`, Daszek/browser, cross-service health |

Never label **B** without the corresponding stack/runtime evidence.

## Proof labels (workspace)

- `confirmed by local tests` — Gate A green, Gate B not required
- `proven_local` — Gate A + Gate B green when B required
- `not proven` — missing Gate A or required Gate B
- `historical` — archival proof only

## Example report

```text
status: PASS | PARTIAL | FAIL

Gate A (gmail-agent):
- command: python -m pytest tools/gmail_audit/tests -q
- result: ...
- artifact: ...

Gate B (stack):
- status: not run | passed | failed
- command: pwsh -File scripts/preflight-local-stack.ps1 -FullStack
- evidence: ...

Not proven:
- ...
```

## Pointers

- `gmail-agent/docs/runbooks/LAST_PROVEN_STATE.md` (runtime claims only)
- `gmail-agent/AGENTS.md` verification section
- Root `.cursor/rules/92-proof-gate-discipline.mdc`
