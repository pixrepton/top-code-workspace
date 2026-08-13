# Fresh38 Docker Exec lifecycle proof. Docker is stubbed; no live container, provider,
# judge, scoring, or product code is executed.

$ErrorActionPreference = 'Stop'
$Workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Wrapper = Join-Path $Workspace 'scripts\run_fresh38_case_batch.ps1'

$failures = @()
function Check([bool]$condition, [string]$label) {
    if ($condition) { Write-Host "  PASS  $label" }
    else { Write-Host "  FAIL  $label" -ForegroundColor Red; $script:failures += $label }
}

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("f38-exec-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $root | Out-Null

try {
    $shimDir = Join-Path $root 'shim'
    New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
    @'
@echo off
setlocal EnableDelayedExpansion
if "%~1"=="version" (echo 25.0.0& exit /b 0)
if "%~1"=="events" goto :events
if "%~1"=="inspect" goto :inspect
if "%~1"=="exec" goto :exec
if "%~1"=="cp" goto :cp
exit /b 0

:inspect
if "%~2"=="--format" (echo sha256:stubimage0001& exit /b 0)
if "%F38_SCENARIO%"=="running_then_die" (
  if exist "%F38_DIE_MARKER%" (
    echo [{"ID":"mainexec001","Running":false,"ExitCode":0,"Pid":4242,"ProcessConfig":{"entrypoint":"python","arguments":["-u","run_recovery_pf.py"]},"ContainerID":"stub-container-id"}]
  ) else (
    echo [{"ID":"mainexec001","Running":true,"ExitCode":null,"Pid":4242,"ProcessConfig":{"entrypoint":"python","arguments":["-u","run_recovery_pf.py"]},"ContainerID":"stub-container-id"}]
  )
  exit /b 0
)
if "%F38_SCENARIO%"=="exec_timeout" (
  echo [{"ID":"mainexec001","Running":true,"ExitCode":null,"Pid":4242,"ProcessConfig":{"entrypoint":"python","arguments":["-u","run_recovery_pf.py"]},"ContainerID":"stub-container-id"}]
  exit /b 0
)
if "%F38_SCENARIO%"=="exec_nonzero" (
  echo [{"ID":"mainexec001","Running":false,"ExitCode":7,"Pid":4242,"ProcessConfig":{"entrypoint":"python","arguments":["-u","run_recovery_pf.py"]},"ContainerID":"stub-container-id"}]
  exit /b 0
)
echo [{"ID":"mainexec001","Running":false,"ExitCode":0,"Pid":4242,"ProcessConfig":{"entrypoint":"python","arguments":["-u","run_recovery_pf.py"]},"ContainerID":"stub-container-id"}]
exit /b 0

:events
if "%F38_SCENARIO%"=="missing_exec_id" exit /b 0
if "%F38_SCENARIO%"=="running_then_die" goto :events_delayed
if "%F38_SCENARIO%"=="exec_timeout" goto :events_timeout
call :main_events
if "%F38_SCENARIO%"=="ambiguous_exec_id" (
  echo {"Type":"container","Action":"exec_create: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec002","name":"stub-container","image":"stub-image"}},"time":1780000003,"timeNano":1780000003000000001}
  echo {"Type":"container","Action":"exec_start: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec002","name":"stub-container","image":"stub-image"}},"time":1780000003,"timeNano":1780000003000000002}
  echo {"Type":"container","Action":"exec_die","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec002","exitCode":"0","name":"stub-container","image":"stub-image"}},"time":1780000004,"timeNano":1780000004000000001}
)
exit /b 0

