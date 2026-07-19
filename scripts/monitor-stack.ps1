<#
.SYNOPSIS
    Stack health monitor for TOP-INSTAL AI-OS.
    Checks all major services and logs failures to monitor.log.

.DESCRIPTION
    Run periodically using Task Scheduler, cron, or a systemd timer
    to detect service degradation before operators notice.

.EXAMPLE
    powershell -File scripts/monitor-stack.ps1
#>

param(
    [int]$TimeoutSec = 10,
    [string]$LogPath = "monitor.log",
    [string]$AgentBaseUrl = "http://localhost:8765",
    [string]$RagBaseUrl = "http://localhost:8000",
    [string]$DaszekBaseUrl = "http://localhost:8090",
    [string]$KalkBaseUrl = "http://localhost:8091"
)

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$results = @()

function Check-Health {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$Url,

        [int]$ExpectedStatus = 200
    )

    try {
        $response = Invoke-WebRequest `
            -Uri $Url `
            -TimeoutSec $TimeoutSec `
            -UseBasicParsing `
            -ErrorAction Stop

        $actualStatus = [int]$response.StatusCode
        $isOk = $actualStatus -eq $ExpectedStatus

        $status = if ($isOk) {
            "OK"
        }
        else {
            "HTTP $actualStatus"
        }

        return [pscustomobject]@{
            Name   = $Name
            Ok     = $isOk
            Status = $status
            Detail = ""
        }
    }
    catch {
        $detail = $_.Exception.Message -replace "\r?\n", " "

        return [pscustomobject]@{
            Name   = $Name
            Ok     = $false
            Status = "FAIL"
            Detail = $detail
        }
    }
}

# Core services
$results += Check-Health `
    -Name "gmail-agent (Node B)" `
    -Url "$AgentBaseUrl/health"

$results += Check-Health `
    -Name "RAG (HVAC KB)" `
    -Url "$RagBaseUrl/health"

$results += Check-Health `
    -Name "Daszek (Dashboard)" `
    -Url "$DaszekBaseUrl/"

$results += Check-Health `
    -Name "kalk-top (calculator)" `
    -Url "$KalkBaseUrl/"

# Detailed RAG check
try {
    $ragHealth = Invoke-RestMethod `
        -Uri "$RagBaseUrl/health" `
        -TimeoutSec $TimeoutSec `
        -ErrorAction Stop

    $ragStatus = [string]$ragHealth.status
    $ragChunks = $ragHealth.kb_status.chunk_count
    $ragIsOk = $ragStatus -eq "healthy"

    if ([string]::IsNullOrWhiteSpace($ragStatus)) {
        $ragDisplayStatus = "missing_status"
    }
    else {
        $ragDisplayStatus = $ragStatus
    }

    $results += [pscustomobject]@{
        Name   = "RAG status"
        Ok     = $ragIsOk
        Status = $ragDisplayStatus
        Detail = "chunks=$ragChunks"
    }
}
catch {
    $detail = $_.Exception.Message -replace "\r?\n", " "

    $results += [pscustomobject]@{
        Name   = "RAG status"
        Ok     = $false
        Status = "FAIL"
        Detail = $detail
    }
}

# Detailed Agent API check
try {
    $agentHealth = Invoke-RestMethod `
        -Uri "$AgentBaseUrl/health" `
        -TimeoutSec $TimeoutSec `
        -ErrorAction Stop

    $writeRoutes = $agentHealth.write_routes_enabled
    $writeRoutesOk = $writeRoutes -eq $true

    if ($null -eq $writeRoutes) {
        $agentStatus = "write_routes=missing"
    }
    else {
        $agentStatus = "write_routes=$writeRoutes"
    }

    $results += [pscustomobject]@{
        Name   = "Agent API"
        Ok     = $writeRoutesOk
        Status = $agentStatus
        Detail = ""
    }
}
catch {
    $detail = $_.Exception.Message -replace "\r?\n", " "

    $results += [pscustomobject]@{
        Name   = "Agent API"
        Ok     = $false
        Status = "FAIL"
        Detail = $detail
    }
}

# Normalize collections
$results = @($results)
$failures = @($results | Where-Object { $_.Ok -ne $true })

# Build log output
$logLines = @(
    "[$timestamp] $($results.Count) checks, $($failures.Count) failures"
)

foreach ($failure in $failures) {
    $logLines += (
        "  FAIL: {0} - {1} {2}" -f `
            $failure.Name,
            $failure.Status,
            $failure.Detail
    ).TrimEnd()
}

$logLine = $logLines -join [Environment]::NewLine

# Ensure that the log directory exists
$logDirectory = Split-Path -Parent $LogPath

if (
    -not [string]::IsNullOrWhiteSpace($logDirectory) -and
    -not (Test-Path -LiteralPath $logDirectory)
) {
    New-Item `
        -ItemType Directory `
        -Path $logDirectory `
        -Force `
        -ErrorAction Stop | Out-Null
}

# Append to log file
$logLine | Out-File `
    -FilePath $LogPath `
    -Append `
    -Encoding utf8

# Output to stdout
Write-Host $logLine

if ($failures.Count -gt 0) {
    Write-Host "SOME CHECKS FAILED - check $LogPath for details"
    exit 1
}

Write-Host "ALL CHECKS PASSED"
exit 0