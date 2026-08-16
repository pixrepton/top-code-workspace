# RAG V2 live cutover Gate B harness (compose profile rag-v2-data-plane).
#
# Brings up the RAG V2 data-plane stack, waits for health, generates a real
# multi-page PDF with a table, then runs host-side Python proof:
#   ingest_pdf_bytes_live -> live vertical retrieve -> optional Temporal
#   start_ingest -> restart rag-v2-ingest-worker -> re-query Qdrant.
#
# HONESTY / BOUNDS:
# - Does NOT flip RAG_CORE=v2 globally (product default stays legacy).
# - Does NOT perform staged product cutover / dual-read cutover gates.
# - Sets RAG_V2_LIVE_DATA_PLANE=1 / RAG_V2_LIVE_INGEST=1 only for this host
#   proof process (and via compose override for containers when already set).
# - Full product answer-path cutover remains a separate operator decision.
# - Companion: rag-chat-asystent/backend/scripts/rag_v2_live_cutover_proof.py
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag_v2_live_cutover_gate_b.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag_v2_live_cutover_gate_b.ps1 -SkipBuild
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/rag_v2_live_cutover_gate_b.ps1 -SkipTemporal -SkipRestart
#
# Exit: 0 = PASS, non-zero = FAIL

param(
    [string]$RagBaseUrl = 'http://127.0.0.1:8000',
    [int]$GraphStorePort = 54130,
    [int]$MinioPort = 9000,
    [int]$QdrantPort = 6333,
    [int]$TemporalPort = 7233,
    [string]$ProofDir = '',
    [string]$SummaryDir = '',
    [string]$PythonExe = 'python',
    [switch]$SkipBuild,
    [switch]$SkipUp,
    [switch]$SkipTemporal,
    [switch]$SkipRestart,
    [string]$WorkerContainer = 'hvac-rag-v2-ingest-worker'
)

$ErrorActionPreference = 'Continue'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

$ragRoot = $env:RAG_BACKEND_ROOT
if (-not $ragRoot) { $ragRoot = Join-Path $env:TOP_CODE_ROOT 'rag-chat-asystent' }

$scratchRoot = if ($env:TOP_CODE_SESSION_SCRATCH) { $env:TOP_CODE_SESSION_SCRATCH } else { 'C:\top-code-session-scratch' }
if (-not $ProofDir) {
    $ProofDir = Join-Path $scratchRoot 'rag-v2-live-cutover'
}
New-Item -ItemType Directory -Path $ProofDir -Force | Out-Null

$day = Get-Date -Format 'yyyyMMdd'
$stamp = Get-Date -Format 'yyyyMMddTHHmmss'
$proofId = "rag-v2-live-cutover-$stamp"

$knowledgeEval = Join-Path $env:TOP_CODE_ROOT "knowledge\eval\rag-v2-live-cutover-$day"
if (-not $SummaryDir) {
    try {
        New-Item -ItemType Directory -Path $knowledgeEval -Force -ErrorAction Stop | Out-Null
        $SummaryDir = $knowledgeEval
    } catch {
        $SummaryDir = Join-Path $ProofDir 'summary'
        New-Item -ItemType Directory -Path $SummaryDir -Force | Out-Null
    }
}

$logFile = Join-Path $ProofDir "gate-b-$stamp.log"
$summaryJson = Join-Path $SummaryDir "summary-$stamp.json"
$pdfPath = Join-Path $ProofDir "live-cutover-$stamp.pdf"
$proofPy = Join-Path $ragRoot 'backend\scripts\rag_v2_live_cutover_proof.py'

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
    param([string]$HostName, [int]$Port, [int]$TimeoutSec = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-Tcp -HostName $HostName -Port $Port -TimeoutMs 1000) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Wait-HttpOk {
    param([string]$Url, [int]$TimeoutSec = 120)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) { return $true }
        } catch {}
        Start-Sleep -Seconds 2
    }
    return $false
}

$overall = 'FAIL'
$composeExit = -1
$proofExit = -1
$health = [ordered]@{
    rag_health = 'FAIL'
    temporal   = 'FAIL'
    minio      = 'FAIL'
    qdrant     = 'FAIL'
    graphstore = 'FAIL'
}
$gitSha = 'unknown'
$gaps = [System.Collections.Generic.List[string]]::new()
$commands = [System.Collections.Generic.List[string]]::new()