:main_events
echo {"Type":"container","Action":"exec_create: sh -lc rm -rf /tmp/fresh38-sentinel/%F38_ATTEMPT_ID%; mkdir -p /tmp/fresh38-sentinel/%F38_ATTEMPT_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"probeexec001","name":"stub-container","image":"stub-image"}},"time":1780000000,"timeNano":1780000000000000001}
echo {"Type":"container","Action":"exec_start: sh -lc rm -rf /tmp/fresh38-sentinel/%F38_ATTEMPT_ID%; mkdir -p /tmp/fresh38-sentinel/%F38_ATTEMPT_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"probeexec001","name":"stub-container","image":"stub-image"}},"time":1780000000,"timeNano":1780000000000000002}
echo {"Type":"container","Action":"exec_die","Actor":{"ID":"stub-container-id","Attributes":{"execID":"probeexec001","exitCode":"0","name":"stub-container","image":"stub-image"}},"time":1780000000,"timeNano":1780000000000000003}
echo {"Type":"container","Action":"exec_create: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000001}
echo {"Type":"container","Action":"exec_start: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000002}
if "%F38_SCENARIO%"=="exec_nonzero" (
  echo {"Type":"container","Action":"exec_die","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","exitCode":"7","name":"stub-container","image":"stub-image"}},"time":1780000002,"timeNano":1780000002000000001}
) else if "%F38_SCENARIO%"=="exit_mismatch" (
  echo {"Type":"container","Action":"exec_die","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","exitCode":"7","name":"stub-container","image":"stub-image"}},"time":1780000002,"timeNano":1780000002000000001}
) else (
  echo {"Type":"container","Action":"exec_die","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","exitCode":"0","name":"stub-container","image":"stub-image"}},"time":1780000002,"timeNano":1780000002000000001}
)
exit /b 0

