# Gate A + Gate B local verification (no VPS)
param(
    [switch]$SkipTests,
    [switch]$CoreOnly
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

$root = $env:TOP_CODE_ROOT
$fail = 0

Write-Host '=== verify-local-gates ===' -ForegroundColor Cyan

$preflightArgs = @()
if (-not $CoreOnly) { $preflightArgs += '-FullStack' }

& (Join-Path $PSScriptRoot 'preflight-local-stack.ps1') @preflightArgs
$preflightExit = $LASTEXITCODE
if ($preflightExit -eq 1) {
    Write-Host '[FAIL] preflight hard failure (Docker)' -ForegroundColor Red
    exit 1
}
if ($preflightExit -eq 2) {
    Write-Host '[WARN] preflight FullStack partial — some services down' -ForegroundColor Yellow
}

if ($SkipTests) {
    Write-Host 'SkipTests set — preflight only' -ForegroundColor Yellow
    exit $preflightExit
}

# gmail-agent pytest (smoke subset if available)
$gaTests = Join-Path $root 'gmail-agent\tools\gmail_audit\tests'
if (Test-Path $gaTests) {
    Write-Host '--- gmail-agent pytest (quick) ---' -ForegroundColor Cyan
    Push-Location (Join-Path $root 'gmail-agent')
    python -m pytest tools/gmail_audit/tests/test_truth_flow_pr4_pr8.py tools/gmail_audit/tests/test_signal_reconciler_runtime.py -q --tb=line 2>&1
    if ($LASTEXITCODE -ne 0) { $fail++ }
    Pop-Location
}

# cieplo-orchestrator
$coRoot = Join-Path $root 'cieplo-orchestrator'
if (Test-Path (Join-Path $coRoot 'tests')) {
    Write-Host '--- cieplo-orchestrator pytest ---' -ForegroundColor Cyan
    Push-Location $coRoot
    python -m pytest tests -q --tb=line 2>&1
    if ($LASTEXITCODE -ne 0) { $fail++ }
    Pop-Location
}

# daszek JS syntax
$daszekApp = Join-Path $root 'daszek\public\app.js'
if (Test-Path $daszekApp) {
    Write-Host '--- daszek node --check ---' -ForegroundColor Cyan
    node --check $daszekApp 2>&1
    if ($LASTEXITCODE -ne 0) { $fail++ }
}

# kalk-top verify (optional — runtime may be off)
$ktPkg = Join-Path $root 'kalk-top\package.json'
if ((Test-Path $ktPkg) -and -not $CoreOnly) {
    Write-Host '--- kalk-top npm run verify (skip if runtime off) ---' -ForegroundColor Cyan
    Push-Location (Join-Path $root 'kalk-top')
    npm run verify 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[WARN] kalk-top verify failed — runtime may be off' -ForegroundColor Yellow
    }
    Pop-Location
}

if ($fail -gt 0) {
    Write-Host "[FAIL] verify-local-gates: $fail test suite(s) failed" -ForegroundColor Red
    exit 1
}

Write-Host '[OK] verify-local-gates complete' -ForegroundColor Green
exit 0
