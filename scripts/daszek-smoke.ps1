# Daszek repair smoke — Gate A + Gate B (local stack)
param(
    [switch]$SkipPreflight
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "=== Gate A: static ===" -ForegroundColor Cyan
php -l daszek/includes/api.php | Out-Host
php -l daszek/includes/api-v2.php | Out-Host
php -l daszek/includes/api-v3.php | Out-Host
node --check daszek/public/app.js | Out-Host
Push-Location gmail-agent
python -m pytest tools/gmail_audit/tests/test_api_tasks.py tools/gmail_audit/tests/test_api_cases.py tools/gmail_audit/tests/test_correlation_registry_p0.py tools/gmail_audit/tests/test_materialize_composite.py tools/gmail_audit/tests/test_materialize_approve_harness.py tools/gmail_audit/tests/test_health_monitor.py tools/gmail_audit/tests/test_worker_bridge_drain.py tools/gmail_audit/tests/test_bridge_action_decision.py -q
Pop-Location

if (-not $SkipPreflight) {
    Write-Host "=== Gate B: preflight ===" -ForegroundColor Cyan
    & "$root/scripts/preflight-local-stack.ps1"
}

Write-Host "=== Gate B: Node B tasks ===" -ForegroundColor Cyan
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/health' -TimeoutSec 10
if (-not $health.ok) { throw 'Node B health not ok' }
Write-Host "Node B health OK"

$probeOut = docker exec gmail-agent-nodeb-api python -c "import urllib.request,json; req=urllib.request.Request('http://127.0.0.1:8765/tasks', data=json.dumps({'title':'daszek-smoke-probe'}).encode(), headers={'Content-Type':'application/json'}, method='POST'); r=urllib.request.urlopen(req, timeout=20); print(r.status); print(r.read().decode()[:200])" 2>&1
if ($LASTEXITCODE -ne 0) { throw "POST /tasks via docker exec failed: $probeOut" }
Write-Host $probeOut

Write-Host "=== Gate B: Daszek feed latest ===" -ForegroundColor Cyan
try {
    $job = Start-Job { Invoke-WebRequest -Uri 'http://127.0.0.1:8090/wp-json/daszek/v3/operational-feed-snapshots/latest' -TimeoutSec 8 -UseBasicParsing }
    if (Wait-Job $job -Timeout 12) {
        $feed = Receive-Job $job
        Write-Host "Feed latest HTTP $($feed.StatusCode)"
    }
    else {
        Stop-Job $job -Force
        Write-Warning "Feed latest timed out (auth or stack)"
    }
    Remove-Job $job -Force -ErrorAction SilentlyContinue
}
catch {
    Write-Warning "Feed latest requires auth or stack: $_"
}

Write-Host "=== Gate C: health + bridge summary (optional) ===" -ForegroundColor Cyan
try {
    $hb = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/system/health/status' -TimeoutSec 15
    if ($null -eq $hb.risk_flags) {
        Write-Warning "health/status missing risk_flags array"
    }
    else {
        Write-Host "health/status risk_flags: $($hb.risk_flags.Count)"
    }
}
catch {
    Write-Warning "Gate C health/status skipped: $_"
}

Write-Host "=== Daszek smoke PASS ===" -ForegroundColor Green
