param(
    [Parameter(Mandatory = $true)]
    [string]$MessageId,

    [string]$ProofDir = "",

    [string]$PreviousProofDir = "",

    [switch]$SkipDaszekRecreate,

    [switch]$SimulateFailureAfterWorkerStop,

    [switch]$SimulateFailureAfterProofApiStart,

    [switch]$SimulateFailureBeforeBrowserProof
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$env:COMPOSE_STATUS_STDOUT = '1'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

$workspaceRoot = $env:TOP_CODE_ROOT
$gmailRoot = Join-Path $workspaceRoot 'gmail-agent'
$syncScript = Join-Path $workspaceRoot 'scripts\sync-local-stack-env.ps1'
$preflightScript = Join-Path $workspaceRoot 'scripts\preflight-local-stack.ps1'
$daszekCompose = Join-Path $workspaceRoot 'docker-compose.daszek-local.yml'
$browserHarness = Join-Path $workspaceRoot 'scripts\row4a_browser_proof.py'
$nodebApiContainer = 'gmail-agent-nodeb-api'
$workerContainerName = 'gmail-agent-vps-gmail-agent-worker-1'

if (-not $ProofDir) {
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $ProofDir = "C:\gate-b-row4a-local-proof-$stamp"
}

$proofPath = [System.IO.Path]::GetFullPath($ProofDir)
if (Test-Path -LiteralPath $proofPath) {
    throw "ProofDir already exists: $proofPath"
}

$dockerProofPath = $proofPath -replace '\\', '/'
$activationDir = Join-Path $proofPath 'activation'
$logsDir = Join-Path $proofPath 'logs'
$row31Dir = Join-Path $proofPath 'row3-1'
$row4Dir = Join-Path $proofPath 'row4'
$browserDir = Join-Path $proofPath 'browser'
$runtimeEnvDir = Join-Path $proofPath 'runtime-env'
$generatedLocalEnvPath = Join-Path $runtimeEnvDir 'gmail-agent.env'
$generatedAuditEnvPath = Join-Path $runtimeEnvDir 'audit.env'
$composeOverridePath = Join-Path $runtimeEnvDir 'docker-compose.row4a.override.yml'
$generatedLocalEnvForCompose = $generatedLocalEnvPath -replace '\\', '/'

foreach ($dir in @($proofPath, $activationDir, $logsDir, $row31Dir, $row4Dir, $browserDir, $runtimeEnvDir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}

$composeOverride = @'
services:
  gmail-agent-nodeb-api:
    environment:
      GMAIL_AGENT_ENV_FILE: /app/proof-env/gmail-agent.env
    volumes:
      - type: bind
        source: ${ROW4A_GENERATED_ENV_FILE}
        target: /app/proof-env/gmail-agent.env
        read_only: true
  gmail-agent-worker:
    environment:
      GMAIL_AGENT_ENV_FILE: /app/proof-env/gmail-agent.env
    volumes:
      - type: bind
        source: ${ROW4A_GENERATED_ENV_FILE}
        target: /app/proof-env/gmail-agent.env
        read_only: true
'@
Set-Content -Encoding utf8 -LiteralPath $composeOverridePath -Value $composeOverride
$env:ROW4A_GENERATED_ENV_FILE = $generatedLocalEnvForCompose

$runtimeHashSpecs = @(
    [ordered]@{ Label = 'gmail_intake'; HostPath = 'tools\gmail_audit\gmail_intake.py'; ContainerPath = '/app/tools/gmail_audit/gmail_intake.py' },
    [ordered]@{ Label = 'intake_schema'; HostPath = 'tools\gmail_audit\intake_schema.py'; ContainerPath = '/app/tools/gmail_audit/intake_schema.py' },
    [ordered]@{ Label = 'projection_proof_report'; HostPath = 'tools\gmail_audit\projection_proof_report.py'; ContainerPath = '/app/tools/gmail_audit/projection_proof_report.py' },
    [ordered]@{ Label = 'agent_runtime_settings'; HostPath = 'tools\gmail_audit\agent_runtime\settings.py'; ContainerPath = '/app/tools/gmail_audit/agent_runtime/settings.py' },
    [ordered]@{ Label = 'agent_reconcile'; HostPath = 'tools\gmail_audit\agent_runtime\agent_reconcile.py'; ContainerPath = '/app/tools/gmail_audit/agent_runtime/agent_reconcile.py' },
    [ordered]@{ Label = 'engagement_store'; HostPath = 'tools\gmail_audit\agent_runtime\store.py'; ContainerPath = '/app/tools/gmail_audit/agent_runtime/store.py' },
    [ordered]@{ Label = 'engagement_snapshot_v2'; HostPath = 'tools\gmail_audit\llm_contracts\engagement_snapshot_v2.py'; ContainerPath = '/app/tools/gmail_audit/llm_contracts/engagement_snapshot_v2.py' },
    [ordered]@{ Label = 'daszek_v3_feed_runtime'; HostPath = 'tools\gmail_audit\daszek_v3_feed_runtime.py'; ContainerPath = '/app/tools/gmail_audit/daszek_v3_feed_runtime.py' },
    [ordered]@{ Label = 'engagement_feed_init'; HostPath = 'tools\gmail_audit\daszek_engagement_feed\__init__.py'; ContainerPath = '/app/tools/gmail_audit/daszek_engagement_feed/__init__.py' },
    [ordered]@{ Label = 'engagement_feed_build'; HostPath = 'tools\gmail_audit\daszek_engagement_feed\build.py'; ContainerPath = '/app/tools/gmail_audit/daszek_engagement_feed/build.py' },
    [ordered]@{ Label = 'engagement_feed_desk'; HostPath = 'tools\gmail_audit\daszek_engagement_feed\desk.py'; ContainerPath = '/app/tools/gmail_audit/daszek_engagement_feed/desk.py' },
    [ordered]@{ Label = 'engagement_feed_case'; HostPath = 'tools\gmail_audit\daszek_engagement_feed\case.py'; ContainerPath = '/app/tools/gmail_audit/daszek_engagement_feed/case.py' },
    [ordered]@{ Label = 'event_spine_query'; HostPath = 'tools\gmail_audit\event_spine\query.py'; ContainerPath = '/app/tools/gmail_audit/event_spine/query.py' },
    [ordered]@{ Label = 'sequential_runner'; HostPath = 'scripts\sequential_gmail_ingress_daszek.py'; ContainerPath = '/app/scripts/sequential_gmail_ingress_daszek.py' }
)

$canonicalEnvPaths = @(
    (Join-Path $gmailRoot '.env.vps'),
    (Join-Path $gmailRoot '.env.local-vps'),
    (Join-Path $gmailRoot 'tools\gmail_audit\.env'),
    (Join-Path $gmailRoot 'deploy\.env.daszek-local'),
    (Join-Path $workspaceRoot '.env.daszek-local'),
    (Join-Path $workspaceRoot 'rag-chat-asystent\.env'),
    (Join-Path $workspaceRoot 'rag-chat-asystent\.env-asystent-rag-keys'),
    (Join-Path $workspaceRoot 'cieplo-orchestrator\.env')
)

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [string]$FailureMessage = 'Command failed.'
    )
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage ExitCode=$LASTEXITCODE"
    }
}

