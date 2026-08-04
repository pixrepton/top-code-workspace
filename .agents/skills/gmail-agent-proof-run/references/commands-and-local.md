# Commands and local Docker proof

Use after reading the root `SKILL.md` STOP/forbidden section.

## Workspace preflight (from repo root)

```powershell
pwsh -File scripts/preflight-local-stack.ps1
pwsh -File scripts/preflight-local-stack.ps1 -FullStack
pwsh -File scripts/verify-local-gates.ps1
```

## Gate A (from `gmail-agent/`)

```powershell
python -m compileall tools/gmail_audit scripts -q
python -m pytest tools/gmail_audit/tests -q --tb=line
python tools/gmail_audit/gmail_intake.py doctor --skip-gmail --verbose
```

## Docker (image-baked code)

If behavior depends on container image, rebuild and recreate before claiming runtime proof. See workspace `36-docker-procedure.mdc`.

## Proof storage

- Record command, cwd, environment intent, artifact path.
- Do not rely on terminal scrollback.
- Use workspace scratch or task checkpoint artifacts when appropriate.

## VPS / production

Explicit operator request only. Default workspace mandate is local Docker.

## More

- [README.md](README.md) — Gate A/B framing and report template.
