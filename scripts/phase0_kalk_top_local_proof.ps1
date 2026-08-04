# Phase 0.4 — local KALK_TOP runtime proof
# Gate B adjunct: verifies host kalk-top :8091 and Node B doctor wiring.

param(
    [string]$KalkHealthUrl = 'http://127.0.0.1:8091/index.php?rest_route=/',
    [string]$GmailAgentDir = ''
)

$ErrorActionPreference = 'Stop'
$failures = @()

if (-not $GmailAgentDir) {
    $GmailAgentDir = Join-Path (Split-Path $PSScriptRoot -Parent) 'gmail-agent'
}

Write-Host "PHASE0 KALK_TOP proof"
Write-Host "health: $KalkHealthUrl"

try {
    $resp = Invoke-WebRequest -Uri $KalkHealthUrl -UseBasicParsing -TimeoutSec 15
    if ($resp.StatusCode -lt 200 -or $resp.StatusCode -ge 400) {
        $failures += "kalk-top health HTTP $($resp.StatusCode)"
    } else {
        Write-Host "kalk-top health: OK ($($resp.StatusCode))"
    }
} catch {
    $failures += "kalk-top health unreachable: $($_.Exception.Message)"
}

$composeFile = Join-Path $GmailAgentDir 'docker-compose.local-vps.yml'
if (Test-Path $composeFile) {
    $composeText = Get-Content $composeFile -Raw
    if ($composeText -notmatch 'KALK_TOP_BASE_URL:\s*http://host\.docker\.internal:8091') {
        $failures += 'docker-compose.local-vps.yml missing KALK_TOP_BASE_URL=http://host.docker.internal:8091'
    } else {
        Write-Host 'compose KALK_TOP_BASE_URL: OK'
    }
} else {
    $failures += "missing compose file: $composeFile"
}

$auditDir = Join-Path $GmailAgentDir 'tools\gmail_audit'
if (Test-Path $auditDir) {
    Push-Location $auditDir
    try {
        $doctor = python -c @"
from agent_runtime.settings import load_agent_runtime_settings
from agent_runtime.validate import build_agent_doctor_check
settings = load_agent_runtime_settings()
check = build_agent_doctor_check(settings)
url = str(settings.kalk_top_base_url or '').strip()
print('doctor_status', check.get('status'))
print('kalk_top_base_url', url or '<empty>')
warnings = check.get('warnings') or []
for w in warnings:
    if 'KALK_TOP' in w:
        print('warning', w)
"@
        Write-Host $doctor
    } finally {
        Pop-Location
    }
}

if ($failures.Count -gt 0) {
    Write-Host 'FAIL'
    $failures | ForEach-Object { Write-Host "- $_" }
    exit 1
}

Write-Host 'PASS phase0 kalk-top local proof'
exit 0