try {
    Write-Log "RAG V2 live cutover Gate B" 'Cyan'
    Write-Log "BOUNDS: does NOT flip RAG_CORE=v2; staged cutover is separate." 'Yellow'
    Write-Log "ProofDir=$ProofDir SummaryDir=$SummaryDir" 'Cyan'
    Write-Log "ragRoot=$ragRoot" 'Cyan'

    if (-not (Test-Path -LiteralPath $proofPy)) {
        throw "Companion proof missing: $proofPy"
    }

    try {
        $gitSha = (git -C $ragRoot rev-parse --short HEAD 2>$null).Trim()
        if (-not $gitSha) { $gitSha = 'unknown' }
    } catch { $gitSha = 'unknown' }
    Write-Log "rag-chat-asystent git_sha=$gitSha" 'Cyan'

    $composeFiles = @(
        '-f', 'docker-compose.yml',
        '-f', 'docker-compose.rag-v2-data-plane.yml'
    )
    $profileArgs = @('--profile', 'rag-v2-data-plane')
    $services = @(
        'rag-backend',
        'rag-v2-ingest-worker',
        'rag-v2-minio',
        'rag-v2-qdrant',
        'rag-v2-temporal',
        'graphstore-postgres'
    )

    if (-not $SkipUp) {
        Push-Location $ragRoot
        try {
            $env:RAG_V2_LIVE_DATA_PLANE = '1'
            $env:RAG_V2_LIVE_INGEST = '1'
            if (-not $SkipBuild) {
                $upArgs = $profileArgs + $composeFiles + @('up', '-d', '--build') + $services
                $cmdText = "docker compose $($upArgs -join ' ')"
                $commands.Add($cmdText)
                Write-Log "Compose up --build: $cmdText" 'Cyan'
                # Docker emits progress on stderr; avoid PowerShell treating it as terminating.
                $prevEap = $ErrorActionPreference
                $ErrorActionPreference = 'SilentlyContinue'
                & docker compose @upArgs *> (Join-Path $ProofDir "compose-up-$stamp.log")
                $composeExit = $LASTEXITCODE
                $ErrorActionPreference = $prevEap
            } else {
                $upArgs = $profileArgs + $composeFiles + @('up', '-d') + $services
                $cmdText = "docker compose $($upArgs -join ' ')"
                $commands.Add($cmdText)
                Write-Log "Compose up (no build): $cmdText" 'Cyan'
                $prevEap = $ErrorActionPreference
                $ErrorActionPreference = 'SilentlyContinue'
                & docker compose @upArgs *> (Join-Path $ProofDir "compose-up-$stamp.log")
                $composeExit = $LASTEXITCODE
                $ErrorActionPreference = $prevEap
            }
            if ($composeExit -ne 0) {
                throw "docker compose up failed (exit=$composeExit)"
            }
            Write-Log "Compose up OK (exit=$composeExit)" 'Green'
        } finally {
            Pop-Location
        }
    } else {
        Write-Log "SkipUp set - assuming stack already running." 'Yellow'
        $composeExit = 0
        $gaps.Add('SkipUp: compose not started by this harness')
    }

    Write-Log "Waiting for health endpoints..." 'Cyan'
    if (Wait-HttpOk -Url "$RagBaseUrl/health" -TimeoutSec 180) {
        $health.rag_health = 'PASS'
        Write-Log "RAG /health OK ($RagBaseUrl/health)" 'Green'
    } else {
        Write-Log "RAG /health NOT ready" 'Red'
    }

    if (Wait-Tcp -HostName '127.0.0.1' -Port $TemporalPort -TimeoutSec 120) {
        $health.temporal = 'PASS'
        Write-Log "Temporal :$TemporalPort OK" 'Green'
    } else {
        Write-Log "Temporal :$TemporalPort NOT ready" 'Red'
    }

    if (Wait-Tcp -HostName '127.0.0.1' -Port $MinioPort -TimeoutSec 60) {
        $health.minio = 'PASS'
        Write-Log "MinIO :$MinioPort OK" 'Green'
    } else {
        Write-Log "MinIO :$MinioPort NOT ready" 'Red'
    }

    if (Wait-Tcp -HostName '127.0.0.1' -Port $QdrantPort -TimeoutSec 60) {
        $health.qdrant = 'PASS'
        Write-Log "Qdrant :$QdrantPort OK" 'Green'
    } else {
        Write-Log "Qdrant :$QdrantPort NOT ready" 'Red'
    }

    if (Wait-Tcp -HostName '127.0.0.1' -Port $GraphStorePort -TimeoutSec 60) {
        $health.graphstore = 'PASS'
        Write-Log "GraphStore Postgres :$GraphStorePort OK" 'Green'
    } else {
        Write-Log "GraphStore Postgres :$GraphStorePort NOT ready" 'Red'
    }

    $requiredHealth = @(
        $health.rag_health,
        $health.temporal,
        $health.minio,
        $health.qdrant,
        $health.graphstore
    )
    if ($requiredHealth -contains 'FAIL') {
        throw "Required health checks failed: $($health | ConvertTo-Json -Compress)"
    }

    # --- generate multi-page PDF with table ---
    Write-Log "Generating multi-page PDF with table: $pdfPath" 'Cyan'
    $pdfScript = @"
from pathlib import Path
out = Path(r'$pdfPath')
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate(str(out), pagesize=A4)
styles = getSampleStyleSheet()
story = []
story.append(Paragraph('RAG V2 Live Cutover Proof - Strona 1', styles['Title']))
story.append(Spacer(1, 0.5 * cm))
story.append(Paragraph(
    'Instrukcja techniczna pompy ciepla XYZ. Dokument wielostronicowy do Gate B.',
    styles['Normal'],
))
story.append(Spacer(1, 0.4 * cm))
story.append(Paragraph('Tabela parametrow technicznych:', styles['Heading2']))
data = [
    ['Parametr', 'Wartosc', 'Jednostka'],
    ['Moc grzewcza', '8', 'kW'],
    ['COP A7/W35', '4.2', '-'],
    ['Czynnik', 'R32', '-'],
]
t = Table(data, colWidths=[6 * cm, 3 * cm, 3 * cm])
t.setStyle(TableStyle([
    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
    ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
]))
story.append(t)
story.append(PageBreak())
story.append(Paragraph('RAG V2 Live Cutover Proof - Strona 2', styles['Title']))
story.append(Spacer(1, 0.5 * cm))
story.append(Paragraph(
    'Dodatkowy kontekst: pompa ciepla XYZ o mocy grzewczej 8 kW do instalacji TOP-INSTAL.',
    styles['Normal'],
))
story.append(Paragraph(
    'Fact line for retrieval: moc grzewcza pompy ciepla wynosi 8 kW.',
    styles['Normal'],
))
story.append(Paragraph(
    'Sekcja serwisowa: sprawdzanie cisnienia, filtrow i odszraniania.',
    styles['Normal'],
))
doc.build(story)
print('PDF_OK', out, out.stat().st_size)
"@
    $pdfGenPy = Join-Path $ProofDir "gen_pdf_$stamp.py"
    Set-Content -LiteralPath $pdfGenPy -Value $pdfScript -Encoding UTF8
    $commands.Add("$PythonExe $pdfGenPy")
    $pdfOut = & $PythonExe $pdfGenPy 2>&1 | Out-String
    Write-Log $pdfOut.Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pdfPath)) {
        throw "PDF generation failed: $pdfOut"
    }
    Write-Log "PDF ready: $pdfPath" 'Green'

    # --- host-side live env ---
    $backendPath = Join-Path $ragRoot 'backend'
    $env:PYTHONPATH = $backendPath
    $env:MINIO_ENDPOINT = "127.0.0.1:$MinioPort"
    $env:MINIO_ACCESS_KEY = 'minioadmin'
    $env:MINIO_SECRET_KEY = 'minioadmin'
    $env:MINIO_ROOT_USER = 'minioadmin'
    $env:MINIO_ROOT_PASSWORD = 'minioadmin'
    $env:MINIO_BUCKET = 'rag-v2'
    $env:MINIO_SECURE = '0'
    $env:QDRANT_URL = "http://127.0.0.1:$QdrantPort"
    $env:RAG_V2_QDRANT_URL = "http://127.0.0.1:$QdrantPort"
    $env:RAG_V2_TEMPORAL_HOST = "127.0.0.1:$TemporalPort"
    $env:TEMPORAL_HOST = "127.0.0.1:$TemporalPort"
    $env:RAG_V2_TEMPORAL_TASK_QUEUE = 'rag-v2-ingest'
    $env:RAG_V2_POSTGRES_DSN = "postgresql://postgres:postgres@127.0.0.1:$GraphStorePort/graphstore"
    $env:PGVECTOR_DSN = $env:RAG_V2_POSTGRES_DSN
    $env:RAG_V2_LIVE_DATA_PLANE = '1'
    $env:RAG_V2_LIVE_INGEST = '1'

    Write-Log "ENV host proof: MINIO_ENDPOINT=$($env:MINIO_ENDPOINT) QDRANT_URL=$($env:QDRANT_URL) TEMPORAL=$($env:RAG_V2_TEMPORAL_HOST) PG=127.0.0.1:$GraphStorePort LIVE_DATA_PLANE=1" 'Cyan'
    Write-Log "NOTE: secrets set in process env only; summary JSON redacts credentials." 'Yellow'

    $pyArgs = @(
        $proofPy,
        '--pdf', $pdfPath,
        '--summary-out', $summaryJson,
        '--proof-id', $proofId,
        '--worker-container', $WorkerContainer,
        '--query', 'moc grzewcza pompy ciepla'
    )
    if ($SkipTemporal) { $pyArgs += '--skip-temporal' }
    if ($SkipRestart) { $pyArgs += '--skip-restart' }

    $cmdProof = "$PythonExe $($pyArgs -join ' ')"
    $commands.Add($cmdProof)
    Write-Log "Running companion proof..." 'Cyan'
    $proofLog = Join-Path $ProofDir "proof-py-$stamp.log"
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    & $PythonExe @pyArgs *> $proofLog
    $proofExit = $LASTEXITCODE
    $ErrorActionPreference = $prevEap
    if (Test-Path -LiteralPath $proofLog) {
        Get-Content -LiteralPath $proofLog -Tail 40 | ForEach-Object { Write-Log $_ 'Gray' }
    }
    Write-Log "Companion proof exit=$proofExit" $(if ($proofExit -eq 0) { 'Green' } else { 'Red' })

    if ($proofExit -eq 0) {
        $overall = 'PASS'
    } else {
        $overall = 'FAIL'
        $gaps.Add("Companion proof exit=$proofExit; see $proofLog")
    }

} catch {
    Write-Log "FATAL: $($_.Exception.Message)" 'Red'
    $gaps.Add("Fatal: $($_.Exception.Message)")
    $overall = 'FAIL'
}

