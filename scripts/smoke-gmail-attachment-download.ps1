# Gate B: bounded proof for GET /cases/{case_id}/attachments/{attachment_ref} @ Node B :8766
param(
    [string]$BaseUrl = 'http://127.0.0.1:8766',
    [string]$OutFile = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

$gaRoot = $env:GMAIL_AGENT_ROOT
$envFile = Join-Path $gaRoot '.env.local-vps'
if (-not (Test-Path $envFile)) {
    $envFile = Join-Path $gaRoot 'tools\gmail_audit\.env'
}
if (-not (Test-Path $envFile)) {
    Write-Error "Missing gmail-agent env file (.env.local-vps or tools/gmail_audit/.env)"
}

function Get-EnvValue([string]$path, [string]$key) {
    foreach ($line in Get-Content $path) {
        if ($line -match "^\s*$key\s*=\s*(.+)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return ''
}

$token = Get-EnvValue $envFile 'NODE_B_REGISTRY_TOKEN'
if (-not $token) { $token = Get-EnvValue $envFile 'DASZEK_BRIDGE_TOKEN' }
if (-not $token) { Write-Error 'NODE_B_REGISTRY_TOKEN (or DASZEK_BRIDGE_TOKEN) not set in env file' }

Write-Host '=== smoke-gmail-attachment-download ===' -ForegroundColor Cyan
Write-Host "Preflight: $BaseUrl/health"
try {
    $health = Invoke-RestMethod -Uri "$BaseUrl/health" -TimeoutSec 10
} catch {
    Write-Error "Node B API not reachable at $BaseUrl - start gmail-agent docker stack"
}
$healthLabel = if ($health.status) { $health.status } elseif ($health.healthy) { $health.healthy } else { 'ok' }
Write-Host "Health: $healthLabel"

$finder = Join-Path $PSScriptRoot 'smoke-gmail-attachment-find-case.py'
$foundJson = python $finder 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Attachment lookup failed: $foundJson"
}
$found = $foundJson | ConvertFrom-Json
if ($found.error) { Write-Error $found.error }

$caseId = $found.case_id
$ref = $found.attachment_ref
$url = "$BaseUrl/cases/$caseId/attachments/$ref"
Write-Host "Download: case=$caseId ref=$ref file=$($found.file_name)"

if (-not $OutFile) {
    $OutFile = Join-Path $env:TEMP "gmail-att-smoke-$caseId.bin"
}
$headers = @{ Authorization = "Bearer $token" }
Invoke-WebRequest -Uri $url -Headers $headers -OutFile $OutFile -TimeoutSec 120 | Out-Null
$bytes = (Get-Item $OutFile).Length
Write-Host "HTTP 200, bytes=$bytes, out=$OutFile" -ForegroundColor Green
if ($bytes -le 0) { Write-Error 'Empty attachment body' }
Write-Host 'SMOKE_GMAIL_ATTACHMENT_DOWNLOAD_OK'
exit 0