function Invoke-ProofCompose {
    param(
        [string[]]$ComposeArgs,
        [string]$FailureMessage
    )
    Invoke-Checked -FailureMessage $FailureMessage -Command {
        & docker --log-level error compose --env-file .env.vps -f docker-compose.local-vps.yml -f $composeOverridePath @ComposeArgs
    }
}

function Invoke-CanonicalCompose {
    param(
        [string[]]$ComposeArgs,
        [string]$FailureMessage
    )
    Invoke-Checked -FailureMessage $FailureMessage -Command {
        & docker --log-level error compose --env-file .env.vps -f docker-compose.local-vps.yml @ComposeArgs
    }
}

function Write-JsonArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        $Object
    )
    $json = $Object | ConvertTo-Json -Depth 12
    Set-Content -Encoding utf8 -LiteralPath $Path -Value $json
}

function Get-FileIntegritySnapshot {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Paths
    )
    $rows = @()
    foreach ($path in $Paths) {
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path
            $rows += [ordered]@{
                path = $path
                exists = $true
                size = [int64]$item.Length
                sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
            }
        }
        else {
            $rows += [ordered]@{
                path = $path
                exists = $false
                size = $null
                sha256 = ''
            }
        }
    }
    return $rows
}

function Compare-FileIntegritySnapshots {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Before,
        [Parameter(Mandatory = $true)]
        [object[]]$After
    )
    $byPath = @{}
    foreach ($row in $After) {
        $byPath[[string]$row.path] = $row
    }
    $mismatches = @()
    foreach ($row in $Before) {
        $path = [string]$row.path
        $afterRow = $byPath[$path]
        if (-not $afterRow) {
            $mismatches += [ordered]@{ path = $path; reason = 'missing_after' }
            continue
        }
        if (($row.exists -ne $afterRow.exists) -or ($row.size -ne $afterRow.size) -or ($row.sha256 -ne $afterRow.sha256)) {
            $mismatches += [ordered]@{
                path = $path
                before = $row
                after = $afterRow
            }
        }
    }
    return $mismatches
}

