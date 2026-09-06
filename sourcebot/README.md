# Sourcebot Local

Local, read-only Sourcebot setup for `top-code workspace`.

Run:

```powershell
docker compose -f docker-compose.sourcebot-local.yml up -d
python scripts/dev-tooling/sourcebot_smoke.py --write-artifact --allow-auth-required
```

Notes:

- Sourcebot mounts the workspace at `/repos/top-code:ro`.
- It is intentionally not registered as an MCP server in the free baseline.
- Sourcebot MCP is documented by Sourcebot as paid-plan only; use the web UI/API as cited structural search, not product runtime proof.
- Telemetry is disabled with `SOURCEBOT_TELEMETRY_DISABLED=true`.
- `/api/search` can return `401` until an operator creates/logs into the local owner account or provides `SOURCEBOT_API_KEY`.
