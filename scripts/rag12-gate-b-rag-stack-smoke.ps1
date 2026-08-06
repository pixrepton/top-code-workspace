# RAG-12 - bounded Gate B RAG stack smoke (NOT full ecosystem Gate B).
#
# Probes what is actually up locally:
#   required: Docker, Node B /health, RAG /health, GraphStore Postgres :54130
#   surface:  GET /rag_v2/status (RAG-14 adapter checklist) - host fallback if image stale
#   optional: MinIO :9000, Qdrant :6333, Temporal :7233  -> honest SKIP when down
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag12-gate-b-rag-stack-smoke.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag12-gate-b-rag-stack-smoke.ps1 -RequireLiveAdapters
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag12-gate-b-rag-stack-smoke.ps1 -ManifestPath .artifacts/rag12-manifest.json
#
# Exit codes:
#   0 = PASS (required green; optional may SKIP)
#   2 = PARTIAL (required green, but /rag_v2/status HTTP missing or RequireLiveAdapters unmet)
#   1 = FAIL (required component down)

param(
    [string]$RagBaseUrl = 'http://127.0.0.1:8000',
    [string]$NodeBBaseUrl = '',
    [int]$GraphStorePort = 54130,
    [int]$MinioPort = 9000,
    [int]$QdrantPort = 6333,
    [int]$TemporalPort = 7233,
    [string]$ManifestPath = '',
    [switch]$RequireLiveAdapters,
    [switch]$SkipHostStatusFallback
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

if (-not $NodeBBaseUrl) {
    $nodebPort = 8766
    $vpsEnv = Join-Path $env:TOP_CODE_ROOT 'gmail-agent\.env.vps'
    if (Test-Path -LiteralPath $vpsEnv) {
        $portLine = Get-Content $vpsEnv | Where-Object { $_ -match '^GMAIL_AGENT_NODEB_PORT=' } | Select-Object -First 1
        if ($portLine -match '^GMAIL_AGENT_NODEB_PORT=(\d+)') { $nodebPort = [int]$Matches[1] }
    }
    $NodeBBaseUrl = "http://127.0.0.1:$nodebPort"
}

if (-not $ManifestPath) {
    $artifacts = Join-Path $env:TOP_CODE_ROOT '.artifacts'
    if (-not (Test-Path -LiteralPath $artifacts)) {
        New-Item -ItemType Directory -Path $artifacts -Force | Out-Null
    }
    $stamp = Get-Date -Format 'yyyyMMddTHHmmssZ'
    $ManifestPath = Join-Path $artifacts "rag12-gate-b-smoke-$stamp.json"
}

$matrix = [System.Collections.Generic.List[object]]::new()
$startedAt = (Get-Date).ToUniversalTime().ToString('o')

function Add-Row {
    param(
        [string]$Component,
        [string]$Role,          # required | optional | surface
        [string]$Status,        # PASS | FAIL | SKIP | INACTIVE | PARTIAL
        [string]$Detail,
        [object]$Evidence = $null
    )
    $row = [ordered]@{
        component = $Component
        role      = $Role
        status    = $Status
        detail    = $Detail
        evidence  = $Evidence
    }
    $matrix.Add([pscustomobject]$row) | Out-Null
    $color = switch ($Status) {
        'PASS' { 'Green' }
        'FAIL' { 'Red' }
        'SKIP' { 'Yellow' }
        'INACTIVE' { 'DarkYellow' }
        'PARTIAL' { 'Yellow' }
        default { 'Gray' }
    }
    Write-Host ("[{0}] {1} ({2}): {3}" -f $Status, $Component, $Role, $Detail) -ForegroundColor $color
}

function Test-TcpFast {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 1500)
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false
        }
        $client.EndConnect($iar)
        return $true
    }
    catch {
        return $false
    }
    finally {
        if ($client) { $client.Close() }
    }
}

function Invoke-JsonGet {
    param([string]$Url, [int]$TimeoutSec = 8)
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        $body = $resp.Content
        $json = $null
        try { $json = $body | ConvertFrom-Json } catch {}
        return @{
            ok         = ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400)
            statusCode = [int]$resp.StatusCode
            body       = $body
            json       = $json
            error      = $null
        }
    }
    catch {
        $code = $null
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $code = [int]$_.Exception.Response.StatusCode
        }
        return @{
            ok         = $false
            statusCode = $code
            body       = $null
            json       = $null
            error      = $_.Exception.Message
        }
    }
}