function Get-ContainerSnapshot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName
    )
    try {
        $inspectJson = & docker --log-level error inspect $ContainerName 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $inspectJson) {
            return [ordered]@{
                detected_at = [DateTime]::UtcNow.ToString('o')
                container_name = $ContainerName
                exists = $false
                running = $false
                status = 'missing'
                health = ''
                restart_policy = ''
                restart_count = 0
                container_id = ''
                env = @{}
                mounts = @()
                proof_env_file = ''
                proof_mount_present = $false
            }
        }
        $inspect = ($inspectJson | ConvertFrom-Json)[0]
        $state = $inspect.State
        $envMap = @{}
        foreach ($entry in @($inspect.Config.Env)) {
            if ($entry -match '^(.*?)=(.*)$') {
                $envMap[$Matches[1]] = $Matches[2]
            }
        }
        $mounts = @()
        foreach ($mount in @($inspect.Mounts)) {
            $mounts += [ordered]@{
                type = [string]$mount.Type
                source = [string]$mount.Source
                destination = [string]$mount.Destination
                read_only = -not [bool]$mount.RW
            }
        }
        $proofEnvFile = ''
        if ($envMap.ContainsKey('GMAIL_AGENT_ENV_FILE')) {
            $proofEnvFile = [string]$envMap['GMAIL_AGENT_ENV_FILE']
        }
        $proofMountPresent = $false
        foreach ($mount in $mounts) {
            if ([string]$mount.destination -eq '/app/proof-env/gmail-agent.env') {
                $proofMountPresent = $true
                break
            }
        }
        return [ordered]@{
            detected_at = [DateTime]::UtcNow.ToString('o')
            container_name = $ContainerName
            exists = $true
            running = [bool]$state.Running
            status = [string]$state.Status
            health = [string]($state.Health.Status)
            restart_policy = [string]$inspect.HostConfig.RestartPolicy.Name
            restart_count = [int]$inspect.RestartCount
            container_id = [string]$inspect.Id
            env = $envMap
            mounts = $mounts
            proof_env_file = $proofEnvFile
            proof_mount_present = $proofMountPresent
        }
    }
    catch {
        return [ordered]@{
            detected_at = [DateTime]::UtcNow.ToString('o')
            container_name = $ContainerName
            exists = $false
            running = $false
            status = 'missing'
            health = ''
            restart_policy = ''
            restart_count = 0
            container_id = ''
            env = @{}
            mounts = @()
            proof_env_file = ''
            proof_mount_present = $false
        }
    }
}

function Stop-ContainerIfRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName
    )
    $state = Get-ContainerSnapshot -ContainerName $ContainerName
    if (-not $state.running) {
        return $state
    }
    Invoke-Checked -FailureMessage "Failed to stop container $ContainerName." -Command {
        & docker --log-level error stop -t 20 $ContainerName | Out-Null
    }
    return (Get-ContainerSnapshot -ContainerName $ContainerName)
}

function Remove-ContainerIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName
    )
    $state = Get-ContainerSnapshot -ContainerName $ContainerName
    if (-not $state.exists) {
        return $false
    }
    Invoke-Checked -FailureMessage "Failed to remove container $ContainerName." -Command {
        & docker --log-level error rm -f $ContainerName | Out-Null
    }
    return $true
}

function Wait-ContainerRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,
        [int]$TimeoutSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $state = Get-ContainerSnapshot -ContainerName $ContainerName
        if ($state.running -and $state.status -eq 'running') {
            return $state
        }
        Start-Sleep -Seconds 2
    }
    while ((Get-Date) -lt $deadline)
    throw "Container $ContainerName did not reach running state within ${TimeoutSeconds}s."
}

function Wait-WorkerHeartbeat {
    param([int]$TimeoutSeconds = 30)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $logs = (& docker logs --tail 20 $workerContainerName 2>$null | Out-String)
        if (($logs -match 'GET /profile ok') -or ($logs -match 'GET /history ok') -or ($logs -match 'WORKER_CHECKPOINT_RESTORE')) {
            return
        }
        Start-Sleep -Seconds 2
    }
    while ((Get-Date) -lt $deadline)
    throw 'Background worker did not show expected heartbeat/poll markers after restore.'
}

function Assert-HttpOk {
    param(
        [string]$Name,
        [string]$Url,
        [int]$ReadyTimeoutSeconds = 60
    )
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        }
        catch {
        }
        Start-Sleep -Seconds 2
    }
    while ((Get-Date) -lt $deadline)
    throw "$Name check failed: $Url"
}

function Invoke-SyncLocalEnvProof {
    try {
        $output = & $syncScript -ProofOnly -LocalVpsPath $generatedLocalEnvPath -AuditEnvPath $generatedAuditEnvPath *>&1
        return [ordered]@{
            exit_code = 0
            text = (($output | ForEach-Object { "$_" }) -join "`n")
        }
    }
    catch {
        return [ordered]@{
            exit_code = 1
            text = $_.ToString()
        }
    }
}

