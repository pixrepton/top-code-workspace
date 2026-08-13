# Fresh38 capture contract proof. Docker is stubbed; no live container, provider, judge,
# scoring, or product code is executed.

$ErrorActionPreference = 'Stop'
$Workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Wrapper = Join-Path $Workspace 'scripts\run_fresh38_case_batch.ps1'

$failures = @()
function Check([bool]$condition, [string]$label) {
    if ($condition) { Write-Host "  PASS  $label" }
    else { Write-Host "  FAIL  $label" -ForegroundColor Red; $script:failures += $label }
}

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("f38-contract-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $root | Out-Null

try {
    $shimDir = Join-Path $root 'shim'
    New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
    @'
@echo off
setlocal EnableDelayedExpansion
if "%~1"=="version" (echo 25.0.0& exit /b 0)
if "%~1"=="inspect" goto :inspect
if "%~1"=="events" goto :events
if "%~1"=="exec" goto :exec
if "%~1"=="cp" goto :cp
exit /b 0
:inspect
if "%~2"=="--format" (echo sha256:stubimage0001& exit /b 0)
echo [{"ID":"contractexec001","Running":false,"ExitCode":0,"Pid":4242,"ProcessConfig":{"entrypoint":"python","arguments":["-u","run_recovery_pf.py"]},"ContainerID":"stub-container-id"}]
exit /b 0
:events
echo {"Type":"container","Action":"exec_create: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% STUB-01","Actor":{"ID":"stub-container-id","Attributes":{"execID":"contractexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000001}
echo {"Type":"container","Action":"exec_start: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% STUB-01","Actor":{"ID":"stub-container-id","Attributes":{"execID":"contractexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000002}
echo {"Type":"container","Action":"exec_die","Actor":{"ID":"stub-container-id","Attributes":{"execID":"contractexec001","exitCode":"0","name":"stub-container","image":"stub-image"}},"time":1780000002,"timeNano":1780000002000000001}
exit /b 0
:exec
echo %* | findstr /c:"rm -f" >nul
if not errorlevel 1 exit /b 0
echo %* | findstr /c:"run_recovery_pf.py" >nul
if not errorlevel 1 (
  1>&2 echo [fresh38-lifecycle] {"event":"runner_start","attempt_id":"%F38_ATTEMPT_ID%","pid":321,"runner":{"pid":321,"ppid":1,"proc_start_ticks":999,"cmdline":"python -u run_recovery_pf.py"}}
  exit /b 0
)
echo %* | findstr /c:"python -" >nul
if not errorlevel 1 (
  echo {"probe_time_utc":"2026-08-12T00:00:00Z","attempt_id":"%F38_ATTEMPT_ID%","remote_path":"%F38_REMOTE_PATH%","runner_pid_requested":"321","runner_start_ticks_requested":"999","runner_pid_info":{"pid":"321","exists":false},"attempt_processes":[],"ownership":{"original_runner_alive":false,"attempt_process_count":0,"closed":true},"artifact":{"path":"%F38_REMOTE_PATH%","exists":true,"size":128,"valid_json":true,"attempt_id":"%F38_ATTEMPT_ID%","case_id":"STUB-01","stage_reached":"full"}}
  exit /b 0
)
exit /b 0
:cp
set "SRC=%~2"
set "DST=%~3"
if "%SRC:~1,1%"==":" exit /b 0
echo %SRC% | findstr /c:"stdout.txt" >nul
if not errorlevel 1 (
  > "%DST%" echo === STUB-01 mode=production_faithful ===
  exit /b 0
)
echo %SRC% | findstr /c:"stderr.txt" >nul
if not errorlevel 1 (
  > "%DST%" echo [fresh38-lifecycle] {"event":"runner_start","attempt_id":"%F38_ATTEMPT_ID%","pid":321,"runner":{"pid":321,"ppid":1,"proc_start_ticks":999,"cmdline":"python -u run_recovery_pf.py"}}
  exit /b 0
)
if "%F38_STUB_MODE%"=="missing" exit /b 1
if "%F38_STUB_MODE%"=="malformed" (
  > "%DST%" echo {not-json
  exit /b 0
)
if "%F38_STUB_MODE%"=="mismatch" (
  > "%DST%" echo {"measurement_attempt":{"attempt_id":"%F38_ATTEMPT_ID%","artifact_path":"%F38_REMOTE_PATH%"},"cases":[{"id":"OTHER","stage_reached":"full"}]}
  exit /b 0
)
if "%F38_STUB_MODE%"=="wrongattempt" (
  > "%DST%" echo {"measurement_attempt":{"attempt_id":"other-attempt","artifact_path":"%F38_REMOTE_PATH%"},"cases":[{"id":"STUB-01","stage_reached":"full"}]}
  exit /b 0
)
if "%F38_STUB_MODE%"=="nonterminal" (
  > "%DST%" echo {"measurement_attempt":{"attempt_id":"%F38_ATTEMPT_ID%","artifact_path":"%F38_REMOTE_PATH%"},"cases":[{"id":"STUB-01"}]}
  exit /b 0
)
if "%F38_STUB_MODE%"=="delayed" (
  if exist "%F38_DELAY_MARKER%" (
    > "%DST%" echo {"measurement_attempt":{"attempt_id":"%F38_ATTEMPT_ID%","artifact_path":"%F38_REMOTE_PATH%"},"cases":[{"id":"STUB-01","stage_reached":"full"}]}
    exit /b 0
  )
  > "%F38_DELAY_MARKER%" echo late
  exit /b 1
)
if "%F38_STUB_MODE%"=="productfail" (
  > "%DST%" echo {"measurement_attempt":{"attempt_id":"%F38_ATTEMPT_ID%","artifact_path":"%F38_REMOTE_PATH%"},"cases":[{"id":"STUB-01","stage_reached":"intake_reasoning_error","case_product_outcome":"CASE_PRODUCT_FAIL","terminal_product_result":{"stage":"intake_reasoning","reason":"intake_result_final_missing"}}]}
  exit /b 0
)
> "%DST%" echo {"measurement_attempt":{"attempt_id":"%F38_ATTEMPT_ID%","artifact_path":"%F38_REMOTE_PATH%"},"cases":[{"id":"STUB-01","stage_reached":"full","case_product_outcome":"CASE_PRODUCT_PASS"}]}
exit /b 0
'@ | Set-Content -Path (Join-Path $shimDir 'docker.bat') -Encoding ASCII
    $env:PATH = "$shimDir;$env:PATH"
    $env:FRESH38_EXEC_CHANNEL = 'docker_cli'

    $corpus = Join-Path $root 'corpus-v2.json'
    Set-Content -Path $corpus -Value '{"cases":[{"id":"STUB-01"}]}' -Encoding UTF8
    $harness = Join-Path $Workspace 'scripts\fresh38'

    function Invoke-Wrapper([string]$mode, [string]$outName) {
        $env:F38_STUB_MODE = $mode
        $env:F38_DELAY_MARKER = Join-Path $root "$outName.delay"
        $env:F38_REMOTE_PATH = "/tmp/fresh38-sentinel/contract$outName/STUB-01/one-STUB-01.json"
        $env:F38_ATTEMPT_ID = "contract$outName"
        $outDir = Join-Path $root $outName
        $argList = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Wrapper,
            '-CaseIds', 'STUB-01',
            '-OutDir', $outDir,
            '-Corpus', $corpus,
            '-HarnessDir', $harness,
            '-Container', 'stub-container',
            '-AttemptId', "contract$outName",
            '-NoReuse'
        )
        $output = & powershell @argList 2>&1 | Out-String
        return [pscustomobject]@{ Output = $output; ExitCode = $LASTEXITCODE; OutDir = $outDir }
    }

    Write-Host "`n[1/10] subprocess exit 0 + valid artifact -> qualified capture"
    $valid = Invoke-Wrapper 'valid' 'valid'
    Check ($valid.ExitCode -eq 0) 'valid artifact exits 0'
    Check ($valid.Output -match 'OK STUB-01 terminal=full') 'valid artifact is accepted'
    $validEvidence = Get-Content (Join-Path $valid.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($validEvidence.measurement_verdict.measurement_qualification -eq 'QUALIFIED') 'valid capture is qualified'
    Check ($validEvidence.measurement_verdict.l3_interpretation_allowed -eq 'YES') 'L3 interpretation is allowed only for qualified capture'

    Write-Host "`n[2/10] subprocess exit 0 + missing artifact -> artifact failure"
    $missing = Invoke-Wrapper 'missing' 'missing'
    Check ($missing.ExitCode -ne 0) 'missing artifact exits non-zero'
    Check ($missing.Output -match 'failure_class=ARTIFACT_FAILURE') 'missing artifact is classified as artifact failure'
    $missingEvidence = Get-Content (Join-Path $missing.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($missingEvidence.measurement_verdict.failure_subclass -eq 'ARTIFACT_MISSING') 'missing artifact subclass is ARTIFACT_MISSING'

    Write-Host "`n[3/10] subprocess exit 0 + malformed artifact -> artifact failure"
    $malformed = Invoke-Wrapper 'malformed' 'malformed'
    Check ($malformed.ExitCode -ne 0) 'malformed artifact exits non-zero'
    Check ($malformed.Output -match 'failure_class=ARTIFACT_FAILURE') 'malformed artifact is rejected'
    $malformedEvidence = Get-Content (Join-Path $malformed.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($malformedEvidence.measurement_verdict.failure_subclass -eq 'ARTIFACT_CORRUPT') 'malformed artifact subclass is ARTIFACT_CORRUPT'

    Write-Host "`n[4/10] case id mismatch -> artifact identity failure"
    $mismatch = Invoke-Wrapper 'mismatch' 'mismatch'
    Check ($mismatch.ExitCode -ne 0) 'case id mismatch exits non-zero'
    Check ($mismatch.Output -match 'failure_class=ARTIFACT_FAILURE') 'case id mismatch is rejected'
    $mismatchEvidence = Get-Content (Join-Path $mismatch.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($mismatchEvidence.measurement_verdict.failure_subclass -eq 'ARTIFACT_IDENTITY_MISMATCH') 'case id mismatch subclass is ARTIFACT_IDENTITY_MISMATCH'

    Write-Host "`n[5/10] wrong attempt_id -> artifact identity failure"
    $wrongAttempt = Invoke-Wrapper 'wrongattempt' 'wrongattempt'
    Check ($wrongAttempt.ExitCode -ne 0) 'wrong attempt_id exits non-zero'
    $wrongAttemptEvidence = Get-Content (Join-Path $wrongAttempt.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($wrongAttemptEvidence.measurement_verdict.failure_subclass -eq 'ARTIFACT_IDENTITY_MISMATCH') 'wrong attempt_id subclass is ARTIFACT_IDENTITY_MISMATCH'

    Write-Host "`n[6/10] missing terminal stage -> artifact non-terminal failure"
    $nonterminal = Invoke-Wrapper 'nonterminal' 'nonterminal'
    Check ($nonterminal.ExitCode -ne 0) 'non-terminal artifact exits non-zero'
    $nonterminalEvidence = Get-Content (Join-Path $nonterminal.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($nonterminalEvidence.measurement_verdict.failure_subclass -eq 'ARTIFACT_NON_TERMINAL') 'non-terminal artifact subclass is ARTIFACT_NON_TERMINAL'

    Write-Host "`n[7/10] genuine product failure artifact -> qualified capture"
    $productFail = Invoke-Wrapper 'productfail' 'productfail'
    Check ($productFail.ExitCode -eq 0) 'product failure artifact exits 0'
    Check ($productFail.Output -match 'OK STUB-01 terminal=intake_reasoning_error product_outcome=CASE_PRODUCT_FAIL') 'product failure remains a valid capture'
    $productFailEvidence = Get-Content (Join-Path $productFail.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($productFailEvidence.measurement_verdict.measurement_qualification -eq 'QUALIFIED') 'product failure can be a qualified measurement'

    Write-Host "`n[8/10] delayed artifact after exec -> artifact failure, no retry workaround"
    $delayed = Invoke-Wrapper 'delayed' 'delayed'
    Check ($delayed.ExitCode -ne 0) 'delayed artifact exits non-zero'
    Check ($delayed.Output -match 'COPY_FAIL STUB-01') 'delayed artifact is not masked by copy retry'
    $delayedEvidence = Get-Content (Join-Path $delayed.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($delayedEvidence.measurement_verdict.failure_class -eq 'ARTIFACT_FAILURE') 'delayed artifact remains artifact failure'

    Write-Host "`n[9/10] invalid measurement blocks product interpretation"
    Check ($delayedEvidence.measurement_verdict.l3_interpretation_allowed -eq 'NO') 'L3 interpretation is blocked on invalid measurement'
    Check ($delayedEvidence.measurement_verdict.judge_run -eq 'NO') 'judge is blocked on invalid measurement'
    Check ($delayedEvidence.measurement_verdict.scoring_run -eq 'NO') 'scoring is blocked on invalid measurement'
    Check ($delayedEvidence.measurement_verdict.capability_classified -eq 'NO') 'capability classification is blocked on invalid measurement'

    Write-Host "`n[10/10] merged result preserves product failure"
    $merged = Get-Content (Join-Path $productFail.OutDir 'fresh38-partial-results.json') -Raw | ConvertFrom-Json
    Check ($merged.ok_cases -contains 'STUB-01') 'product failure case is included in ok_cases'
    Check ($merged.cases[0].case_product_outcome -eq 'CASE_PRODUCT_FAIL') 'product failure outcome is preserved'
}
finally {
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
    Remove-Item Env:F38_STUB_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:F38_DELAY_MARKER -ErrorAction SilentlyContinue
    Remove-Item Env:F38_REMOTE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:F38_ATTEMPT_ID -ErrorAction SilentlyContinue
    Remove-Item Env:FRESH38_EXEC_CHANNEL -ErrorAction SilentlyContinue
}

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "FRESH38 CAPTURE CONTRACT: FAIL ($($failures.Count))" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host 'FRESH38 CAPTURE CONTRACT: PASS' -ForegroundColor Green
exit 0
