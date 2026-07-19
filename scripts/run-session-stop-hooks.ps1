# Run session-end hooks manually.
# Writes only scratch closeout data; no repo-local memory store.
param(
    [string]$TranscriptPath = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1')

$root = $env:TOP_CODE_ROOT
if (-not $root) { throw 'TOP_CODE_ROOT not set (run via resolve-paths.ps1).' }

$stdinObj = @{
    manual          = $true
    status          = 'completed'
    loop_count      = 0
    conversation_id = 'manual-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
}
if ($TranscriptPath) { $stdinObj.transcript_path = $TranscriptPath }

$stdin = $stdinObj | ConvertTo-Json -Compress
$hooks = @('session-stop-arch-refresh.js')

Write-Host 'Session closeout hooks (manual)' -ForegroundColor Cyan
foreach ($hook in $hooks) {
    $hookPath = Join-Path (Join-Path $root '.cursor\hooks') $hook
    if (-not (Test-Path $hookPath)) {
        Write-Warning "Missing: $hookPath"
        continue
    }
    Write-Host "  -> $hook" -ForegroundColor Gray
    $stdin | node $hookPath
}

$scratchDir = $env:TOP_CODE_SESSION_SCRATCH
if (-not $scratchDir) { $scratchDir = 'C:\top-code-session-scratch' }
Write-Host "Done. Log: $(Join-Path $scratchDir 'SESSION_CLOSEOUT.log')" -ForegroundColor Green