function Invoke-WorkerRun {
    param(
        [string[]]$RunArgs,
        [string]$FailureMessage
    )
    Invoke-Checked -FailureMessage $FailureMessage -Command {
        & docker --log-level error compose --env-file .env.vps -f docker-compose.local-vps.yml -f $composeOverridePath --profile worker run --rm -T --no-deps `
            -v "${dockerProofPath}:/app/gate-b-proof:rw" `
            gmail-agent-worker @RunArgs
    }
}

function Restore-CanonicalApi {
    param($PreviousState)
    if (-not $PreviousState.exists) {
        Remove-ContainerIfExists -ContainerName $nodebApiContainer | Out-Null
        return (Get-ContainerSnapshot -ContainerName $nodebApiContainer)
    }
    Invoke-CanonicalCompose -ComposeArgs @('--profile', 'api', 'up', '-d', '--force-recreate', '--no-deps', 'gmail-agent-nodeb-api') -FailureMessage 'Failed to restore canonical Node B API.'
    if ($PreviousState.restart_policy) {
        Invoke-Checked -FailureMessage 'Failed to restore Node B API restart policy.' -Command {
            & docker --log-level error update --restart=$($PreviousState.restart_policy) $nodebApiContainer | Out-Null
        }
    }
    if (-not $PreviousState.running) {
        Stop-ContainerIfRunning -ContainerName $nodebApiContainer | Out-Null
        return (Get-ContainerSnapshot -ContainerName $nodebApiContainer)
    }
    $state = Wait-ContainerRunning -ContainerName $nodebApiContainer
    Start-Sleep -Seconds 3
    return (Get-ContainerSnapshot -ContainerName $nodebApiContainer)
}

function Restore-CanonicalWorker {
    param($PreviousState)
    if (-not $PreviousState.exists) {
        Remove-ContainerIfExists -ContainerName $workerContainerName | Out-Null
        return (Get-ContainerSnapshot -ContainerName $workerContainerName)
    }
    Invoke-CanonicalCompose -ComposeArgs @('--profile', 'worker', 'up', '-d', '--force-recreate', '--no-deps', 'gmail-agent-worker') -FailureMessage 'Failed to restore canonical background worker.'
    if ($PreviousState.restart_policy) {
        Invoke-Checked -FailureMessage 'Failed to restore worker restart policy.' -Command {
            & docker --log-level error update --restart=$($PreviousState.restart_policy) $workerContainerName | Out-Null
        }
    }
    if (-not $PreviousState.running) {
        Stop-ContainerIfRunning -ContainerName $workerContainerName | Out-Null
        return (Get-ContainerSnapshot -ContainerName $workerContainerName)
    }
    $state = Wait-ContainerRunning -ContainerName $workerContainerName
    Start-Sleep -Seconds 5
    return (Get-ContainerSnapshot -ContainerName $workerContainerName)
}

function Assert-NoProofOverride {
    param(
        [Parameter(Mandatory = $true)]
        $State,
        [string]$ContainerLabel
    )
    if (-not $State.exists) {
        return
    }
    if ([string]$State.proof_env_file -eq '/app/proof-env/gmail-agent.env') {
        throw "$ContainerLabel still exposes proof GMAIL_AGENT_ENV_FILE after restore."
    }
    if ([bool]$State.proof_mount_present) {
        throw "$ContainerLabel still exposes proof env bind mount after restore."
    }
}

function Write-PreReplayBaselineArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CurrentProofDir,
        [Parameter(Mandatory = $true)]
        [string]$PreviousProofDir
    )
    $resolvedPrevious = [System.IO.Path]::GetFullPath($PreviousProofDir)
    $handoffPath = Join-Path $resolvedPrevious 'OPERATOR_ROW4_HANDOFF.json'
    if (-not (Test-Path -LiteralPath $handoffPath)) {
        throw "PreviousProofDir is missing OPERATOR_ROW4_HANDOFF.json: $resolvedPrevious"
    }
    $handoff = Get-Content -Raw -LiteralPath $handoffPath | ConvertFrom-Json
    $item = $handoff.item
    if (-not $item) {
        throw "PreviousProofDir handoff has no item payload: $resolvedPrevious"
    }
    $signalId = [string]$item.signal_id
    $engagementId = [string]$item.engagement_id
    $caseId = [string]$item.case_id
    $query = @"
