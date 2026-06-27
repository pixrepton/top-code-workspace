# Local Docker stack health check (Gate B preflight)

param(

    [switch]$FullStack

)



$ErrorActionPreference = 'Continue'

. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null



$fail = 0

$warn = 0



Write-Host "TOP_CODE_ROOT=$env:TOP_CODE_ROOT" -ForegroundColor Cyan

if ($FullStack) {

    Write-Host 'Mode: FullStack (core + Daszek + kalk-top + GraphStore PG)' -ForegroundColor Cyan

}

else {

    Write-Host 'Mode: core (gmail-agent API + RAG). Use -FullStack for full local stack.' -ForegroundColor Cyan

}



try {

    docker version 2>&1 | Out-Null

    if ($LASTEXITCODE -ne 0) { throw 'docker not running' }

    Write-Host '[OK] Docker Desktop' -ForegroundColor Green

}

catch {

    Write-Host '[FAIL] Docker Desktop not available' -ForegroundColor Red

    $fail++

}



function Test-HttpHealth($name, $url) {

    try {

        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5

        if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) {

            Write-Host "[OK] $name $url" -ForegroundColor Green

            return $true

        }

    }

    catch {}

    Write-Host "[SKIP/FAIL] $name $url (start local stack if needed)" -ForegroundColor Yellow

    return $false

}



function Test-TcpPort($name, $hostName, $port) {

    try {

        $result = Test-NetConnection -ComputerName $hostName -Port $port -WarningAction SilentlyContinue -ErrorAction Stop

        if ($result.TcpTestSucceeded) {

            Write-Host "[OK] $name ${hostName}:$port" -ForegroundColor Green

            return $true

        }

    }

    catch {}

    Write-Host "[SKIP/FAIL] $name ${hostName}:$port (start local stack if needed)" -ForegroundColor Yellow

    return $false

}



$nodebPort = 8766

$vpsEnv = Join-Path $env:TOP_CODE_ROOT 'gmail-agent\.env.vps'

if (Test-Path $vpsEnv) {

    $portLine = Get-Content $vpsEnv | Where-Object { $_ -match '^GMAIL_AGENT_NODEB_PORT=' } | Select-Object -First 1

    if ($portLine -match '^GMAIL_AGENT_NODEB_PORT=(\d+)') { $nodebPort = [int]$Matches[1] }

}



$coreOk = $true

if (-not (Test-HttpHealth 'gmail-agent API' "http://127.0.0.1:$nodebPort/health")) { $coreOk = $false }

if (-not (Test-HttpHealth 'RAG backend' 'http://127.0.0.1:8000/health')) { $coreOk = $false }



if (-not $coreOk) { $warn++ }



if ($FullStack) {

    if (-not (Test-HttpHealth 'Daszek sandbox' 'http://127.0.0.1:8090')) { $warn++ }

    if (-not (Test-HttpHealth 'kalk-top runtime' 'http://127.0.0.1:8091/wp-json/')) { $warn++ }

    if (-not (Test-TcpPort 'GraphStore Postgres' '127.0.0.1' 54130)) { $warn++ }

    if (-not (Test-TcpPort 'mailbox Postgres' '127.0.0.1' 54129)) { $warn++ }

}



if ($fail -gt 0) { exit 1 }

if ($FullStack -and $warn -gt 0) { exit 2 }

exit 0
