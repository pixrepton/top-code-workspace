# Push RAG system_health snapshot to Daszek + emit rag.kb_health.snapshot (W3 cron/harness).
# Usage: pwsh -File scripts/push-rag-system-health.ps1
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

function Read-EnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) { return '' }
    foreach ($line in Get-Content $Path) {
        if ($line -match "^$([regex]::Escape($Key))=(.*)$") { return $Matches[1].Trim() }
    }
    return ''
}

$nodebPort = 8766
$gmailRoot = Join-Path $env:TOP_CODE_ROOT 'gmail-agent'
$ragRoot = Join-Path $env:TOP_CODE_ROOT 'rag-chat-asystent'
$localVps = Join-Path $gmailRoot '.env.local-vps'
$auditEnv = Join-Path $gmailRoot 'tools\gmail_audit\.env'

$token = Read-EnvValue $localVps 'NODE_B_REGISTRY_TOKEN'
if (-not $token) { $token = Read-EnvValue $auditEnv 'NODE_B_REGISTRY_TOKEN' }
if (-not $token) { throw 'NODE_B_REGISTRY_TOKEN not found — run scripts/sync-local-stack-env.ps1 first' }

$env:RAG_BASE_URL = 'http://127.0.0.1:8000'
$env:DASZEK_BASE_URL = 'http://127.0.0.1:8090'
$env:NODE_B_REGISTRY_BASE_URL = "http://127.0.0.1:$nodebPort"
$env:NODE_B_REGISTRY_TOKEN = $token
$env:DASZEK_BRIDGE_TOKEN = $token

$push = Join-Path $ragRoot 'scripts\push_system_health_snapshot.py'
if (-not (Test-Path $push)) { throw "Missing $push" }

Write-Host "Pushing RAG system_health snapshot (Daszek + Node B os_event)..."
& python $push
if ($LASTEXITCODE -ne 0) { throw "push_system_health_snapshot failed (exit $LASTEXITCODE)" }
Write-Host 'OK push-rag-system-health'