select json_build_object(
  'engagement_id', engagement_id,
  'case_id', case_id,
  'version', version,
  'last_trace_id', last_trace_id,
  'signal_id', snapshot_data->>'signal_id',
  'snapshot_trace_id', snapshot_data->>'trace_id'
)
from operator_engagement_snapshots
where engagement_id = '$engagementId' and snapshot_data->>'signal_id' = '$signalId';
"@
    $rowJson = & docker --log-level error exec gmail-agent-mailbox-memory psql -U mailbox_memory -d mailbox_memory -At -c $query
    if ($LASTEXITCODE -ne 0 -or -not ($rowJson -join '').Trim()) {
        throw "Failed to capture pre-replay engagement baseline for signal_id=$signalId engagement_id=$engagementId"
    }
    $row = (($rowJson | ForEach-Object { "$_" }) -join "`n").Trim() | ConvertFrom-Json
    Write-JsonArtifact -Path (Join-Path $CurrentProofDir 'pre-replay-baseline.json') -Object ([ordered]@{
        captured_at = [DateTime]::UtcNow.ToString('o')
        previous_proof_dir = $resolvedPrevious
        message_id = [string]$item.message_id
        signal_id = $signalId
        engagement_id = $engagementId
        case_id = $caseId
        engagement_row = $row
    })
}

Invoke-Checked -FailureMessage 'Docker Desktop is not available.' -Command {
    docker --log-level error version | Out-Null
}

$workerStatePath = Join-Path $proofPath 'worker-proof-window.json'
$restorePath = Join-Path $proofPath 'runtime-restore.json'
$envIntegrityPath = Join-Path $proofPath 'env-integrity.json'
$finalSummaryPath = Join-Path $proofPath 'final-summary.json'

$envBefore = Get-FileIntegritySnapshot -Paths $canonicalEnvPaths
Write-JsonArtifact -Path $envIntegrityPath -Object ([ordered]@{
    before = $envBefore
    after = @()
    byte_identical = $false
    mismatches = @()
})

$workerBefore = $null
$workerAfterStop = $null
$workerDuringIngest = $null
$workerDuringBrowser = $null
$workerAfterRestore = $null
$apiBefore = $null
$apiProof = $null
$apiDuringBrowser = $null
$apiAfterRestore = $null
$browserAnchors = @{}
$snapshotMembership = @{}
$workerHeartbeatConfirmed = $false
$pendingError = $null

