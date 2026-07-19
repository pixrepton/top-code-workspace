# Run session-start hooks manually (operator: "uruchom hooki startu sesji").
# Writes SESSION_START_CONTEXT.md to TOP_CODE_SESSION_SCRATCH or C:\top-code-session-scratch.
param()

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1')

$root = $env:TOP_CODE_ROOT
if (-not $root) { throw 'TOP_CODE_ROOT not set (run via resolve-paths.ps1).' }

$stdinObj = @{
    manual          = $true
    loop_count      = 0
    conversation_id = 'manual-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
}
$stdin = $stdinObj | ConvertTo-Json -Compress

function Get-HookFollowupMessage {
    param(
        [string]$HookPath,
        [string]$StdinJson
    )
    if (-not (Test-Path $HookPath)) {
        return $null
    }
    $raw = $StdinJson | node $HookPath 2>$null
    if (-not $raw) { return $null }
    try {
        $parsed = $raw.Trim() | ConvertFrom-Json
        if ($parsed.followup_message) {
            return [string]$parsed.followup_message
        }
    }
    catch {
        return $null
    }
    return $null
}

$hooksDir = Join-Path $root '.cursor\hooks'
$hookSpecs = @(
    @{ File = 'session-start-inject.js'; Section = 'Memory inject' }
    @{ File = 'session-start-arch-check.js'; Section = 'Arch check' }
)

$generatedAt = (Get-Date).ToUniversalTime().ToString('o')
$sections = @(
    '# Session start context',
    '',
    "Generated: $generatedAt",
    'Mode: manual',
    ''
)

$logLines = @("## $generatedAt")

Write-Host 'Session start hooks (manual)' -ForegroundColor Cyan
foreach ($spec in $hookSpecs) {
    $hookPath = Join-Path $hooksDir $spec.File
    if (-not (Test-Path $hookPath)) {
        Write-Warning "Missing: $hookPath"
        $sections += @("## $($spec.Section)", '', '(hook missing)', '')
        $logLines += "[start] MISSING: $($spec.File)"
        continue
    }
    Write-Host "  -> $($spec.File)" -ForegroundColor Gray
    $message = Get-HookFollowupMessage -HookPath $hookPath -StdinJson $stdin
    $sections += @("## $($spec.Section)", '')
    if ($message) {
        $sections += $message.Split("`n")
        $logLines += "[start] OK: $($spec.File)"
    }
    else {
        $sections += '(no data)'
        $logLines += "[start] EMPTY: $($spec.File)"
    }
    $sections += ''
}

$scratchDir = $env:TOP_CODE_SESSION_SCRATCH
if (-not $scratchDir) { $scratchDir = 'C:\top-code-session-scratch' }
if (-not (Test-Path $scratchDir)) {
    New-Item -ItemType Directory -Path $scratchDir -Force | Out-Null
}

$contextPath = Join-Path $scratchDir 'SESSION_START_CONTEXT.md'
$logPath = Join-Path $scratchDir 'SESSION_START.log'

Set-Content -Path $contextPath -Value ($sections -join "`n") -Encoding UTF8
Add-Content -Path $logPath -Value (($logLines -join "`n") + "`n")

Write-Host "Done. Context: $contextPath" -ForegroundColor Green
Write-Host "Log: $logPath" -ForegroundColor Green
