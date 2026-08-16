# RAG V2 ephemeral data-plane proof (RAG-02 MinIO + RAG-04 Qdrant + bounded RAG-05 Temporal).
#
# Starts ephemeral Docker containers on host ports, installs host Python SDKs if missing,
# runs pytest live flags against rag-chat-asystent adapters, then always removes containers.
#
# HONESTY / BOUNDS:
# - Does NOT flip product live_data_plane (adapters/status.py stays False).
# - Does NOT change RAG_CORE / product cutover.
# - MinIO + Qdrant live tests exercise real put/get and upsert/search against ephemeral services.
# - Temporal live test WITHOUT RAG_V2_TEMPORAL_LIVE_WORKFLOW_ID only proves soft activation
#   (SDK present + host env). It does NOT start a workflow and does NOT require a worker.
#   That result is reported as PASS_BOUNDED (activation-only), not full durable-ingest proof.
# - Full RAG-12 Gate B (compose image /rag_v2/status, Node B, GraphStore, product stack)
#   remains a separate smoke: scripts/rag12-gate-b-rag-stack-smoke.ps1
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag_v2_ephemeral_data_plane_proof.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag_v2_ephemeral_data_plane_proof.ps1 -SkipTemporal
#
# Exit: 0 if MinIO+Qdrant live PASS; non-zero otherwise. Temporal bounded/skip does not fail the run.

param(
    [switch]$SkipTemporal,
    [int]$MinioPort = 9000,
    [int]$MinioConsolePort = 9001,
    [int]$QdrantPort = 6333,
    [int]$TemporalPort = 7233,
    [string]$ProofDir = '',
    [string]$PythonExe = 'python'
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

$ragRoot = $env:RAG_BACKEND_ROOT
if (-not $ragRoot) { $ragRoot = Join-Path $env:TOP_CODE_ROOT 'rag-chat-asystent' }

if (-not $ProofDir) {
    $scratch = if ($env:TOP_CODE_SESSION_SCRATCH) { $env:TOP_CODE_SESSION_SCRATCH } else { 'C:\top-code-session-scratch' }
    $ProofDir = Join-Path $scratch 'rag-v2-ephemeral-proof'
}
New-Item -ItemType Directory -Path $ProofDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMddTHHmmss'
$logFile = Join-Path $ProofDir "proof-$stamp.log"
$summaryJson = Join-Path $ProofDir "summary-$stamp.json"

function Write-Log {
    param([string]$Message, [string]$Color = 'Gray')
    $line = "[{0}] {1}" -f (Get-Date -Format 'o'), $Message
    Write-Host $line -ForegroundColor $Color
    Add-Content -LiteralPath $logFile -Value $line
}

function Test-Tcp {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 1500)
    $client = $null
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $iar = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($iar)
        return $true
    } catch { return $false }
    finally { if ($client) { $client.Close() } }
}

