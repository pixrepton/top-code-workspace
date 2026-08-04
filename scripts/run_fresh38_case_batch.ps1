# Case-by-case Fresh 38 SUT capture into gmail-agent-nodeb-api.
# Avoids full-batch OOM (Exit2 137). Uses resilient per-case docker exec.

param(
    [string[]]$CaseIds = @(),
    [string]$OutDir = '',
    [string]$Corpus = '',
    [string]$HarnessDir = '',
    [string]$PatchedRunner = '',
    [string]$Container = 'gmail-agent-nodeb-api',
    [string]$Mode = 'production_faithful'
)

$ErrorActionPreference = 'Continue'
$Workspace = Split-Path $PSScriptRoot -Parent
$AuditDir = Join-Path $Workspace 'gmail-agent\tools\gmail_audit'

if (-not $Corpus) {
    $Corpus = Join-Path $AuditDir 'tests\fixtures\measurement_contract_v1\corpus-v2.json'
}
if (-not $HarnessDir) {
    $HarnessDir = Join-Path $Workspace '.artifacts\ai-os-post-stage6-fresh-baseline\harness'
}
if (-not $PatchedRunner) {
    $candidate = 'C:\top-code-session-scratch\exit2-fresh38-20260803T185704\run_recovery_pf.PATCHED.py'
    if (Test-Path $candidate) {
        $PatchedRunner = $candidate
    } else {
        $PatchedRunner = Join-Path $HarnessDir 'run_recovery_pf.py'
    }
}
if (-not $OutDir) {
    $stamp = Get-Date -Format 'yyyyMMddTHHmmss'
    $OutDir = Join-Path $env:TEMP "fresh38-capture-$stamp"
}

if (-not $CaseIds -or $CaseIds.Count -eq 0) {
    $CaseIds = @('NEW-03', 'FU-05', 'SVC-01', 'SVC-02', 'CTX-01')
} else {
    # Accept both @('A','B') and 'A,B' / 'A,B,C' from CLI.
    $CaseIds = @(
        $CaseIds |
            ForEach-Object { $_ -split ',' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$log = Join-Path $OutDir 'capture.log'

function Log([string]$msg) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Host $line
}

Log "START cases=$($CaseIds -join ',')"
Log "runner=$PatchedRunner"
Log "corpus=$Corpus"

docker exec $Container sh -lc 'mkdir -p /tmp/fresh38-sentinel' | Out-Null
docker cp $PatchedRunner "${Container}:/tmp/fresh38-sentinel/run_recovery_pf.py"
docker cp (Join-Path $HarnessDir 'scoring.py') "${Container}:/tmp/fresh38-sentinel/scoring.py"
docker cp $Corpus "${Container}:/tmp/fresh38-sentinel/corpus-v2.json"

# Hotfix product files into running API image (no rebuild) so capture sees current host SHA.
$hotFiles = @(
    'central_llm_stage.py',
    'understanding_output.py',
    'eval_understanding_judge.py'
)
foreach ($name in $hotFiles) {
    $src = Join-Path $AuditDir $name
    if (Test-Path $src) {
        docker cp $src "${Container}:/app/tools/gmail_audit/$name"
        Log "synced $name"
    }
}

$merged = @{
    mode = $Mode
    cases = @()
    capture_tool = 'scripts/run_fresh38_case_batch.ps1'
    started_at = (Get-Date).ToString('o')
}
$failed = @()
$ok = @()

foreach ($cid in $CaseIds) {
    Log "START $cid"
    $remoteOut = "/tmp/fresh38-sentinel/one-$cid.json"
    $stdout = Join-Path $OutDir "one-$cid-stdout.txt"
    $stderr = Join-Path $OutDir "one-$cid-stderr.txt"
    # Use cmd redirection so docker JSON logs on stderr do not become PowerShell errors.
    cmd /c "docker exec -w /tmp/fresh38-sentinel $Container python run_recovery_pf.py $Mode corpus-v2.json $remoteOut $cid > `"$stdout`" 2> `"$stderr`""
    $ec = $LASTEXITCODE
    $local = Join-Path $OutDir "one-$cid.json"
    $hasOut = $false
    if ($ec -eq 0) {
        docker cp "${Container}:$remoteOut" $local 2>$null
        $hasOut = Test-Path $local
    }
    if (-not $hasOut) {
        Log "FAIL $cid exit=$ec"
        $failed += $cid
        continue
    }
    try {
        $j = Get-Content $local -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($j.cases) {
            foreach ($nc in @($j.cases)) {
                $merged.cases += $nc
            }
        }
        $ok += $cid
        Log "OK $cid"
    } catch {
        Log "FAIL $cid parse: $($_.Exception.Message)"
        $failed += $cid
    }
}

$merged.completed_at = (Get-Date).ToString('o')
$merged.ok_cases = $ok
$merged.failed_cases = $failed
($merged | ConvertTo-Json -Depth 40) | Set-Content (Join-Path $OutDir 'fresh38-partial-results.json') -Encoding UTF8

Log "DONE ok=$($ok.Count) failed=$($failed.Count) out=$OutDir"
if ($failed.Count -gt 0) { exit 1 }
exit 0