Write-Host 'RAG-12 bounded Gate B RAG stack smoke' -ForegroundColor Cyan
Write-Host "TOP_CODE_ROOT=$env:TOP_CODE_ROOT"
Write-Host "rag=$RagBaseUrl  node_b=$NodeBBaseUrl"
Write-Host "RequireLiveAdapters=$RequireLiveAdapters"
Write-Host ''

# --- Docker ---
$dockerOk = $false
try {
    docker version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $dockerOk = $true }
}
catch {}
if ($dockerOk) {
    Add-Row -Component 'docker' -Role 'required' -Status 'PASS' -Detail 'Docker Desktop available'
}
else {
    Add-Row -Component 'docker' -Role 'required' -Status 'FAIL' -Detail 'Docker Desktop not available'
}

# --- Node B ---
$nodeb = Invoke-JsonGet -Url "$NodeBBaseUrl/health"
if ($nodeb.ok) {
    $svc = if ($nodeb.json) { $nodeb.json.service } else { $null }
    Add-Row -Component 'node_b' -Role 'required' -Status 'PASS' -Detail ("HTTP {0} {1}/health service={2}" -f $nodeb.statusCode, $NodeBBaseUrl, $svc) -Evidence @{ url = "$NodeBBaseUrl/health"; status_code = $nodeb.statusCode }
}
else {
    Add-Row -Component 'node_b' -Role 'required' -Status 'FAIL' -Detail ("unreachable {0}/health: {1}" -f $NodeBBaseUrl, $nodeb.error) -Evidence @{ url = "$NodeBBaseUrl/health"; status_code = $nodeb.statusCode; error = $nodeb.error }
}

# --- RAG API health ---
$ragHealth = Invoke-JsonGet -Url "$RagBaseUrl/health"
$ragHealthOk = $false
if ($ragHealth.ok -and $ragHealth.json -and $ragHealth.json.status) {
    $st = [string]$ragHealth.json.status
    $eng = [string]$ragHealth.json.engine
    $ragHealthOk = ($st -eq 'healthy' -or $st -eq 'degraded') -and $eng
    $detail = "status=$st engine=$eng index_ready=$($ragHealth.json.index_ready) storage=$($ragHealth.json.storage_backend)"
    if ($ragHealthOk) {
        Add-Row -Component 'rag_api' -Role 'required' -Status 'PASS' -Detail $detail -Evidence @{
            url             = "$RagBaseUrl/health"
            status_code     = $ragHealth.statusCode
            status          = $st
            engine          = $eng
            storage_backend = [string]$ragHealth.json.storage_backend
            has_rag_v2_key  = [bool]($ragHealth.json.PSObject.Properties.Name -contains 'rag_v2')
        }
    }
    else {
        Add-Row -Component 'rag_api' -Role 'required' -Status 'FAIL' -Detail $detail -Evidence @{ url = "$RagBaseUrl/health"; status_code = $ragHealth.statusCode }
    }
}
else {
    Add-Row -Component 'rag_api' -Role 'required' -Status 'FAIL' -Detail ("unreachable {0}/health: {1}" -f $RagBaseUrl, $ragHealth.error) -Evidence @{ url = "$RagBaseUrl/health"; status_code = $ragHealth.statusCode; error = $ragHealth.error }
}

# --- GraphStore Postgres (compose: graphstore-postgres) ---
if (Test-TcpFast -HostName '127.0.0.1' -Port $GraphStorePort) {
    Add-Row -Component 'postgres_graphstore' -Role 'required' -Status 'PASS' -Detail "TCP 127.0.0.1:$GraphStorePort open (hvac-graphstore-postgres)" -Evidence @{ host = '127.0.0.1'; port = $GraphStorePort }
}
else {
    Add-Row -Component 'postgres_graphstore' -Role 'required' -Status 'FAIL' -Detail "TCP 127.0.0.1:$GraphStorePort closed - start rag-chat-asystent docker compose" -Evidence @{ host = '127.0.0.1'; port = $GraphStorePort }
}

# --- Optional live data-plane listeners ---
function Add-OptionalTcp {
    param([string]$Name, [int]$Port, [string]$Hint)
    $open = Test-TcpFast -HostName '127.0.0.1' -Port $Port
    if ($open) {
        Add-Row -Component $Name -Role 'optional' -Status 'PASS' -Detail "TCP 127.0.0.1:$Port open" -Evidence @{ host = '127.0.0.1'; port = $Port }
        return $true
    }
    $status = if ($RequireLiveAdapters) { 'FAIL' } else { 'SKIP' }
    Add-Row -Component $Name -Role 'optional' -Status $status -Detail ("TCP 127.0.0.1:{0} closed - {1}" -f $Port, $Hint) -Evidence @{ host = '127.0.0.1'; port = $Port }
    return $false
}

