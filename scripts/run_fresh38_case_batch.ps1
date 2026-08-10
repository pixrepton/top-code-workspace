# Case-by-case Fresh 38 SUT capture into gmail-agent-nodeb-api.
# Avoids full-batch OOM (Exit2 137). Uses resilient per-case docker exec.

param(
    [string[]]$CaseIds = @(),
    [string]$OutDir = '',
    [string]$Corpus = '',
    [string]$HarnessDir = '',
    [string]$PatchedRunner = '',
    [string]$Container = 'gmail-agent-nodeb-api',
    [string]$Mode = 'production_faithful',
    # FIRST_ATTEMPT evidence is a reliability measurement and must never be overwritten by a
    # later retry. RECOVERY_ATTEMPT artifacts are written to a separate subdirectory.
    [ValidateSet('FIRST_ATTEMPT', 'RECOVERY_ATTEMPT')]
    [string]$AttemptType = 'FIRST_ATTEMPT',
    [int]$AttemptNumber = 1,
    # Hard guarantee for a canonical frozen run: refuse every reuse, even a matching one.
    [switch]$NoReuse,
    # SUT source root to fingerprint and hot-sync. Defaults to the real product tree; overridable
    # so the fingerprint mechanism itself can be tested against a controlled tree.
    [string]$SutSourceRoot = ''
)

$ErrorActionPreference = 'Continue'
$Workspace = Split-Path $PSScriptRoot -Parent
$AuditDir = Join-Path $Workspace 'gmail-agent\tools\gmail_audit'