Push-Location $gmailRoot
try {
    $workerBefore = Get-ContainerSnapshot -ContainerName $workerContainerName
    $apiBefore = Get-ContainerSnapshot -ContainerName $nodebApiContainer
    if ($PreviousProofDir) {
        Write-PreReplayBaselineArtifact -CurrentProofDir $proofPath -PreviousProofDir $PreviousProofDir
    }
    Write-JsonArtifact -Path $workerStatePath -Object ([ordered]@{
        proof_window_started_at = [DateTime]::UtcNow.ToString('o')
        worker_before = $workerBefore
        api_before = $apiBefore
    })

    try {
        Write-Host "[row4a] quiesce background gmail-agent worker"
        if ($workerBefore.running) {
            Invoke-Checked -FailureMessage 'Failed to quiesce background worker.' -Command {
                & docker --log-level error update --restart=no $workerContainerName | Out-Null
                & docker --log-level error stop -t 20 $workerContainerName | Out-Null
            }
        }
        $workerAfterStop = Get-ContainerSnapshot -ContainerName $workerContainerName
        Write-JsonArtifact -Path $workerStatePath -Object ([ordered]@{
            proof_window_started_at = [DateTime]::UtcNow.ToString('o')
            worker_before = $workerBefore
            worker_after_stop = $workerAfterStop
            api_before = $apiBefore
        })
        if ($SimulateFailureAfterWorkerStop) {
            throw 'Simulated failure after worker stop.'
        }

        Write-Host "[row4a] sync proof-only env"
        $syncResult = Invoke-SyncLocalEnvProof
        if ($syncResult.exit_code -ne 0) {
            if ($syncResult.text) { Write-Output $syncResult.text }
            throw 'sync-local-stack-env.ps1 failed in proof-only mode.'
        }
        if ($syncResult.text) { Write-Output $syncResult.text }

        Write-Host "[row4a] start local Node B infra"
        Invoke-CanonicalCompose -ComposeArgs @('up', '-d', 'mailbox-memory-db', 'neo4j', 'ollama') -FailureMessage 'Failed to start Node B infra.'

        $hostRuntimeHashes = [ordered]@{}
        foreach ($spec in $runtimeHashSpecs) {
            $hostRuntimeHashes[$spec.Label] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $gmailRoot $spec.HostPath)).Hash.ToLowerInvariant()
        }
        Write-JsonArtifact -Path (Join-Path $activationDir 'host-runtime-hashes.json') -Object $hostRuntimeHashes

        $needsRecreate = $false
        $containerHashScript = @('set -eu')
        foreach ($spec in $runtimeHashSpecs) {
            $containerHashScript += "sha256sum $($spec.ContainerPath)"
        }
        try {
            $hashLines = & docker --log-level error compose --env-file .env.vps -f docker-compose.local-vps.yml --profile worker run --rm -T --no-deps gmail-agent-worker sh -lc ($containerHashScript -join "`n")
            if ($LASTEXITCODE -ne 0) { $needsRecreate = $true }
            elseif ($hashLines.Count -lt $runtimeHashSpecs.Count) { $needsRecreate = $true }
            else {
                for ($idx = 0; $idx -lt $runtimeHashSpecs.Count; $idx++) {
                    $token = (("$($hashLines[$idx])".Trim()) -split '\s+')[0].ToLowerInvariant()
                    if ($token -ne $hostRuntimeHashes[$runtimeHashSpecs[$idx].Label]) {
                        $needsRecreate = $true
                        break
                    }
                }
            }
        }
        catch {
            $needsRecreate = $true
        }

        if ($needsRecreate) {
            Write-Host "[row4a] rebuild Node B runtime image"
            Invoke-CanonicalCompose -ComposeArgs @('build', 'gmail-agent-nodeb-api', 'gmail-agent-worker') -FailureMessage 'Failed to rebuild Node B runtime image.'
        }

        Write-Host "[row4a] start proof API with proof env override"
        Invoke-ProofCompose -ComposeArgs @('--profile', 'api', 'up', '-d', '--force-recreate', '--no-deps', 'gmail-agent-nodeb-api') -FailureMessage 'Failed to start proof Node B API.'
        $apiProof = Wait-ContainerRunning -ContainerName $nodebApiContainer
        Invoke-Checked -FailureMessage 'Mounted /app/proof-env/gmail-agent.env is not a file inside proof API.' -Command {
            & docker --log-level error exec $nodebApiContainer sh -lc 'test -f /app/proof-env/gmail-agent.env'
        }
        Invoke-Checked -FailureMessage 'Proof API does not expose proof GMAIL_AGENT_ENV_FILE.' -Command {
            & docker --log-level error exec $nodebApiContainer sh -lc 'test "$GMAIL_AGENT_ENV_FILE" = "/app/proof-env/gmail-agent.env"'
        }
        if ($SimulateFailureAfterProofApiStart) {
            throw 'Simulated failure after proof API start.'
        }

        if (-not $SkipDaszekRecreate) {
            Write-Host "[row4a] force-recreate Daszek wordpress"
            Push-Location $workspaceRoot
            try {
                Invoke-Checked -FailureMessage 'Failed to recreate Daszek WordPress.' -Command {
                    & docker compose -f $daszekCompose up -d --force-recreate wordpress
                }
            }
            finally {
                Pop-Location
            }
        }

        Write-Host "[row4a] preflight core stack"
        & powershell -NoProfile -ExecutionPolicy Bypass -File $preflightScript
        if ($LASTEXITCODE -ne 0) {
            throw "preflight-local-stack.ps1 failed. ExitCode=$LASTEXITCODE"
        }
        Assert-HttpOk -Name 'Daszek sandbox' -Url 'http://127.0.0.1:8090/daszek/'
        Assert-HttpOk -Name 'gmail-agent API' -Url 'http://127.0.0.1:8766/health'

        $hashPy = @"