:events_delayed
if not exist "%F38_EVENT_FIRST%" (
  > "%F38_EVENT_FIRST%" echo 1
  echo {"Type":"container","Action":"exec_create: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000001}
  echo {"Type":"container","Action":"exec_start: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000002}
  exit /b 0
)
if not exist "%F38_EVENT_SECOND%" (
  > "%F38_EVENT_SECOND%" echo 2
  echo {"Type":"container","Action":"exec_create: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000001}
  echo {"Type":"container","Action":"exec_start: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000002}
  exit /b 0
)
> "%F38_DIE_MARKER%" echo die
echo {"Type":"container","Action":"exec_die","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","exitCode":"0","name":"stub-container","image":"stub-image"}},"time":1780000002,"timeNano":1780000002000000001}
exit /b 0

:events_timeout
if not exist "%F38_EVENT_FIRST%" (
  > "%F38_EVENT_FIRST%" echo 1
  echo {"Type":"container","Action":"exec_create: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000001}
  echo {"Type":"container","Action":"exec_start: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000002}
  exit /b 0
)
if not exist "%F38_EVENT_SECOND%" (
  > "%F38_EVENT_SECOND%" echo 2
  echo {"Type":"container","Action":"exec_create: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000001}
  echo {"Type":"container","Action":"exec_start: python -u run_recovery_pf.py production_faithful corpus-v2.json %F38_REMOTE_PATH% %F38_CASE_ID%","Actor":{"ID":"stub-container-id","Attributes":{"execID":"mainexec001","name":"stub-container","image":"stub-image"}},"time":1780000001,"timeNano":1780000001000000002}
  exit /b 0
)
ping -n 4 127.0.0.1 >nul
exit /b 0

:exec
echo %* | findstr /c:"run_recovery_pf.py" >nul
if not errorlevel 1 (
  if "%F38_SCENARIO%"=="missing_runner_identity" (
    if "%F38_CASE_EXIT%"=="" exit /b 0
    exit /b %F38_CASE_EXIT%
  )
  if "%F38_SCENARIO%"=="remote_logs_only" (
    if "%F38_CASE_EXIT%"=="" exit /b 0
    exit /b %F38_CASE_EXIT%
  )
  1>&2 echo [fresh38-lifecycle] {"event":"runner_start","attempt_id":"%F38_ATTEMPT_ID%","pid":321,"runner":{"pid":321,"ppid":1,"proc_start_ticks":999,"cmdline":"python -u run_recovery_pf.py"}}
  if "%F38_CASE_EXIT%"=="" exit /b 0
  exit /b %F38_CASE_EXIT%
)
echo %* | findstr /c:"python -" >nul
if not errorlevel 1 (
  if "%F38_SCENARIO%"=="ownership_alive" (
    echo {"probe_time_utc":"2026-08-12T00:00:00Z","attempt_id":"%F38_ATTEMPT_ID%","remote_path":"%F38_REMOTE_PATH%","runner_pid_requested":"321","runner_start_ticks_requested":"999","runner_pid_info":{"pid":"321","exists":true,"proc_start_ticks":999,"children":[]},"attempt_processes":[{"pid":"321","ppid":"1","cmdline":"python -u run_recovery_pf.py","proc_start_ticks":999,"matched_attempt_env":true,"matched_attempt_cmdline":false}],"ownership":{"original_runner_alive":true,"attempt_process_count":1,"closed":false},"artifact":{"path":"%F38_REMOTE_PATH%","exists":true,"size":128,"valid_json":true,"attempt_id":"%F38_ATTEMPT_ID%","case_id":"%F38_CASE_ID%","stage_reached":"full"}}
  ) else (
    echo {"probe_time_utc":"2026-08-12T00:00:00Z","attempt_id":"%F38_ATTEMPT_ID%","remote_path":"%F38_REMOTE_PATH%","runner_pid_requested":"321","runner_start_ticks_requested":"999","runner_pid_info":{"pid":"321","exists":false},"attempt_processes":[],"ownership":{"original_runner_alive":false,"attempt_process_count":0,"closed":true},"artifact":{"path":"%F38_REMOTE_PATH%","exists":true,"size":128,"valid_json":true,"attempt_id":"%F38_ATTEMPT_ID%","case_id":"%F38_CASE_ID%","stage_reached":"full"}}
  )
  exit /b 0
)
exit /b 0

:cp
set "SRC=%~2"
set "DST=%~3"
if "%SRC:~1,1%"==":" exit /b 0
echo %SRC% | findstr /c:"stdout.txt" >nul
if not errorlevel 1 (
  > "%DST%" echo === %F38_CASE_ID% mode=production_faithful ===
  exit /b 0
)
echo %SRC% | findstr /c:"stderr.txt" >nul
if not errorlevel 1 (
  if "%F38_SCENARIO%"=="missing_runner_identity" exit /b 0
  > "%DST%" echo [fresh38-lifecycle] {"event":"runner_start","attempt_id":"%F38_ATTEMPT_ID%","pid":321,"runner":{"pid":321,"ppid":1,"proc_start_ticks":999,"cmdline":"python -u run_recovery_pf.py"}}
  exit /b 0
)
if "%F38_ARTIFACT_MODE%"=="missing" exit /b 1
if "%F38_SCENARIO%"=="running_then_die" (
  if not exist "%F38_DIE_MARKER%" exit /b 1
)
> "%DST%" echo {"measurement_attempt":{"attempt_id":"%F38_ATTEMPT_ID%","artifact_path":"%F38_REMOTE_PATH%"},"cases":[{"id":"%F38_CASE_ID%","stage_reached":"full","case_product_outcome":"CASE_PRODUCT_PASS"}]}
exit /b 0
'@ | Set-Content -Path (Join-Path $shimDir 'docker.bat') -Encoding ASCII
    $env:PATH = "$shimDir;$env:PATH"
    $env:FRESH38_EXEC_CHANNEL = 'docker_cli'

    $corpus = Join-Path $root 'corpus-v2.json'
    Set-Content -Path $corpus -Value '{"cases":[{"id":"STUB-01"}]}' -Encoding UTF8
    $harness = Join-Path $Workspace 'scripts\fresh38'
    $env:F38_CASE_ID = 'STUB-01'

    function Invoke-Wrapper([string]$name, [string]$scenario, [string]$caseExit = '') {
        $attempt = "execinst$name"
        $outDir = Join-Path $root $name
        $env:F38_ATTEMPT_ID = $attempt
        $env:F38_REMOTE_PATH = "/tmp/fresh38-sentinel/$attempt/STUB-01/one-STUB-01.json"
        $env:F38_SCENARIO = $scenario
        $env:F38_CASE_EXIT = $caseExit
        $env:F38_ARTIFACT_MODE = 'valid'
        $env:F38_EVENT_FIRST = Join-Path $root "$name.event1"
        $env:F38_EVENT_SECOND = Join-Path $root "$name.event2"
        $env:F38_DIE_MARKER = Join-Path $root "$name.die"
        Remove-Item -LiteralPath $env:F38_EVENT_FIRST,$env:F38_EVENT_SECOND,$env:F38_DIE_MARKER -ErrorAction SilentlyContinue
        $argList = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Wrapper,
            '-CaseIds', 'STUB-01',
            '-OutDir', $outDir,
            '-Corpus', $corpus,
            '-HarnessDir', $harness,
            '-Container', 'stub-container',
            '-AttemptId', $attempt,
            '-NoReuse'
        )
        $output = & powershell @argList 2>&1 | Out-String
        return [pscustomobject]@{ Output = $output; ExitCode = $LASTEXITCODE; OutDir = $outDir; AttemptId = $attempt }
    }

    Write-Host "`n[1/11] Scenario A: normal execution accepts only after final Exec state"
    $normal = Invoke-Wrapper 'normal' 'normal'
    Check ($normal.ExitCode -eq 0) 'normal execution exits 0'
    Check ($normal.Output -match 'FRESH38_LIFECYCLE_DIAG=1') 'runner lifecycle diagnostics are enabled by default'
    Check ($normal.Output -match 'FRESH38_LIFECYCLE_DIAG_CASE=STUB-01') 'runner lifecycle diagnostics are scoped to the case'
    $normalEvidence = Get-Content (Join-Path $normal.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($normalEvidence.base.exact_docker_exec_id_capture -eq 'PASS') 'exact exec capture is PASS'
    Check ($normalEvidence.final_exec_inspect.Running -eq $false) 'final ExecInspect Running=false'
    Check ($normalEvidence.final_exec_inspect.ExitCode -eq 0) 'final ExecInspect ExitCode=0'
    Check (([string]$normalEvidence.base.host_docker_process.arguments) -match 'run_recovery_pf.py') 'host process argument string is captured'
    Check (([string]$normalEvidence.base.host_docker_process.file_name) -ne '') 'host process file name is captured'
    Check (([string]$normalEvidence.base.host_docker_process.arguments) -match 'runpy.run_path') 'exact Exec uses direct Python bootstrap'
    Check (([string]$normalEvidence.base.host_docker_process.arguments) -notmatch 'sh -lc') 'exact Exec does not insert a shell lifecycle owner'
    Check (([string]$normalEvidence.base.host_docker_process.arguments) -notmatch 'fresh38-attach-keepalive') 'exact Exec does not use attach heartbeat as lifecycle repair'
    Check (([string]$normalEvidence.base.remote_artifact_path) -match '/STUB-01/one-STUB-01.json$') 'remote artifact path is isolated per case'
    Check ($normalEvidence.attempt_process_ownership_closed -eq 'PASS') 'ownership is closed'
    Check ($normalEvidence.artifact_at_wrapper_validation.ok -eq $true) 'artifact accepted after lifecycle gates'

    Write-Host "`n[2/11] Scenario B: runner lifecycle proof comes from runner log, not Docker attach stream"
    $remoteLogs = Invoke-Wrapper 'remotelogs' 'remote_logs_only'
    Check ($remoteLogs.ExitCode -eq 0) 'remote log execution exits 0'
    $remoteLogsEvidence = Get-Content (Join-Path $remoteLogs.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($remoteLogsEvidence.base.runner_identity_from_lifecycle.pid -eq '321') 'runner identity is recovered from runner stderr log'
    Check ((Get-Content (Join-Path $remoteLogs.OutDir 'one-STUB-01-stderr.txt') -Raw) -match 'runner_start') 'runner stderr log is materialized locally'
    Check ($remoteLogsEvidence.measurement_verdict.measurement_qualification -eq 'QUALIFIED') 'missing attach stderr does not invalidate a completed owned Exec'

    Write-Host "`n[3/11] Scenario C: host exits 0 while exact Exec still runs; wrapper fails closed without waiting"
    $delayed = Invoke-Wrapper 'delayed' 'running_then_die'
    Check ($delayed.ExitCode -ne 0) 'running exact Exec exits non-zero'
    Check ($delayed.Output -match 'HOST_CLIENT_EARLY_EXIT') 'early host-client exit is logged'
    $delayedEvidence = Get-Content (Join-Path $delayed.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($delayedEvidence.host_client_early_exit -eq $true) 'HOST_CLIENT_EARLY_EXIT=true in evidence'
    Check ($delayedEvidence.measurement_verdict.execution_channel_integrity -eq 'FAIL') 'execution channel integrity fails'
    Check ($delayedEvidence.measurement_verdict.failure_subclass -eq 'DOCKER_ATTACH_LIFECYCLE_ANOMALY') 'Docker attach lifecycle anomaly is classified'
    Check ($delayedEvidence.measurement_verdict.measurement_qualification -eq 'NOT_QUALIFIED') 'running exact Exec is not qualified'
    Check ($delayedEvidence.artifact_at_wrapper_validation -eq $null) 'artifact is not copied after invalid L0'
    Check (-not (Test-Path (Join-Path $delayed.OutDir 'one-STUB-01.json'))) 'late artifact cannot rescue invalid L0'

    Write-Host "`n[4/11] Scenario D: exact Exec remains running at capture boundary"
    $timeout = Invoke-Wrapper 'timeout' 'exec_timeout'
    Check ($timeout.ExitCode -ne 0) 'running Exec exits non-zero'
    Check ($timeout.Output -match 'DOCKER_ATTACH_LIFECYCLE_ANOMALY') 'running Exec is classified at the boundary'
    $timeoutEvidence = Get-Content (Join-Path $timeout.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($timeoutEvidence.measurement_verdict.measurement_qualification -eq 'NOT_QUALIFIED') 'running Exec is not qualified'
    Check ($timeoutEvidence.artifact_at_wrapper_validation -eq $null) 'artifact is not validated after failed L0'

    Write-Host "`n[5/11] Scenario E: ambiguous or missing exact Exec ID fails closed"
    $ambiguous = Invoke-Wrapper 'ambiguous' 'ambiguous_exec_id'
    Check ($ambiguous.ExitCode -ne 0) 'ambiguous exec correlation exits non-zero'
    Check ($ambiguous.Output -match 'EXEC_IDENTITY_UNPROVEN') 'ambiguous correlation is classified'
    $missing = Invoke-Wrapper 'missing' 'missing_exec_id'
    Check ($missing.ExitCode -ne 0) 'missing exec event exits non-zero'
    Check ($missing.Output -match 'EXEC_IDENTITY_UNPROVEN') 'missing event is a hard instrumentation failure'

    Write-Host "`n[6/11] Scenario F: final Exec non-zero fails even if artifact would exist"
    $execNonZero = Invoke-Wrapper 'execnonzero' 'exec_nonzero'
    Check ($execNonZero.ExitCode -ne 0) 'final Exec non-zero exits non-zero'
    Check ($execNonZero.Output -match 'failure_class=EXEC_FAILURE') 'final Exec non-zero is classified'
    Check (-not (Test-Path (Join-Path $execNonZero.OutDir 'one-STUB-01.json'))) 'artifact is not accepted after final Exec non-zero'

    Write-Host "`n[7/11] Scenario G: surviving attempt writer fails ownership gate"
    $ownership = Invoke-Wrapper 'ownership' 'ownership_alive'
    Check ($ownership.ExitCode -ne 0) 'surviving writer exits non-zero'
    Check ($ownership.Output -match 'OWNERSHIP_FAILURE') 'ownership failure is classified'
    Check (-not (Test-Path (Join-Path $ownership.OutDir 'one-STUB-01.json'))) 'artifact is not accepted after ownership failure'

    Write-Host "`n[8/11] Scenario H: missing runner lifecycle identity fails ownership proof"
    $runnerMissing = Invoke-Wrapper 'runneridmissing' 'missing_runner_identity'
    Check ($runnerMissing.ExitCode -ne 0) 'missing runner identity exits non-zero'
    Check ($runnerMissing.Output -match 'RUNNER_IDENTITY_UNPROVEN') 'missing runner identity subclass is explicit'
    $runnerMissingEvidence = Get-Content (Join-Path $runnerMissing.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($runnerMissingEvidence.measurement_verdict.failure_class -eq 'OWNERSHIP_FAILURE') 'missing runner identity remains an ownership failure'
    Check ($runnerMissingEvidence.measurement_verdict.failure_subclass -eq 'RUNNER_IDENTITY_UNPROVEN') 'missing runner identity is not normalized'
    Check ($runnerMissingEvidence.artifact_at_wrapper_validation -eq $null) 'artifact is not accepted without runner identity proof'

    Write-Host "`n[9/11] Scenario I: event/inspect ExitCode disagreement fails explicitly"
    $mismatch = Invoke-Wrapper 'mismatch' 'exit_mismatch'
    Check ($mismatch.ExitCode -ne 0) 'exit-code mismatch exits non-zero'
    Check ($mismatch.Output -match 'EXEC_STATE_INCONSISTENCY') 'exit-code mismatch is classified'
    $mismatchEvidence = Get-Content (Join-Path $mismatch.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($mismatchEvidence.exec_event_inspect_exitcode_parity -eq 'FAIL') 'parity is FAIL, not manufactured PASS'

    Write-Host "`n[10/11] Host docker.exe non-zero with unknown exact Exec fails as channel integrity"
    $hostUnknown = Invoke-Wrapper 'hostunknown' 'missing_exec_id' '7'
    Check ($hostUnknown.ExitCode -ne 0) 'host docker non-zero with unknown Exec exits non-zero'
    Check ($hostUnknown.Output -match 'HOST_CLIENT_FAILURE_OR_UNKNOWN_EXEC') 'host non-zero unknown Exec is classified'
    $hostUnknownEvidence = Get-Content (Join-Path $hostUnknown.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($hostUnknownEvidence.measurement_verdict.failure_subclass -eq 'HOST_CLIENT_FAILURE_OR_UNKNOWN_EXEC') 'host non-zero unknown Exec subclass is explicit'

    Write-Host "`n[11/11] Host docker.exe non-zero is recorded after exact Exec evidence"
    $hostFail = Invoke-Wrapper 'hostfail' 'normal' '7'
    Check ($hostFail.ExitCode -ne 0) 'host docker non-zero exits non-zero'
    Check ($hostFail.Output -match 'HOST_CLIENT_FAILURE_OR_UNKNOWN_EXEC') 'host client failure is classified separately'
    $hostEvidence = Get-Content (Join-Path $hostFail.OutDir 'one-STUB-01-docker-exec-evidence.json') -Raw | ConvertFrom-Json
    Check ($hostEvidence.final_exec_inspect.ExitCode -eq 0) 'exact Exec final evidence is still inspected'
}
finally {
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
    Remove-Item Env:F38_ATTEMPT_ID -ErrorAction SilentlyContinue
    Remove-Item Env:F38_REMOTE_PATH -ErrorAction SilentlyContinue
    Remove-Item Env:F38_SCENARIO -ErrorAction SilentlyContinue
    Remove-Item Env:F38_CASE_ID -ErrorAction SilentlyContinue
    Remove-Item Env:F38_CASE_EXIT -ErrorAction SilentlyContinue
    Remove-Item Env:F38_ARTIFACT_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:F38_EVENT_FIRST -ErrorAction SilentlyContinue
    Remove-Item Env:F38_EVENT_SECOND -ErrorAction SilentlyContinue
    Remove-Item Env:F38_DIE_MARKER -ErrorAction SilentlyContinue
    Remove-Item Env:FRESH38_EXEC_CHANNEL -ErrorAction SilentlyContinue
}

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "FRESH38 EXEC LIFECYCLE: FAIL ($($failures.Count))" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host 'FRESH38 EXEC LIFECYCLE: PASS' -ForegroundColor Green
exit 0