# Harness-level summary (no secrets).
$harnessSummary = [ordered]@{
    proof_id            = $proofId
    stamp               = $stamp
    overall             = $overall
    git_sha             = $gitSha
    repo                = 'rag-chat-asystent'
    proof_dir           = $ProofDir
    summary_json        = $summaryJson
    pdf_path            = $pdfPath
    compose_exit_code   = $composeExit
    proof_exit_code     = $proofExit
    health              = $health
    commands            = @($commands)
    gaps                = @($gaps)
    bounds              = @(
        'Does not flip RAG_CORE=v2 globally',
        'Does not perform staged product cutover',
        'Uses compose profile rag-v2-data-plane + docker-compose.rag-v2-data-plane.yml',
        'Host proof sets RAG_V2_LIVE_DATA_PLANE=1 / RAG_V2_LIVE_INGEST=1 for this process only'
    )
    companion           = 'rag-chat-asystent/backend/scripts/rag_v2_live_cutover_proof.py'
}

$harnessPath = Join-Path $SummaryDir "harness-$stamp.json"
try {
    $harnessSummary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $harnessPath -Encoding UTF8
} catch {
    $harnessPath = Join-Path $ProofDir "harness-$stamp.json"
    $harnessSummary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $harnessPath -Encoding UTF8
}

Write-Host ''
Write-Host '======== RAG V2 LIVE CUTOVER GATE B ========' -ForegroundColor Cyan
Write-Host ("Overall:        {0}" -f $overall)
Write-Host ("Proof id:       {0}" -f $proofId)
Write-Host ("Git sha:        {0}" -f $gitSha)
Write-Host ("RAG /health:    {0}" -f $health.rag_health)
Write-Host ("Temporal:       {0}" -f $health.temporal)
Write-Host ("MinIO:          {0}" -f $health.minio)
Write-Host ("Qdrant:         {0}" -f $health.qdrant)
Write-Host ("GraphStore:     {0}" -f $health.graphstore)
Write-Host ("Companion exit: {0}" -f $proofExit)
Write-Host ("Summary JSON:   {0}" -f $summaryJson)
Write-Host ("Harness JSON:   {0}" -f $harnessPath)
Write-Host ("Log:            {0}" -f $logFile)
Write-Host '==========================================='

if ($overall -ne 'PASS') { exit 1 }
exit 0