import hashlib, json
paths = {
$(
    ($runtimeHashSpecs | ForEach-Object { "    '$($_.Label)': '$($_.ContainerPath)'" }) -join ",`n"
)
}
print(json.dumps({k: hashlib.sha256(open(v, 'rb').read()).hexdigest() for k, v in paths.items()}))
"@
        $workerHashOutput = Invoke-WorkerRun -RunArgs @('python', '-c', $hashPy) -FailureMessage 'Failed to capture worker runtime hashes.'
        $workerHashText = (($workerHashOutput | ForEach-Object { "$_" }) -join "`n").Trim()
        $workerHashes = @{}
        foreach ($prop in (($workerHashText | ConvertFrom-Json).PSObject.Properties)) {
            $workerHashes[$prop.Name] = [string]$prop.Value
        }
        Write-JsonArtifact -Path (Join-Path $activationDir 'worker-runtime-hashes.json') -Object $workerHashes
        $apiHashOutput = & docker --log-level error exec $nodebApiContainer python -c $hashPy
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to capture live API runtime hashes.'
        }
        $apiHashText = (($apiHashOutput | ForEach-Object { "$_" }) -join "`n").Trim()
        $apiHashes = @{}
        foreach ($prop in (($apiHashText | ConvertFrom-Json).PSObject.Properties)) {
            $apiHashes[$prop.Name] = [string]$prop.Value
        }
        Write-JsonArtifact -Path (Join-Path $activationDir 'api-runtime-hashes.json') -Object $apiHashes
        foreach ($spec in $runtimeHashSpecs) {
            if (($workerHashes[$spec.Label] -ne $hostRuntimeHashes[$spec.Label]) -or ($apiHashes[$spec.Label] -ne $hostRuntimeHashes[$spec.Label])) {
                throw "Runtime hash mismatch for $($spec.Label)"
            }
        }

        $activationPy = "import json, sys; from pathlib import Path; sys.path.insert(0, '/app/tools/gmail_audit'); import gmail_intake as gi; payload = {'container_import_path': gi.__file__, 'artifact_mount_verified': Path('/app/gate-b-proof/activation').is_dir()}; Path('/app/gate-b-proof/activation/runtime-import.json').write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')"
        Invoke-WorkerRun -RunArgs @('python', '-c', $activationPy) -FailureMessage 'Failed to write activation import artifact.'

        Write-Host "[row4a] doctor"
        $doctorRawPath = Join-Path $logsDir 'doctor.raw.log'
        $doctorPath = Join-Path $proofPath 'doctor.json'
        $doctorOutput = Invoke-WorkerRun -RunArgs @(
            'python',
            'tools/gmail_audit/gmail_intake.py',
            'doctor',
            '--gmail-source',
            'google_api',
            '--check-drive',
            '--check-daszek',
            '--check-daszek-v3-feed',
            '--verbose'
        ) -FailureMessage 'Doctor failed.'
        $doctorText = (($doctorOutput | ForEach-Object { "$_" }) -join "`n")
        $doctorText | Set-Content -Encoding utf8 -LiteralPath $doctorRawPath
        $jsonStart = $doctorText.IndexOf('{')
        $jsonEnd = $doctorText.LastIndexOf('}')
        if ($jsonStart -lt 0 -or $jsonEnd -lt $jsonStart) {
            throw "Doctor output did not contain a JSON object. See $doctorRawPath"
        }
        $doctorJson = $doctorText.Substring($jsonStart, $jsonEnd - $jsonStart + 1)
        $doctorJson | Set-Content -Encoding utf8 -LiteralPath $doctorPath

        Write-Host "[row4a] sequential single-message intake -> reconcile -> feed push"
        $seqLogPath = Join-Path $logsDir 'row3-1.log'
        $seqOutput = Invoke-WorkerRun -RunArgs @(
            'python',
            'scripts/sequential_gmail_ingress_daszek.py',
            '--limit',
            '1',
            '--delay',
            '0',
            '--message-id',
            $MessageId,
            '--push-daszek',
            '--projection-proof',
            '--keep-going',
            '--verbose',
            '--batch-dir',
            '/app/gate-b-proof/row3-1'
        ) -FailureMessage 'Sequential run failed.'
        $seqText = (($seqOutput | ForEach-Object { "$_" }) -join "`n")
        $seqText | Set-Content -Encoding utf8 -LiteralPath $seqLogPath
        if ($seqText) { Write-Output $seqText }
        $workerDuringIngest = Get-ContainerSnapshot -ContainerName $workerContainerName

        Write-Host "[row4a] build actionable handoff"
        $handoffTxt = Join-Path $proofPath 'OPERATOR_ROW4_HANDOFF.txt'
        $handoffJson = Join-Path $proofPath 'OPERATOR_ROW4_HANDOFF.json'
        Invoke-Checked -FailureMessage 'Row4a handoff is not actionable.' -Command {
            & python scripts/gate_b_runtime_proof.py write-handoff --proof-dir $proofPath --output $handoffTxt --json-output $handoffJson
        }

        if ($SimulateFailureBeforeBrowserProof) {
            throw 'Simulated failure before browser proof.'
        }

        $workerDuringBrowser = Get-ContainerSnapshot -ContainerName $workerContainerName
        $apiDuringBrowser = Get-ContainerSnapshot -ContainerName $nodebApiContainer
        Write-Host "[row4a] browser proof"
        Invoke-Checked -FailureMessage 'Browser proof failed.' -Command {
            & python $browserHarness --proof-dir $proofPath --handoff $handoffJson --base-url 'http://127.0.0.1:8090/daszek/' --login 'konrad' --password 'konrad123'
        }

        $anchorsPath = Join-Path $browserDir 'anchors.json'
        $membershipPath = Join-Path $proofPath 'exact-snapshot-membership.json'
        if (Test-Path -LiteralPath $anchorsPath) {
            $browserAnchors = Get-Content -Raw -LiteralPath $anchorsPath | ConvertFrom-Json
        }
        if (Test-Path -LiteralPath $membershipPath) {
            $snapshotMembership = Get-Content -Raw -LiteralPath $membershipPath | ConvertFrom-Json
        }
    }
    catch {
        $pendingError = $_.Exception.Message
    }

    try {
        Write-Host "[row4a] restore background gmail-agent worker state"
        $apiAfterRestore = Restore-CanonicalApi -PreviousState $apiBefore
        $workerAfterRestore = Restore-CanonicalWorker -PreviousState $workerBefore
        if ($apiBefore.running) {
            Assert-HttpOk -Name 'gmail-agent API (restored)' -Url 'http://127.0.0.1:8766/health'
        }
        Assert-NoProofOverride -State $apiAfterRestore -ContainerLabel 'Node B API'
        Assert-NoProofOverride -State $workerAfterRestore -ContainerLabel 'background worker'
        if ($apiAfterRestore.running) {
            $restartCountBefore = [int]$apiAfterRestore.restart_count
            Start-Sleep -Seconds 5
            $apiAfterRestore = Get-ContainerSnapshot -ContainerName $nodebApiContainer
            if ([int]$apiAfterRestore.restart_count -gt $restartCountBefore) {
                throw 'Node B API restart loop detected after restore.'
            }
        }
        if ($workerBefore.running) {
            $restartCountBefore = [int]$workerAfterRestore.restart_count
            Start-Sleep -Seconds 5
            $workerAfterRestore = Get-ContainerSnapshot -ContainerName $workerContainerName
            if ([int]$workerAfterRestore.restart_count -gt $restartCountBefore) {
                throw 'Background worker restart loop detected after restore.'
            }
            $workerHeartbeatConfirmed = $true
        }

        $envAfter = Get-FileIntegritySnapshot -Paths $canonicalEnvPaths
        $mismatches = Compare-FileIntegritySnapshots -Before $envBefore -After $envAfter
        $byteIdentical = ($mismatches.Count -eq 0)
        Write-JsonArtifact -Path $envIntegrityPath -Object ([ordered]@{
            before = $envBefore
            after = $envAfter
            byte_identical = $byteIdentical
            mismatches = $mismatches
        })
        if (-not $byteIdentical) {
            throw 'Canonical env files changed during proof run.'
        }

        Write-JsonArtifact -Path $workerStatePath -Object ([ordered]@{
            proof_window_started_at = [DateTime]::UtcNow.ToString('o')
            worker_before = $workerBefore
            worker_after_stop = $workerAfterStop
            worker_during_ingest = $workerDuringIngest
            worker_during_browser_proof = $workerDuringBrowser
            worker_after_restore = $workerAfterRestore
            api_before = $apiBefore
            api_during_proof = $apiProof
            api_during_browser_proof = $apiDuringBrowser
            api_after_restore = $apiAfterRestore
        })

        Write-JsonArtifact -Path $restorePath -Object ([ordered]@{
            worker_before = $workerBefore
            worker_after_restore = $workerAfterRestore
            api_before = $apiBefore
            api_after_restore = $apiAfterRestore
            worker_heartbeat_confirmed_after_restore = $workerHeartbeatConfirmed
            worker_restored_to_previous_running_state = ($workerBefore.running -eq $workerAfterRestore.running)
            worker_restored_to_previous_restart_policy = ([string]$workerBefore.restart_policy -eq [string]$workerAfterRestore.restart_policy)
            api_restored_to_previous_running_state = ($apiBefore.running -eq $apiAfterRestore.running)
            api_restored_to_previous_restart_policy = ([string]$apiBefore.restart_policy -eq [string]$apiAfterRestore.restart_policy)
            api_proof_mount_present_after_restore = [bool]$apiAfterRestore.proof_mount_present
            api_effective_gmail_agent_env_file = [string]$apiAfterRestore.proof_env_file
            worker_proof_mount_present_after_restore = [bool]$workerAfterRestore.proof_mount_present
            worker_effective_gmail_agent_env_file = [string]$workerAfterRestore.proof_env_file
        })

        $handoffJsonPath = Join-Path $proofPath 'OPERATOR_ROW4_HANDOFF.json'
        $handoff = @{}
        if (Test-Path -LiteralPath $handoffJsonPath) {
            $handoff = Get-Content -Raw -LiteralPath $handoffJsonPath | ConvertFrom-Json
        }
        Write-JsonArtifact -Path $finalSummaryPath -Object ([ordered]@{
            proof_dir = $proofPath
            message_id = $MessageId
            handoff = $handoff
            latest_membership = $snapshotMembership
            browser = $browserAnchors
            restore = @{
                worker_before = $workerBefore
                worker_after_restore = $workerAfterRestore
                api_before = $apiBefore
                api_after_restore = $apiAfterRestore
            }
            env_integrity = @{
                byte_identical = $true
                path = $envIntegrityPath
            }
        })
    }
    catch {
        if ($pendingError) {
            $pendingError = "$pendingError`nRESTORE: $($_.Exception.Message)"
        }
        else {
            $pendingError = $_.Exception.Message
        }
    }

    if ($pendingError) {
        throw $pendingError
    }
}
finally {
    Pop-Location
}