function Get-Sha256([string]$path) {
    if (-not (Test-Path $path)) { return '' }
    return (Get-FileHash -Path $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

if (-not $Corpus) {
    $Corpus = Join-Path $AuditDir 'tests\fixtures\measurement_contract_v1\corpus-v2.json'
}
if (-not $HarnessDir) {
    # CL-03: the tracked canonical harness. Previously this defaulted into .artifacts\, which is
    # gitignored, so the runner could not be reconstructed from a fresh checkout at all.
    $HarnessDir = Join-Path $PSScriptRoot 'fresh38'
}
# Runner provenance (FIX-MEAS01): one canonical source, mechanically verified against a
# tracked hash pin. The previous default preferred an opaque session-scratch copy and fell
# back silently, so a canonical qualification run depended on a file nobody could verify.
$ProvenancePath = Join-Path $PSScriptRoot 'fresh38_runner_provenance.json'
$Provenance = $null
if (Test-Path $ProvenancePath) {
    $Provenance = Get-Content $ProvenancePath -Raw -Encoding UTF8 | ConvertFrom-Json
}
if (-not $PatchedRunner) {
    $PatchedRunner = Join-Path $HarnessDir 'run_recovery_pf.py'
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

Log "START cases=$($CaseIds -join ',') attempt=$AttemptType#$AttemptNumber"
Log "runner=$PatchedRunner"
Log "corpus=$Corpus"

# docker must be usable before anything else. Without this check a missing docker on PATH
# still produced an experiment manifest and a "synced" log line for every product file, while
# nothing was actually copied into the container -- a capture that looks provisioned and is not.
$null = & docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -ne 0) {
    Log "ABORT docker is not available on PATH; cannot provision or run a capture"
    exit 2
}

$runnerSha = Get-Sha256 $PatchedRunner
if (-not $runnerSha) {
    Log "ABORT runner not found: $PatchedRunner"
    exit 2
}
if ($Provenance -and $Provenance.canonical_runner.sha256) {
    $expected = [string]$Provenance.canonical_runner.sha256
    if ($runnerSha -ne $expected) {
        Log "ABORT RUNNER_PROVENANCE_MISMATCH expected=$expected actual=$runnerSha path=$PatchedRunner"
        Log "      A capture must never run on an unverified harness. Update scripts/fresh38_runner_provenance.json"
        Log "      in the same commit as the harness change if this difference is intentional."
        exit 2
    }
    Log "runner_provenance=VERIFIED sha256=$runnerSha path=$PatchedRunner"
} else {
    Log "runner_provenance=UNPINNED sha256=$runnerSha"
}

# There must be exactly one canonical runner. A leftover copy that has drifted is reported
# rather than left to be picked up by some other tool that still points at the old location.
if ($Provenance -and $Provenance.deprecated_copies) {
    foreach ($stale in $Provenance.deprecated_copies) {
        $stalePath = [string]$stale.path
        if (-not [System.IO.Path]::IsPathRooted($stalePath)) {
            $stalePath = Join-Path $Workspace $stalePath
        }
        $staleSha = Get-Sha256 $stalePath
        if ($staleSha -and $staleSha -ne $runnerSha -and $stale.path -like '*run_recovery_pf*') {
            Log "WARN DEPRECATED_RUNNER_COPY_DIVERGED path=$($stale.path) sha256=$staleSha (canonical=$runnerSha)"
        }
    }
}

docker exec $Container sh -lc 'mkdir -p /tmp/fresh38-sentinel' | Out-Null
docker cp $PatchedRunner "${Container}:/tmp/fresh38-sentinel/run_recovery_pf.py"
docker cp (Join-Path $HarnessDir 'scoring.py') "${Container}:/tmp/fresh38-sentinel/scoring.py"
docker cp $Corpus "${Container}:/tmp/fresh38-sentinel/corpus-v2.json"

# ── SUT source set (CL-04) ──────────────────────────────────────────────────────────────
# Derived, never hand-curated. A hand-maintained hot-sync list has a structural blind spot: a
# product dependency that is not on the list can change the running code without changing the
# manifest hash, which is exactly how the 21/38 run was contaminated. Adding "a few more files"
# would not close the class -- only mechanical enumeration does.
#
# The set is every .py under the SUT source root, minus directories that are not executed
# product code. Enumeration is deterministic: ordinal-sorted, forward-slash relative paths,
# content hashes only -- no timestamps, no temp paths, no filesystem ordering.
if (-not $SutSourceRoot) { $SutSourceRoot = $AuditDir }
$SutSourceRoot = (Resolve-Path $SutSourceRoot).Path
$SutExcludedDirs = @('tests', '__pycache__', 'runs', 'data', '.pytest_cache', 'scripts', '.venv')

$sutFiles = Get-ChildItem -Path $SutSourceRoot -Recurse -File -Filter '*.py' |
    ForEach-Object {
        $rel = $_.FullName.Substring($SutSourceRoot.Length).TrimStart('\', '/') -replace '\\', '/'
        [pscustomobject]@{ Rel = $rel; Full = $_.FullName }
    } |
    Where-Object {
        $segments = $_.Rel.Split('/')
        $dirSegments = $segments[0..([Math]::Max(0, $segments.Count - 2))]
        if ($segments.Count -eq 1) { $dirSegments = @() }
        -not ($dirSegments | Where-Object { $SutExcludedDirs -contains $_ })
    } |
    Sort-Object -Property @{ Expression = { $_.Rel }; Ascending = $true }

$syncedHashes = [ordered]@{}
foreach ($f in $sutFiles) {
    $syncedHashes[$f.Rel] = Get-Sha256 $f.Full
}
Log "sut_source_files=$($syncedHashes.Count) root=tools/gmail_audit excluded=$($SutExcludedDirs -join ',')"

# Hotfix the whole SUT source set into the running container so the capture executes exactly the
# code that was fingerprinted. Staged and copied in one `docker cp` rather than per file: 361
# individual copies would be slow, and a partial failure mid-list is precisely the silent-drift
# failure this section exists to remove.
$stageDir = Join-Path ([System.IO.Path]::GetTempPath()) ("fresh38-sut-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
try {
    foreach ($f in $sutFiles) {
        $dest = Join-Path $stageDir ($f.Rel -replace '/', '\')
        $destParent = Split-Path $dest -Parent
        if (-not (Test-Path $destParent)) { New-Item -ItemType Directory -Force -Path $destParent | Out-Null }
        Copy-Item -LiteralPath $f.Full -Destination $dest -Force
    }
    docker cp "$stageDir\." "${Container}:/app/tools/gmail_audit/" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # A silently failed hot-sync is the original contamination mechanism: the manifest would
        # record host hashes while the container still ran older code.
        Log "ABORT SUT hot-sync failed (docker cp exit=$LASTEXITCODE)"
        exit 2
    }
    Log "synced SUT source set ($($syncedHashes.Count) files) in one transfer"
} finally {
    Remove-Item -Recurse -Force $stageDir -ErrorAction SilentlyContinue
}

# ── Experiment manifest fingerprint (FIX-MEAS01) ────────────────────────────────────────
# The previous reuse gate checked only `parity_error`, with no proof that an existing artifact
# came from the same SUT. That silently mixed two different preclassifier states into one
# "clean" 21/38 result: 37 of 38 cases were reused from a cache captured before a hot-sync fix.
# Every artifact is now bound to the identity of the code that produced it, and reuse requires
# an exact match.
$imageId = (docker inspect --format '{{.Image}}' $Container 2>$null | Select-Object -First 1)
if (-not $imageId) {
    # The image id is part of the SUT identity; an 'unknown' placeholder would let two different
    # runtimes share one manifest hash, which is exactly what this fingerprint exists to prevent.
    Log "ABORT cannot resolve container image id for $Container"
    exit 2
}

$fingerprintParts = [ordered]@{
    wrapper_sha256  = Get-Sha256 $PSCommandPath
    runner_sha256   = $runnerSha
    scoring_sha256  = Get-Sha256 (Join-Path $HarnessDir 'scoring.py')
    corpus_sha256   = Get-Sha256 $Corpus
    container_image = [string]$imageId
    mode            = $Mode
    sut_source_root = 'gmail-agent/tools/gmail_audit'
    sut_excluded    = $SutExcludedDirs
    product_files   = $syncedHashes
}
$fingerprintJson = $fingerprintParts | ConvertTo-Json -Depth 10 -Compress
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $ExperimentManifestHash = -join (
        $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($fingerprintJson)) |
            ForEach-Object { $_.ToString('x2') }
    )
} finally {
    $sha.Dispose()
}

$experimentManifest = [ordered]@{
    experiment_manifest_hash = $ExperimentManifestHash
    attempt_type             = $AttemptType
    attempt_number           = $AttemptNumber
    out_dir                  = $OutDir
    container                = $Container
    created_at               = (Get-Date).ToString('o')
    components               = $fingerprintParts
    sut_source_file_count    = $syncedHashes.Count
}
($experimentManifest | ConvertTo-Json -Depth 12) |
    Set-Content (Join-Path $OutDir 'experiment-manifest.json') -Encoding UTF8

Log "experiment_manifest_hash=$ExperimentManifestHash"
Log "sut_source_files_fingerprinted=$($syncedHashes.Count)"

# RECOVERY_ATTEMPT artifacts live in their own subtree so a later retry can never overwrite,
# or be confused with, first-attempt reliability evidence.
$ArtifactDir = $OutDir
if ($AttemptType -eq 'RECOVERY_ATTEMPT') {
    $ArtifactDir = Join-Path $OutDir ("recovery-attempt-{0}" -f $AttemptNumber)
    New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
    Log "recovery artifacts -> $ArtifactDir (first-attempt evidence untouched)"
}

$merged = @{
    mode = $Mode
    cases = @()
    capture_tool = 'scripts/run_fresh38_case_batch.ps1'
    started_at = (Get-Date).ToString('o')
    experiment_manifest_hash = $ExperimentManifestHash
    attempt_type = $AttemptType
    attempt_number = $AttemptNumber
}
$failed = @()
$ok = @()

foreach ($cid in $CaseIds) {
    $stdout = Join-Path $ArtifactDir "one-$cid-stdout.txt"
    $stderr = Join-Path $ArtifactDir "one-$cid-stderr.txt"
    $local = Join-Path $ArtifactDir "one-$cid.json"
    $sidecar = Join-Path $ArtifactDir "one-$cid.manifest.json"
    if ((Test-Path $local) -and -not $NoReuse) {
        try {
            # Provenance gate first: an artifact whose SUT identity is unknown or different is
            # not evidence about this SUT, no matter how valid it looks on its own.
            $artifactHash = ''
            $artifactAttempt = ''
            if (Test-Path $sidecar) {
                $sc = Get-Content $sidecar -Raw -Encoding UTF8 | ConvertFrom-Json
                $artifactHash = [string]$sc.experiment_manifest_hash
                $artifactAttempt = [string]$sc.attempt_type
            }
            if (-not $artifactHash) {
                Log "REUSE_REJECT_SUT_MISMATCH $cid reason=no_manifest_sidecar"
            } elseif ($artifactHash -ne $ExperimentManifestHash) {
                Log "REUSE_REJECT_SUT_MISMATCH $cid artifact=$artifactHash current=$ExperimentManifestHash"
            } elseif ($artifactAttempt -ne $AttemptType) {
                Log "REUSE_REJECT_ATTEMPT_MISMATCH $cid artifact=$artifactAttempt current=$AttemptType"
            } else {
                $existing = Get-Content $local -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($existing.cases) {
                    $parityErrors = @()
                    foreach ($nc in @($existing.cases)) {
                        if ($nc.parity_error) {
                            $parityErrors += [string]$nc.parity_error
                        }
                    }
                    if ($parityErrors.Count -gt 0) {
                        Log "REUSE_SKIP $cid parity_error=$($parityErrors -join '|')"
                    } else {
                        foreach ($nc in @($existing.cases)) {
                            $merged.cases += $nc
                        }
                        $ok += $cid
                        Log "REUSE $cid manifest=$artifactHash"
                        continue
                    }
                } else {
                    Log "REUSE_SKIP $cid missing cases"
                }
            }
        } catch {
            Log "REUSE_SKIP $cid parse: $($_.Exception.Message)"
        }
    } elseif ((Test-Path $local) -and $NoReuse) {
        Log "REUSE_DISABLED $cid recapturing under -NoReuse"
    }
    Log "START $cid"
    $remoteOut = "/tmp/fresh38-sentinel/one-$cid.json"
    # Use cmd redirection so docker JSON logs on stderr do not become PowerShell errors.
    cmd /c "docker exec -w /tmp/fresh38-sentinel $Container python run_recovery_pf.py $Mode corpus-v2.json $remoteOut $cid > `"$stdout`" 2> `"$stderr`""
    $ec = $LASTEXITCODE
    $hasOut = $false
    if ($ec -eq 0) {
        docker cp "${Container}:$remoteOut" $local 2>$null
        $hasOut = Test-Path $local
    }
    if ($hasOut) {
        # Bind the artifact to the SUT that produced it, before anything can consume it.
        ([ordered]@{
            case_id                  = $cid
            experiment_manifest_hash = $ExperimentManifestHash
            attempt_type             = $AttemptType
            attempt_number           = $AttemptNumber
            captured_at              = (Get-Date).ToString('o')
            artifact_sha256          = Get-Sha256 $local
            container                = $Container
            mode                     = $Mode
        } | ConvertTo-Json -Depth 6) | Set-Content $sidecar -Encoding UTF8
    }
    if (-not $hasOut) {
        Log "FAIL $cid exit=$ec"
        $failed += $cid
        continue
    }
    try {
        $j = Get-Content $local -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($j.cases) {
            $parityErrors = @()
            foreach ($nc in @($j.cases)) {
                if ($nc.parity_error) {
                    $parityErrors += [string]$nc.parity_error
                }
            }
            if ($parityErrors.Count -gt 0) {
                Log "FAIL $cid parity_error=$($parityErrors -join '|')"
                $failed += $cid
                continue
            }
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
$resultsName = if ($AttemptType -eq 'RECOVERY_ATTEMPT') {
    "fresh38-recovery-attempt-$AttemptNumber-results.json"
} else {
    'fresh38-partial-results.json'
}
($merged | ConvertTo-Json -Depth 40) | Set-Content (Join-Path $ArtifactDir $resultsName) -Encoding UTF8

Log "DONE ok=$($ok.Count) failed=$($failed.Count) attempt=$AttemptType#$AttemptNumber out=$ArtifactDir"
if ($failed.Count -gt 0) { exit 1 }
exit 0
