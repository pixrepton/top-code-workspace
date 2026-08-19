# Sync CLAUDE.md pointer from canonical AGENTS.md (preserves gitnexus block only).

param(
    [string]$Root = $env:TOP_CODE_ROOT
)

$ErrorActionPreference = 'Stop'
if (-not $Root) {
    $Root = Split-Path -Parent $PSScriptRoot
}

$agentsPath = Join-Path $Root 'AGENTS.md'
$claudePath = Join-Path $Root 'CLAUDE.md'

if (-not (Test-Path -LiteralPath $agentsPath)) {
    throw "Missing AGENTS.md at $agentsPath"
}

$agents = Get-Content -LiteralPath $agentsPath -Raw -Encoding UTF8
$match = [regex]::Match($agents, '(<!-- gitnexus:start -->[\s\S]*?<!-- gitnexus:end -->)')
if (-not $match.Success) {
    throw 'AGENTS.md missing gitnexus:start/end block'
}

$header = @'
# CLAUDE.md — TOP-INSTAL Workspace Router (pointer)

Status: **not the canonical L1 constitution** — read [AGENTS.md](AGENTS.md) first for all workspace rules, task/Git control, proof gates, and memory policy.

This file exists for Claude Code discovery. Regenerate with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/sync-l1-router.ps1
```

'@

$newClaude = $header + "`n" + $match.Value + "`n"
[System.IO.File]::WriteAllText($claudePath, $newClaude)
Write-Host "Updated $claudePath from AGENTS.md gitnexus block" -ForegroundColor Green
