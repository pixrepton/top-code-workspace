# CL-04 proof: the SUT fingerprint must have no hand-curated blind spot.
#
# The wrapper used to hot-sync and fingerprint a hand-maintained list of ~25 product files. That
# list is structurally incomplete: a runtime-relevant dependency that nobody remembered to add
# could change the running code while the manifest hash stayed identical, so a stale artifact
# would still be accepted for reuse. Adding "a few more files" does not close the class.
#
# The set is now derived by enumerating the SUT source root. These tests prove the properties the
# curated list could not offer, using a controlled tree and a stubbed docker.
#
# Run:  powershell -NoProfile -File scripts/tests/test_fresh38_sut_fingerprint.ps1

$ErrorActionPreference = 'Stop'
$Workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Wrapper = Join-Path $Workspace 'scripts\run_fresh38_case_batch.ps1'

$failures = @()
function Check([bool]$condition, [string]$label) {
    if ($condition) { Write-Host "  PASS  $label" }
    else { Write-Host "  FAIL  $label" -ForegroundColor Red; $script:failures += $label }
}

$root = Join-Path ([System.IO.Path]::GetTempPath()) ("f38-fp-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $root | Out-Null

try {
    # ── docker stub (pure batch: a PowerShell -File shim would try to bind docker's -w) ──
    $shimDir = Join-Path $root 'shim'
    New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
    @'
@echo off
if "%~1"=="inspect" (echo sha256:stubimage0001& exit /b 0)
if "%~1"=="cp" goto :cp
exit /b 0
:cp
set "SRC=%~2"
set "DST=%~3"
if "%SRC:~1,1%"==":" exit /b 0
> "%DST%" echo {"cases":[{"case_id":"STUB-01","valid":true}]}
exit /b 0
'@ | Set-Content -Path (Join-Path $shimDir 'docker.bat') -Encoding ASCII
    $env:PATH = "$shimDir;$env:PATH"

    # ── a controlled SUT tree ────────────────────────────────────────────────────────────
    $sut = Join-Path $root 'sut'
    New-Item -ItemType Directory -Force -Path (Join-Path $sut 'agent_runtime\tools') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $sut 'tests') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $sut '__pycache__') | Out-Null

    Set-Content (Join-Path $sut 'gmail_intake.py')                  'v1' -Encoding UTF8
    Set-Content (Join-Path $sut 'agent_runtime\tools\handlers.py')  'v1' -Encoding UTF8
    # A real runtime dependency that no curated list ever mentioned:
    Set-Content (Join-Path $sut 'obscure_runtime_dependency.py')    'v1' -Encoding UTF8
    # Outside the SUT: tests, bytecode, and a non-Python file
    Set-Content (Join-Path $sut 'tests\test_something.py')          'v1' -Encoding UTF8
    Set-Content (Join-Path $sut '__pycache__\cached.py')            'v1' -Encoding UTF8
    Set-Content (Join-Path $sut 'notes.txt')                        'v1' -Encoding UTF8

    $corpus = Join-Path $root 'corpus-v2.json'
    Set-Content $corpus '{"cases":[{"case_id":"STUB-01"}]}' -Encoding UTF8

    $canonicalRunner = Join-Path $Workspace 'scripts\fresh38\run_recovery_pf.py'
    if (-not (Test-Path $canonicalRunner)) {
        Write-Host "SKIP: tracked canonical runner missing at $canonicalRunner" -ForegroundColor Yellow
        exit 0
    }

    function Get-ManifestHash([string]$outDir) {
        $argList = @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Wrapper,
            '-CaseIds', 'STUB-01',
            '-OutDir', $outDir,
            '-Corpus', $corpus,
            '-Container', 'stub-container',
            '-SutSourceRoot', $sut
        )
        $null = & powershell @argList 2>&1
        $manifest = Get-Content (Join-Path $outDir 'experiment-manifest.json') -Raw | ConvertFrom-Json
        return $manifest
    }

    Write-Host "`n[1/6] enumeration is deterministic and excludes non-SUT directories"
    $m1 = Get-ManifestHash (Join-Path $root 'out1')
    $m1b = Get-ManifestHash (Join-Path $root 'out1b')
    Check ($m1.experiment_manifest_hash -eq $m1b.experiment_manifest_hash) 'two runs over an unchanged tree produce the same hash'
    $names = @($m1.components.product_files.PSObject.Properties.Name)
    Check ($names -contains 'gmail_intake.py') 'top-level product file is fingerprinted'
    Check ($names -contains 'agent_runtime/tools/handlers.py') 'nested product file is fingerprinted with a forward-slash path'
    Check ($names -contains 'obscure_runtime_dependency.py') 'a dependency no curated list mentioned is fingerprinted'
    Check (-not ($names -contains 'tests/test_something.py')) 'tests are excluded from the SUT'
    Check (-not ($names -contains '__pycache__/cached.py')) 'bytecode cache is excluded'
    Check ($m1.sut_source_file_count -eq $names.Count) 'manifest records the fingerprinted file count'

    Write-Host "`n[2/6] changing a file that was on the old curated list changes the manifest"
    Set-Content (Join-Path $sut 'gmail_intake.py') 'v2' -Encoding UTF8
    $m2 = Get-ManifestHash (Join-Path $root 'out2')
    Check ($m2.experiment_manifest_hash -ne $m1.experiment_manifest_hash) 'known-file change invalidates the fingerprint'

    Write-Host "`n[3/6] the blind spot: changing a NEVER-listed dependency changes the manifest"
    Set-Content (Join-Path $sut 'obscure_runtime_dependency.py') 'v2' -Encoding UTF8
    $m3 = Get-ManifestHash (Join-Path $root 'out3')
    Check ($m3.experiment_manifest_hash -ne $m2.experiment_manifest_hash) 'unlisted runtime dependency change invalidates the fingerprint'

    Write-Host "`n[4/6] changes outside the SUT do not invalidate the fingerprint"
    Set-Content (Join-Path $sut 'tests\test_something.py') 'v2' -Encoding UTF8
    Set-Content (Join-Path $sut 'notes.txt') 'v2' -Encoding UTF8
    Set-Content (Join-Path $sut '__pycache__\cached.py') 'v2' -Encoding UTF8
    $m4 = Get-ManifestHash (Join-Path $root 'out4')
    Check ($m4.experiment_manifest_hash -eq $m3.experiment_manifest_hash) 'test/bytecode/non-python changes do not invalidate a valid run'

    Write-Host "`n[5/6] adding a new product module invalidates the fingerprint"
    Set-Content (Join-Path $sut 'brand_new_module.py') 'v1' -Encoding UTF8
    $m5 = Get-ManifestHash (Join-Path $root 'out5')
    Check ($m5.experiment_manifest_hash -ne $m4.experiment_manifest_hash) 'a newly added product module is picked up automatically'

    Write-Host "`n[6/6] the fingerprint carries no volatile input"
    $componentJson = $m5.components | ConvertTo-Json -Depth 12
    Check ($componentJson -notmatch 'Temp\\\\|/Temp/') 'no temp paths in the fingerprint'
    Check ($componentJson -notmatch '\d{4}-\d{2}-\d{2}T\d{2}:') 'no timestamps in the fingerprint'
    Check ([bool]$m5.components.sut_source_root) 'fingerprint records the SUT source root it enumerated'
}
finally {
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "FRESH38 SUT FINGERPRINT: FAIL ($($failures.Count))" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host 'FRESH38 SUT FINGERPRINT: PASS' -ForegroundColor Green
exit 0
