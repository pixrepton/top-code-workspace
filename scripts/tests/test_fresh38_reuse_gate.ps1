# FIX-MEAS01 proof: the Fresh38 capture wrapper must never reuse an artifact from a different SUT.
#
# The defect this covers wasted a full benchmark run. run_fresh38_case_batch.ps1 resumed a case
# whenever one-<CASE>.json existed and carried no parity_error -- with no proof the artifact came
# from the same system under test. In the 21/38 run, 37 of 38 cases were silently reused from a
# cache captured *before* a preclassifier hot-sync fix, so one "clean" number described two
# different SUTs.
#
# docker is stubbed so this is deterministic and needs no live container or provider.
# Run:  powershell -NoProfile -File scripts/tests/test_fresh38_reuse_gate.ps1

$ErrorActionPreference = 'Stop'
$Workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Wrapper = Join-Path $Workspace 'scripts\run_fresh38_case_batch.ps1'

$failures = @()
function Check([bool]$condition, [string]$label) {
    if ($condition) {
        Write-Host "  PASS  $label"
    } else {
        Write-Host "  FAIL  $label" -ForegroundColor Red
        $script:failures += $label
    }
}

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("fresh38-gate-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $root | Out-Null

try {
    # ── docker stub ────────────────────────────────────────────────────────────────────
    $shimDir = Join-Path $root 'shim'
    New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
    # Pure batch on purpose: the wrapper invokes `docker exec -w <dir> ...`, and a PowerShell
    # shim launched with -File would try to bind `-w` as one of its own parameters and fail
    # before ever seeing the arguments.
    @'
@echo off
if "%~1"=="inspect" (echo sha256:stubimage0001& exit /b 0)
if "%~1"=="cp" goto :cp
exit /b 0
:cp
set "SRC=%~2"
set "DST=%~3"
rem A Windows source path (C:\...) is a push into the container: nothing to do.
if "%SRC:~1,1%"==":" exit /b 0
rem Otherwise this is a pull from the container: synthesize a valid one-CASE artifact.
> "%DST%" echo {"cases":[{"case_id":"STUB-01","valid":true}]}
exit /b 0
'@ | Set-Content -Path (Join-Path $shimDir 'docker.bat') -Encoding ASCII

    $env:PATH = "$shimDir;$env:PATH"

    # ── fixtures ───────────────────────────────────────────────────────────────────────
    $harness = Join-Path $root 'harness'
    New-Item -ItemType Directory -Force -Path $harness | Out-Null
    Set-Content -Path (Join-Path $harness 'scoring.py') -Value 'print("stub scoring")' -Encoding UTF8

    # The runner must be the real canonical one: the wrapper verifies it against the tracked
    # provenance pin before doing anything. It is never executed here (docker is stubbed), so
    # this exercises the provenance check without running a real capture.
    $canonicalRunner = Join-Path $Workspace '.artifacts\ai-os-post-stage6-fresh-baseline\harness\run_recovery_pf.py'
    if (-not (Test-Path $canonicalRunner)) {
        Write-Host "SKIP: canonical runner not present at $canonicalRunner" -ForegroundColor Yellow
        exit 0
    }
    $stubRunner = Join-Path $harness 'run_recovery_pf.py'
    Set-Content -Path $stubRunner -Value 'print("stub runner")' -Encoding UTF8

    $corpus = Join-Path $root 'corpus-v2.json'
    Set-Content -Path $corpus -Value '{"cases":[{"case_id":"STUB-01"}]}' -Encoding UTF8

    $outDir = Join-Path $root 'out'

    function Invoke-Wrapper([string[]]$extra, [string]$runner = '') {
        if (-not $runner) { $runner = $canonicalRunner }
        $argList = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Wrapper,
            '-CaseIds', 'STUB-01',
            '-OutDir', $outDir,
            '-Corpus', $corpus,
            '-HarnessDir', $harness,
            '-PatchedRunner', $runner,
            '-Container', 'stub-container'
        ) + $extra
        $out = & powershell @argList 2>&1 | Out-String
        return $out
    }

    Write-Host "`n[0/5] an unverified runner aborts the capture (runner provenance)"
    $log0 = Invoke-Wrapper @() $stubRunner
    Check ($log0 -match 'RUNNER_PROVENANCE_MISMATCH') 'a runner that fails its hash pin aborts the run'
    Check (-not (Test-Path (Join-Path $outDir 'experiment-manifest.json'))) 'no manifest is produced by an aborted run'

    Write-Host "`n[1/5] first capture writes a manifest-bound artifact"
    $log1 = Invoke-Wrapper @()
    Check ($log1 -match 'experiment_manifest_hash=[0-9a-f]{64}') 'experiment manifest hash is computed'
    Check (Test-Path (Join-Path $outDir 'experiment-manifest.json')) 'experiment-manifest.json is written'
    Check (Test-Path (Join-Path $outDir 'one-STUB-01.manifest.json')) 'per-case manifest sidecar is written'
    $sidecar = Get-Content (Join-Path $outDir 'one-STUB-01.manifest.json') -Raw | ConvertFrom-Json
    Check ($sidecar.attempt_type -eq 'FIRST_ATTEMPT') 'sidecar records attempt_type=FIRST_ATTEMPT'
    Check ($sidecar.attempt_number -eq 1) 'sidecar records attempt_number'
    Check ([bool]$sidecar.artifact_sha256) 'sidecar records the artifact hash'

    Write-Host "`n[2/5] unchanged SUT is allowed to reuse"
    $log2 = Invoke-Wrapper @()
    Check ($log2 -match 'REUSE STUB-01') 'identical SUT reuses the existing artifact'
    Check ($log2 -notmatch 'REUSE_REJECT') 'no spurious rejection on an identical SUT'

    Write-Host "`n[3/5] changed SUT must be rejected, not silently reused"
    # Any component of the fingerprint changing is enough; the corpus stands in for a product change.
    Set-Content -Path $corpus -Value '{"cases":[{"case_id":"STUB-01","changed":true}]}' -Encoding UTF8
    $log3 = Invoke-Wrapper @()
    Check ($log3 -match 'REUSE_REJECT_SUT_MISMATCH STUB-01') 'changed SUT triggers REUSE_REJECT_SUT_MISMATCH'
    Check ($log3 -notmatch 'REUSE STUB-01 manifest') 'changed SUT does not reuse'
    Check ($log3 -match 'OK STUB-01') 'changed SUT recaptures the case'

    Write-Host "`n[4/5] recovery attempts never overwrite first-attempt evidence"
    $firstArtifact = Join-Path $outDir 'one-STUB-01.json'
    $firstHashBefore = (Get-FileHash $firstArtifact -Algorithm SHA256).Hash
    $log4 = Invoke-Wrapper @('-AttemptType', 'RECOVERY_ATTEMPT', '-AttemptNumber', '1')
    $recoveryDir = Join-Path $outDir 'recovery-attempt-1'
    Check (Test-Path (Join-Path $recoveryDir 'one-STUB-01.json')) 'recovery artifact is written to its own subdirectory'
    Check ((Get-FileHash $firstArtifact -Algorithm SHA256).Hash -eq $firstHashBefore) 'first-attempt artifact is byte-identical after a recovery run'
    $recSidecar = Get-Content (Join-Path $recoveryDir 'one-STUB-01.manifest.json') -Raw | ConvertFrom-Json
    Check ($recSidecar.attempt_type -eq 'RECOVERY_ATTEMPT') 'recovery sidecar records attempt_type=RECOVERY_ATTEMPT'
    Check ($log4 -match 'recovery artifacts ->') 'recovery routing is logged'

    Write-Host "`n[extra] -NoReuse forces a recapture even on an identical SUT"
    $log5 = Invoke-Wrapper @('-NoReuse')
    Check ($log5 -match 'REUSE_DISABLED STUB-01') '-NoReuse bypasses the reuse path entirely'
}
finally {
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "FRESH38 REUSE GATE: FAIL ($($failures.Count))" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host 'FRESH38 REUSE GATE: PASS' -ForegroundColor Green
exit 0
