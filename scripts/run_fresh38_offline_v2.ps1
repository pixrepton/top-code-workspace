# Offline Fresh 38 rescore (measurement contract v2 primary).
# Does NOT call the SUT. Requires frozen capture + optional judge results.

param(
    [string]$RunResults = 'C:\top-code-session-scratch\exit2-fresh38-20260803T185704\fresh-full38-results.json',
    [string]$JudgeResults = 'C:\top-code-session-scratch\exit2-fresh38-20260803T185704\fresh-understanding-judge.REJUDGE.json',
    [string]$Corpus = '',
    [string]$OutDir = '',
    [ValidateSet('v1', 'v2', 'v3', 'v4')]
    [string]$Contract = 'v2'
)

$ErrorActionPreference = 'Stop'
$Workspace = Split-Path $PSScriptRoot -Parent
$AuditDir = Join-Path $Workspace 'gmail-agent\tools\gmail_audit'

if (-not $Corpus) {
    $Corpus = Join-Path $AuditDir 'tests\fixtures\measurement_contract_v1\corpus-v1.json'
}
if (-not $OutDir) {
    $stamp = Get-Date -Format 'yyyyMMddTHHmmss'
    $OutDir = Join-Path $Workspace "knowledge\eval\phase1-fresh38-$stamp"
}

if (-not (Test-Path $RunResults)) { throw "missing run results: $RunResults" }
if (-not (Test-Path $Corpus)) { throw "missing corpus: $Corpus" }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$judgeArg = @()
if ($JudgeResults -and (Test-Path $JudgeResults)) {
    $judgeArg = @('--understanding-judge-results', $JudgeResults)
} else {
    Write-Host "WARN: no judge results; rescore will treat missing judge as HARNESS for understanding-eligible cases"
}

Push-Location $AuditDir
try {
    python eval_final_rescore_versioned.py `
        --measurement-contract-version $Contract `
        --run-results $RunResults `
        --corpus $Corpus `
        @judgeArg `
        --out (Join-Path $OutDir "rescore-$Contract.json") `
        --summary-out (Join-Path $OutDir "summary-$Contract.json") `
        --breakdown-out (Join-Path $OutDir "breakdown-$Contract.json") `
        --qualification-out (Join-Path $OutDir "qualification-$Contract.json")
    if ($LASTEXITCODE -ne 0) { throw "rescore exit $LASTEXITCODE" }
} finally {
    Pop-Location
}

$qual = Get-Content (Join-Path $OutDir "qualification-$Contract.json") -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ("OUTDIR={0}" -f $OutDir)
Write-Host ("scoring_complete={0}" -f $qual.scoring_complete)
Write-Host ("clean_pass={0}" -f $qual.clean_pass)
Write-Host ("verdict={0}" -f $qual.verdict)
exit 0