$minioLive = Add-OptionalTcp -Name 'minio' -Port $MinioPort -Hint 'RAG-02 live blob not required for COMPLETE_BOUNDED; no invent of full MinIO stack'
$qdrantLive = Add-OptionalTcp -Name 'qdrant' -Port $QdrantPort -Hint 'RAG-04 live hybrid index not required; no invent of Qdrant'
$temporalLive = Add-OptionalTcp -Name 'temporal' -Port $TemporalPort -Hint 'RAG-05 durable ingest not required; no invent of Temporal'

# --- RAG-14 /rag_v2/status surface ---
$statusUrl = "$RagBaseUrl/rag_v2/status"
$ragStatus = Invoke-JsonGet -Url $statusUrl
$adapterPayload = $null
$statusSource = $null

if ($ragStatus.ok -and $ragStatus.json) {
    $adapterPayload = $ragStatus.json
    $statusSource = 'http'
    Add-Row -Component 'rag_v2_status' -Role 'surface' -Status 'PASS' -Detail ("HTTP {0} rag_core={1} activated_count={2}/{3} live_data_plane={4}" -f `
            $ragStatus.statusCode, $adapterPayload.rag_core, $adapterPayload.activated_count, $adapterPayload.adapter_count, $adapterPayload.live_data_plane) `
        -Evidence @{ url = $statusUrl; source = 'http'; status_code = $ragStatus.statusCode; payload = $adapterPayload }
}
else {
    $why = if ($ragStatus.statusCode) { "HTTP $($ragStatus.statusCode)" } else { $ragStatus.error }
    if ($SkipHostStatusFallback) {
        Add-Row -Component 'rag_v2_status' -Role 'surface' -Status 'FAIL' -Detail ("$why - host fallback disabled; rebuild rag-backend image to ship RAG-14") -Evidence @{ url = $statusUrl; status_code = $ragStatus.statusCode; error = $ragStatus.error }
    }
    else {
        # Strongest local proof without inventing services: probe soft-activation on host tree.
        $backendDir = Join-Path $env:TOP_CODE_ROOT 'rag-chat-asystent\backend'
        $probeFile = Join-Path $env:TEMP ("rag12-status-probe-{0}.py" -f [guid]::NewGuid().ToString('N'))
        @(
            'import json, sys'
            ('sys.path.insert(0, r"{0}")' -f $backendDir.Replace('\', '\\'))
            'from rag_v2.adapters.status import collect_rag_v2_adapter_status'
            'print(json.dumps(collect_rag_v2_adapter_status(), ensure_ascii=True))'
        ) | Set-Content -LiteralPath $probeFile -Encoding ASCII
        $prevPyPath = $env:PYTHONPATH
        $env:PYTHONPATH = $backendDir
        try {
            $raw = & python $probeFile 2>&1 | Out-String
            $exit = $LASTEXITCODE
        }
        finally {
            if ($null -eq $prevPyPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $prevPyPath }
            Remove-Item -LiteralPath $probeFile -Force -ErrorAction SilentlyContinue
        }
        $text = if ($raw) { $raw.Trim() } else { '' }
        if ($exit -eq 0 -and $text) {
            try {
                # Prefer last JSON object line (ignore any warnings on stdout).
                $jsonLine = ($text -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') } | Select-Object -Last 1)
                if (-not $jsonLine) { $jsonLine = $text }
                $adapterPayload = $jsonLine | ConvertFrom-Json
                $statusSource = 'host_python_fallback'
                Add-Row -Component 'rag_v2_status' -Role 'surface' -Status 'PARTIAL' -Detail ("HTTP missing ($why); host fallback OK rag_core=$($adapterPayload.rag_core) activated=$($adapterPayload.activated_count)/$($adapterPayload.adapter_count) - rebuild rag-backend for live HTTP") `
                    -Evidence @{ url = $statusUrl; http_status_code = $ragStatus.statusCode; source = 'host_python_fallback'; payload = $adapterPayload }
            }
            catch {
                Add-Row -Component 'rag_v2_status' -Role 'surface' -Status 'FAIL' -Detail ("HTTP missing ($why); host fallback JSON parse failed: $text") -Evidence @{ url = $statusUrl; error = "$text" }
            }
        }
        else {
            Add-Row -Component 'rag_v2_status' -Role 'surface' -Status 'FAIL' -Detail ("HTTP missing ($why); host fallback failed: $text") -Evidence @{ url = $statusUrl; http_status_code = $ragStatus.statusCode; error = "$text" }
        }
    }
}

# Per-adapter soft-activation rows (from status payload when available)
if ($adapterPayload -and $adapterPayload.adapters) {
    foreach ($a in $adapterPayload.adapters) {
        $name = [string]$a.name
        $activated = [bool]$a.activated
        $rid = [string]$a.roadmap_id
        $reason = [string]$a.inactive_reason
        $liveOpen = switch ($name) {
            'minio' { $minioLive }
            'qdrant' { $qdrantLive }
            'temporal' { $temporalLive }
            default { $null }
        }
        if ($activated) {
            $detail = "soft-activated ($rid) source=$statusSource"
            if ($null -ne $liveOpen -and -not $liveOpen) {
                $detail += ' - config/SDK ready but live TCP listener SKIP/absent'
            }
            Add-Row -Component ("adapter_$name") -Role 'optional' -Status 'PASS' -Detail $detail -Evidence $a
        }
        else {
            Add-Row -Component ("adapter_$name") -Role 'optional' -Status 'INACTIVE' -Detail ("$rid inactive: $reason (source=$statusSource)") -Evidence $a
        }
    }
}

# --- Verdict ---
$requiredFail = @($matrix | Where-Object { $_.role -eq 'required' -and $_.status -eq 'FAIL' })
$surfaceFail = @($matrix | Where-Object { $_.component -eq 'rag_v2_status' -and $_.status -eq 'FAIL' })
$surfacePartial = @($matrix | Where-Object { $_.component -eq 'rag_v2_status' -and $_.status -eq 'PARTIAL' })
$optionalFail = @($matrix | Where-Object { $_.role -eq 'optional' -and $_.status -eq 'FAIL' })

$verdict = 'PASS'
$exitCode = 0
if ($requiredFail.Count -gt 0 -or $surfaceFail.Count -gt 0) {
    $verdict = 'FAIL'
    $exitCode = 1
}
elseif (
    $surfacePartial.Count -gt 0 -or
    $optionalFail.Count -gt 0 -or
    ($RequireLiveAdapters -and (-not $minioLive -or -not $qdrantLive -or -not $temporalLive))
) {
    $verdict = 'PARTIAL'
    $exitCode = 2
}

$endedAt = (Get-Date).ToUniversalTime().ToString('o')
$manifest = [ordered]@{
    roadmap_id           = 'RAG-12'
    title                = 'Formal live Gate B RAG stack smoke (bounded)'
    not_full_ecosystem   = $true
    started_at_utc       = $startedAt
    ended_at_utc         = $endedAt
    verdict              = $verdict
    exit_code            = $exitCode
    require_live_adapters = [bool]$RequireLiveAdapters
    endpoints            = [ordered]@{
        rag_health      = "$RagBaseUrl/health"
        rag_v2_status   = $statusUrl
        node_b_health   = "$NodeBBaseUrl/health"
    }
    live_tcp             = [ordered]@{
        postgres_graphstore = $GraphStorePort
        minio               = $MinioPort
        qdrant              = $QdrantPort
        temporal            = $TemporalPort
    }
    matrix               = @($matrix | ForEach-Object {
            [ordered]@{
                component = $_.component
                role      = $_.role
                status    = $_.status
                detail    = $_.detail
            }
        })
    notes                = @(
        'COMPLETE_BOUNDED / shadow vertical - live data plane (MinIO/Qdrant/Temporal).',
        'SKIP on optional listeners is expected when those stacks are not running.',
        'rag_v2_status PARTIAL means host PYTHONPATH fallback - rebuild/recreate rag-backend for HTTP RAG-14.'
    )
}

$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ManifestPath -Encoding UTF8

Write-Host ''
Write-Host "VERDICT: $verdict (exit $exitCode)" -ForegroundColor $(if ($verdict -eq 'PASS') { 'Green' } elseif ($verdict -eq 'PARTIAL') { 'Yellow' } else { 'Red' })
Write-Host "Manifest: $ManifestPath"
Write-Host ''
Write-Host 'Per-service matrix:' -ForegroundColor Cyan
$matrix | ForEach-Object {
    '{0,-22} {1,-10} {2}' -f $_.component, $_.status, $_.role
} | Write-Host

exit $exitCode
