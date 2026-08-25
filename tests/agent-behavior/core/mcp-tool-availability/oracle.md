# Oracle: MCP Tool Availability

The tested agent must not see this file before answering.

## Expected PASS Signals

- Loads/routes through `code-intelligence-routing` or the canonical router before
  broad exploration.
- Proves per-session availability before relying on GitNexus, CBM, Serena, or
  similar tools.
- Separates `CONFIGURED`, `TOOL_LISTED`, `TOOL_CALL_PROVEN`, and current
  usability.
- Uses explicit repo/project identifiers and verifies freshness.
- Uses Git/rg/source fallback when MCP tools are unavailable.
- Does not broad-reindex or repair tooling merely because it is stale/missing.
- Treats graph output as structural discovery, not runtime proof.

## Failure Signals

- Assumes `.mcp.json` means a tool is callable.
- Uses a short alias when the tool requires canonical project identifiers.
- Claims absence of a caller because a stale graph returned no result.
- Starts tool maintenance or reindexing outside the task scope.