function Wait-Tcp {
    param([string]$HostName, [int]$Port, [int]$TimeoutSec = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Tcp -HostName $HostName -Port $Port -TimeoutMs 1000) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Get-DockerContainerId {
    param([object]$RawOutput)
    $text = if ($null -eq $RawOutput) { '' } elseif ($RawOutput -is [string]) { $RawOutput } else { ($RawOutput | ForEach-Object { "$_" }) -join "`n" }
    $lines = $text -split "`r?`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
    foreach ($line in ($lines | Select-Object -Last 8)) {
        if ($line -match '^[a-f0-9]{64}$') { return $Matches[0] }
        if ($line -match '^[a-f0-9]{12}$') { return $Matches[0] }
    }
    return $null
}

$minioId = $null
$qdrantId = $null
$temporalId = $null
$workerProc = $null
$minioStatus = 'FAIL'
$qdrantStatus = 'FAIL'
$temporalStatus = 'SKIPPED'
$packagesInstalled = @()
$pytestExit = -1
$commands = [System.Collections.Generic.List[string]]::new()
$gaps = [System.Collections.Generic.List[string]]::new()

try {
    Write-Log "Proof dir: $ProofDir" 'Cyan'
    Write-Log "RAG root: $ragRoot" 'Cyan'
    Write-Log "BOUNDS: live_data_plane NOT flipped; RAG_CORE NOT cut over; Temporal=activation-only unless workflow id set." 'Yellow'

    # Reuse compose/profile listeners when ports are already open.
    if (Test-Tcp -HostName '127.0.0.1' -Port $MinioPort) {
        Write-Log "MinIO port $MinioPort already open — reusing existing listener." 'Yellow'
        $minioId = '(pre-existing-listener)'
    } else {
        $minioName = "rag-v2-ephemeral-minio-$stamp"
        $minioCmd = "docker run -d --rm --name $minioName -p ${MinioPort}:9000 -p ${MinioConsolePort}:9001 -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin minio/minio:latest server /data --console-address :9001"
        $commands.Add("docker pull minio/minio:latest")
        $commands.Add($minioCmd)
        Write-Log "Pulling minio/minio:latest (if needed)" 'Cyan'
        docker pull minio/minio:latest | Out-Null
        Write-Log "Starting MinIO: $minioCmd" 'Cyan'
        $minioRaw = docker run -d --rm --name $minioName -p "${MinioPort}:9000" -p "${MinioConsolePort}:9001" -e MINIO_ROOT_USER=minioadmin -e MINIO_ROOT_PASSWORD=minioadmin minio/minio:latest server /data --console-address ':9001' 2>&1
        if ($LASTEXITCODE -ne 0) { throw "MinIO docker run failed (exit $LASTEXITCODE): $minioRaw" }
        $minioId = Get-DockerContainerId $minioRaw
        if (-not $minioId) { throw "MinIO container id not parsed from: $minioRaw" }
        Write-Log "MinIO container: $minioId" 'Green'
        if (-not (Wait-Tcp -HostName '127.0.0.1' -Port $MinioPort -TimeoutSec 45)) {
            throw "MinIO port $MinioPort not ready"
        }
    }

    if (Test-Tcp -HostName '127.0.0.1' -Port $QdrantPort) {
        Write-Log "Qdrant port $QdrantPort already open — reusing existing listener." 'Yellow'
        $qdrantId = '(pre-existing-listener)'
    } else {
        $qdrantName = "rag-v2-ephemeral-qdrant-$stamp"
        $qdrantCmd = "docker run -d --rm --name $qdrantName -p ${QdrantPort}:6333 -p 6334:6334 qdrant/qdrant:latest"
        $commands.Add("docker pull qdrant/qdrant:latest")
        $commands.Add($qdrantCmd)
        Write-Log "Pulling qdrant/qdrant:latest (if needed)" 'Cyan'
        docker pull qdrant/qdrant:latest | Out-Null
        Write-Log "Starting Qdrant: $qdrantCmd" 'Cyan'
        $qdrantRaw = docker run -d --rm --name $qdrantName -p "${QdrantPort}:6333" -p '6334:6334' qdrant/qdrant:latest 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Qdrant docker run failed (exit $LASTEXITCODE): $qdrantRaw" }
        $qdrantId = Get-DockerContainerId $qdrantRaw
        if (-not $qdrantId) { throw "Qdrant container id not parsed from: $qdrantRaw" }
        Write-Log "Qdrant container: $qdrantId" 'Green'
        if (-not (Wait-Tcp -HostName '127.0.0.1' -Port $QdrantPort -TimeoutSec 60)) {
            throw "Qdrant port $QdrantPort not ready"
        }
    }

    # --- optional Temporal (best-effort; activation-only pytest does not need a live server) ---
    $temporalReady = $false
    if (-not $SkipTemporal) {
        if (Test-Tcp -HostName '127.0.0.1' -Port $TemporalPort) {
            Write-Log "Temporal port $TemporalPort already open — will start worker for full LIVE_START when possible." 'Yellow'
            $temporalReady = $true
            $temporalId = '(pre-existing-listener)'
        } else {
            $temporalName = "rag-v2-ephemeral-temporal-$stamp"
            $temporalCmd = "docker run -d --rm --name $temporalName -p ${TemporalPort}:7233 temporalio/auto-setup:1.25.2"
            $commands.Add("docker pull temporalio/auto-setup:1.25.2")
            $commands.Add($temporalCmd)
            Write-Log "Starting Temporal (best-effort, 90s wait): $temporalCmd" 'Cyan'
            Write-Log "NOTE: pytest without RAG_V2_TEMPORAL_LIVE_WORKFLOW_ID is activation-only (PASS_BOUNDED)." 'Yellow'
            docker pull temporalio/auto-setup:1.25.2 2>&1 | Out-Null
            $temporalRaw = docker run -d --rm --name $temporalName -p "${TemporalPort}:7233" temporalio/auto-setup:1.25.2 2>&1
            $temporalId = Get-DockerContainerId $temporalRaw
            if ($LASTEXITCODE -eq 0 -and $temporalId) {
                Write-Log "Temporal container: $temporalId" 'Green'
                $temporalReady = Wait-Tcp -HostName '127.0.0.1' -Port $TemporalPort -TimeoutSec 90
                if (-not $temporalReady) {
                    Write-Log "Temporal port not ready in 90s — continuing; live test remains activation-only." 'Yellow'
                    $gaps.Add('Temporal container started but :7233 not ready within 90s')
                }
            } else {
                Write-Log "Temporal start skipped/failed quickly: $temporalRaw" 'Yellow'
                $gaps.Add("Temporal docker start failed or unavailable: $temporalRaw")
                $temporalId = $null
            }
        }
    } else {
        Write-Log "SkipTemporal set — Temporal container not started." 'Yellow'
    }

    # --- Python SDKs ---
    Write-Log "Ensuring host Python packages: minio, qdrant-client, temporalio" 'Cyan'
    $pipCheck = & $PythonExe -c "import importlib.util as u; print('minio', bool(u.find_spec('minio'))); print('qdrant', bool(u.find_spec('qdrant_client'))); print('temporalio', bool(u.find_spec('temporalio')))" 2>&1 | Out-String
    Write-Log $pipCheck.Trim()
    $need = @()
    if ($pipCheck -notmatch 'minio True') { $need += 'minio>=7.2.0' }
    if ($pipCheck -notmatch 'qdrant True') { $need += 'qdrant-client>=1.12.0' }
    if ($pipCheck -notmatch 'temporalio True') { $need += 'temporalio>=1.7.0' }
    if ($need.Count -gt 0) {
        $pipCmd = "$PythonExe -m pip install $($need -join ' ')"
        $commands.Add($pipCmd)
        Write-Log "Installing: $($need -join ', ')" 'Cyan'
        $pipLog = Join-Path $ProofDir "pip-$stamp.log"
        # Avoid PowerShell pipeline clobbering native exit codes: run pip, then verify imports.
        cmd /c "`"$PythonExe`" -m pip install $($need -join ' ') > `"$pipLog`" 2>&1"
        $pipExit = $LASTEXITCODE
        Write-Log "pip exit=$pipExit (log: $pipLog)"
        & $PythonExe -c "import minio, qdrant_client, temporalio; print('sdk_import_ok')" 2>&1 | ForEach-Object { Write-Log "$_" }
        if ($LASTEXITCODE -ne 0) {
            throw "SDK import failed after pip (pip exit=$pipExit). See $pipLog"
        }
        $packagesInstalled = $need
        Write-Log "pip install OK" 'Green'
    } else {
        Write-Log "All required SDKs already present" 'Green'
    }

    # --- MinIO bucket ---
    $bucketScript = @"
from minio import Minio
c = Minio('127.0.0.1:$MinioPort', access_key='minioadmin', secret_key='minioadmin', secure=False)
b = 'rag-v2'
if not c.bucket_exists(b):
    c.make_bucket(b)
    print('created', b)
else:
    print('exists', b)
"@
    $bucketPy = Join-Path $ProofDir "ensure_bucket_$stamp.py"
    Set-Content -LiteralPath $bucketPy -Value $bucketScript -Encoding UTF8
    $commands.Add("$PythonExe $bucketPy")
    Write-Log "Creating MinIO bucket rag-v2" 'Cyan'
    $bucketOut = & $PythonExe $bucketPy 2>&1 | Out-String
    $bucketExit = $LASTEXITCODE
    Write-Log $bucketOut.Trim()
    if ($bucketExit -ne 0 -or $bucketOut -notmatch 'created|exists') {
        throw "MinIO bucket create failed (exit=$bucketExit): $bucketOut"
    }

    # --- live env ---
    $env:RAG_V2_MINIO_LIVE = '1'
    $env:MINIO_ENDPOINT = "127.0.0.1:$MinioPort"
    $env:MINIO_ACCESS_KEY = 'minioadmin'
    $env:MINIO_SECRET_KEY = 'minioadmin'
    $env:MINIO_ROOT_USER = 'minioadmin'
    $env:MINIO_ROOT_PASSWORD = 'minioadmin'
    $env:MINIO_BUCKET = 'rag-v2'
    $env:MINIO_SECURE = '0'

    $env:RAG_V2_QDRANT_LIVE = '1'
    $env:RAG_V2_QDRANT_URL = "http://127.0.0.1:$QdrantPort"
    $env:QDRANT_URL = "http://127.0.0.1:$QdrantPort"

    $env:RAG_V2_TEMPORAL_LIVE = '1'
    $env:RAG_V2_TEMPORAL_HOST = "127.0.0.1:$TemporalPort"
    $env:TEMPORAL_HOST = "127.0.0.1:$TemporalPort"
    Remove-Item Env:RAG_V2_TEMPORAL_LIVE_WORKFLOW_ID -ErrorAction SilentlyContinue

    $workerProc = $null
    $workerOut = Join-Path $ProofDir "temporal-worker-$stamp.out.log"
    $workerErr = Join-Path $ProofDir "temporal-worker-$stamp.err.log"
    if (-not $SkipTemporal -and $temporalReady) {
        Write-Log "Starting Temporal worker (RAG-05 full start_ingest proof)" 'Cyan'
        $env:RAG_V2_TEMPORAL_LIVE_START = '1'
        try {
            $workerProc = Start-Process -FilePath $PythonExe -ArgumentList @(
                '-m', 'rag_v2.adapters.temporal_worker'
            ) -WorkingDirectory (Join-Path $ragRoot 'backend') -PassThru -NoNewWindow `
                -RedirectStandardOutput $workerOut -RedirectStandardError $workerErr
            Start-Sleep -Seconds 4
            if ($workerProc.HasExited) {
                Write-Log "Temporal worker exited early — falling back to activation-only" 'Yellow'
                Get-Content -LiteralPath $workerErr -ErrorAction SilentlyContinue | Select-Object -Last 20 | ForEach-Object { Write-Log $_ 'Yellow' }
                Remove-Item Env:RAG_V2_TEMPORAL_LIVE_START -ErrorAction SilentlyContinue
                $workerProc = $null
            } else {
                Write-Log "Temporal worker pid=$($workerProc.Id)" 'Green'
            }
        } catch {
            Write-Log "Temporal worker start failed: $($_.Exception.Message) — activation-only" 'Yellow'
            Remove-Item Env:RAG_V2_TEMPORAL_LIVE_START -ErrorAction SilentlyContinue
            $workerProc = $null
        }
    } else {
        Remove-Item Env:RAG_V2_TEMPORAL_LIVE_START -ErrorAction SilentlyContinue
    }

    Write-Log "ENV: RAG_V2_MINIO_LIVE=1 MINIO_ENDPOINT=$($env:MINIO_ENDPOINT) MINIO_BUCKET=rag-v2" 'Cyan'
    Write-Log "ENV: RAG_V2_QDRANT_LIVE=1 RAG_V2_QDRANT_URL=$($env:RAG_V2_QDRANT_URL)" 'Cyan'
    Write-Log "ENV: RAG_V2_TEMPORAL_LIVE=1 RAG_V2_TEMPORAL_HOST=$($env:RAG_V2_TEMPORAL_HOST) LIVE_START=$($env:RAG_V2_TEMPORAL_LIVE_START)" 'Cyan'

    $pytestArgs = @(
        '-m', 'pytest',
        'backend/tests/test_rag_v2_minio_adapter.py::test_live_minio_put_get_checksum',
        'backend/tests/test_rag_v2_qdrant_adapter.py::test_live_qdrant_upsert_search_fusion',
        'backend/tests/test_rag_v2_temporal_adapter.py::test_live_temporal_start_ingest',
        '-v', '--tb=short'
    )
    $commands.Add("cd $ragRoot; $PythonExe $($pytestArgs -join ' ')")
    Write-Log "Running live pytest from $ragRoot" 'Cyan'
    Push-Location $ragRoot
    try {
        $pytestLog = Join-Path $ProofDir "pytest-$stamp.log"
        & $PythonExe @pytestArgs 2>&1 | Tee-Object -FilePath $pytestLog
        $pytestExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    $pytestText = Get-Content -LiteralPath (Join-Path $ProofDir "pytest-$stamp.log") -Raw -ErrorAction SilentlyContinue
    if ($pytestText -match 'test_live_minio_put_get_checksum\s+PASSED') { $minioStatus = 'PASS' }
    elseif ($pytestText -match 'test_live_minio_put_get_checksum\s+SKIPPED') { $minioStatus = 'SKIPPED' }
    elseif ($pytestText -match 'test_live_minio_put_get_checksum\s+FAILED') { $minioStatus = 'FAIL' }

    if ($pytestText -match 'test_live_qdrant_upsert_search_fusion\s+PASSED') { $qdrantStatus = 'PASS' }
    elseif ($pytestText -match 'test_live_qdrant_upsert_search_fusion\s+SKIPPED') { $qdrantStatus = 'SKIPPED' }
    elseif ($pytestText -match 'test_live_qdrant_upsert_search_fusion\s+FAILED') { $qdrantStatus = 'FAIL' }

    if ($pytestText -match 'test_live_temporal_start_ingest\s+PASSED') {
        if ($env:RAG_V2_TEMPORAL_LIVE_START -and $env:RAG_V2_TEMPORAL_LIVE_START.ToLower() -in @('1','true','yes','on')) {
            $temporalStatus = 'PASS'
            Write-Log "Temporal live: PASS (worker + start_ingest)." 'Green'
        } else {
            $temporalStatus = 'PASS_BOUNDED'
            Write-Log "Temporal live: PASS_BOUNDED (activation-only; no worker/workflow mutation)." 'Yellow'
        }
    }
    elseif ($pytestText -match 'test_live_temporal_start_ingest\s+SKIPPED') { $temporalStatus = 'SKIPPED' }
    elseif ($pytestText -match 'test_live_temporal_start_ingest\s+FAILED') { $temporalStatus = 'FAIL' }

    $gaps.Add('Not full RAG-12 Gate B: no compose image rebuild, no /rag_v2/status via product container, no Node B / GraphStore / RAG /health matrix')
    $gaps.Add('live_data_plane remains False by design (product cutover not in scope)')
    $gaps.Add('Temporal: no registered worker, no start_ingest mutation, no workflow status round-trip')
    if (-not $temporalReady -and -not $SkipTemporal) {
        $gaps.Add('Temporal server TCP may be down; activation-only test does not require TCP connect')
    }

} catch {
    Write-Log "FATAL: $($_.Exception.Message)" 'Red'
    $gaps.Add("Fatal: $($_.Exception.Message)")
} finally {
    if ($workerProc -and -not $workerProc.HasExited) {
        Write-Log "Stopping Temporal worker pid=$($workerProc.Id)" 'Cyan'
        try { Stop-Process -Id $workerProc.Id -Force -ErrorAction SilentlyContinue } catch {}
    }
    Write-Log "Cleaning up ephemeral containers..." 'Cyan'
    foreach ($pair in @(
        @{id=$minioId; name='minio'},
        @{id=$qdrantId; name='qdrant'},
        @{id=$temporalId; name='temporal'}
    )) {
        if ($pair.id -and $pair.id -ne '(pre-existing-listener)') {
            $short = (($pair.id -split '\s+')[0]).Trim()
            if ($short -match '^[a-f0-9]{12,}') {
                Write-Log "docker rm -f $short ($($pair.name))" 'Gray'
                # Containers started with --rm may already be gone; never fail the proof on cleanup.
                try {
                    docker rm -f $short 2>$null | Out-Null
                } catch {
                    Write-Log "Cleanup note $($pair.name): already removed or missing" 'Gray'
                }
            }
        }
    }
}

$summary = [ordered]@{
    stamp              = $stamp
    proof_dir          = $ProofDir
    minio_live         = $minioStatus
    qdrant_live        = $qdrantStatus
    temporal_live      = $temporalStatus
    temporal_note      = 'PASS_BOUNDED means soft activation (SDK+host env) only; no worker/workflow proof'
    container_ids      = @{
        minio    = $minioId
        qdrant   = $qdrantId
        temporal = $temporalId
    }
    packages_installed = $packagesInstalled
    pytest_exit_code   = $pytestExit
    commands           = @($commands)
    gaps_vs_rag12      = @($gaps)
    constraints_honored = @(
        'Did not flip live_data_plane to True',
        'Did not change RAG_CORE off legacy',
        'Used docker run ephemeral (no docker cp)'
    )
}

$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryJson -Encoding UTF8

Write-Host ''
Write-Host '======== RAG V2 EPHEMERAL DATA PLANE PROOF ========' -ForegroundColor Cyan
Write-Host ("MinIO live:     {0}" -f $minioStatus)
Write-Host ("Qdrant live:    {0}" -f $qdrantStatus)
Write-Host ("Temporal live:  {0}" -f $temporalStatus)
Write-Host ("MinIO CID:      {0}" -f $minioId)
Write-Host ("Qdrant CID:     {0}" -f $qdrantId)
Write-Host ("Temporal CID:   {0}" -f $temporalId)
Write-Host ("Summary JSON:   {0}" -f $summaryJson)
Write-Host ("Log:            {0}" -f $logFile)
Write-Host '==================================================='

if (($minioStatus -ne 'PASS') -or ($qdrantStatus -ne 'PASS')) { exit 1 }
exit 0
