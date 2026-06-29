<#
.SYNOPSIS
    Stack health monitor for TOP-INSTAL AI-OS.
    Checks all major services and logs failures to monitor.log.
.DESCRIPTION
    Run periodically (e.g. cron / systemd timer / Task Scheduler) to detect
    service degradation before operators notice.
.EXAMPLE
    powershell -File scripts/monitor-stack.ps1
#>

param(
    [int]$TimeoutSec = 10,
    [string]$LogPath = "monitor.log"
)

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$results = @()

function Check-Health {
    param([string]$Name, [string]$Url, [string]$ExpectedStatus = "200")
    try {
        $resp = Invoke-WebRequest -Uri $Url -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
        $ok = $resp.StatusCode -eq 200
        $status = if ($ok) { "OK" } else { "HTTP $($resp.StatusCode)" }
        return @{Name = $Name; Ok = $ok; Status = $status; Detail = "" }
    }
    catch {
        return @{Name = $Name; Ok = $false; Status = "FAIL"; Detail = $_.Exception.Message }
    }
}

# Core services
$results += Check-Health -Name "gmail-agent (Node B)" -Url "http://localhost:8766/health"
$results += Check-Health -Name "RAG (HVAC KB)" -Url "http://localhost:8000/health"
$results += Check-Health -Name "Daszek (Dashboard)" -Url "http://localhost:8090/"
$results += Check-Health -Name "kalk-top (calculator)" -Url "http://localhost:8091/"

# Detailed checks
try {
    $ragHealth = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec $TimeoutSec -ErrorAction Stop
    $ragStatus = $ragHealth.status
    $ragChunks = $ragHealth.kb_status.chunk_count
    $results += @{Name = "RAG status"; Ok = ($ragStatus -eq "healthy"); Status = $ragStatus; Detail = "chunks=$ragChunks" }
}
catch {
    $results += @{Name = "RAG status"; Ok = $false; Status = "FAIL"; Detail = $_.Exception.Message }
}

try {
    $agentHealth = Invoke-RestMethod -Uri "http://localhost:8766/health" -TimeoutSec $TimeoutSec -ErrorAction Stop
    $writeRoutes = $agentHealth.write_routes_enabled
    $results += @{Name = "Agent API"; Ok = $writeRoutes; Status = "write_routes=$writeRoutes"; Detail = "" }
}
catch {
    $results += @{Name = "Agent API"; Ok = $false; Status = "FAIL"; Detail = $_.Exception.Message }
}

# Log results
$failures = $results | Where-Object { !$_.Ok }
$logLine = "[$timestamp] $($results.Count) checks, $($failures.Count) failures"

if ($failures.Count -gt 0) {
    $logLine += "`n"
    foreach ($f in $failures) {
        $logLine += "  FAIL: $($f.Name) — $($f.Status) $($f.Detail)`n"
    }
}

# Append to log file
$logLine | Out-File -FilePath $LogPath -Append -Encoding utf8

# Output to stdout
Write-Host $logLine
if ($failures.Count -gt 0) {
    Write-Host "SOME CHECKS FAILED — check $LogPath for details"
    exit 1
}
else {
    Write-Host "ALL CHECKS PASSED"
    exit 0
}
