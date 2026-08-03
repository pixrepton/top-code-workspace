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



function Ensure-KalkTopRuntime {
    $healthUrl = 'http://127.0.0.1:8091/index.php?rest_route=/'
    if (Test-HttpHealth 'kalk-top runtime' $healthUrl) {
        return $true
    }

    # Canonical owner: the durable docker-compose service (restart:unless-stopped,
    # HEALTHCHECK), not an ephemeral, unsupervised host `php -S` process spawned by
    # this session's own preflight. A prior session-hook-only bootstrap left an
    # orphaned host process with no supervisor, no restart-on-crash and no
    # protection against a second conflicting instance -- every lead depended on an
    # operator having manually run this script at some earlier, unrelated time.
    $composeFile = Join-Path $env:TOP_CODE_ROOT 'docker-compose.kalk-top-local.yml'
    if (Test-Path -LiteralPath $composeFile) {
        Write-Host '[..] starting kalk-top runtime via durable docker-compose service' -ForegroundColor Cyan
        # `docker compose up` writes its own routine progress ("Container ... Starting")
        # to stderr; Windows PowerShell 5.1 always surfaces a native command's stderr
        # lines as a NativeCommandError regardless of `2>`/`*>` redirection -- only
        # $ErrorActionPreference actually silences it. Not a failure signal either way:
        # the health poll below is the real pass/fail gate, not this command's own
        # exit code or stderr chatter.
        $previousEap = $ErrorActionPreference
        $ErrorActionPreference = 'SilentlyContinue'
        try {
            docker compose -f $composeFile up -d 2>$null | Out-Null
        }
        finally {
            $ErrorActionPreference = $previousEap
        }

        for ($i = 0; $i -lt 45; $i++) {
            Start-Sleep -Seconds 1
            try {
                $r = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3
                if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) {
                    Write-Host "[OK] kalk-top runtime (docker, after bootstrap) $healthUrl" -ForegroundColor Green
                    return $true
                }
            }
            catch {}
        }
        Write-Host "[FAIL] kalk-top runtime (docker) did not become healthy within 45s" -ForegroundColor Red
    }
    else {
        Write-Host "[WARN] missing $composeFile; falling back to host bootstrap script" -ForegroundColor Yellow
    }

    # Last-resort fallback only: docker itself unavailable or the compose file is
    # missing. Not the primary/sole mechanism -- see comment above.
    $startScript = Join-Path $env:TOP_CODE_ROOT 'kalk-top\scripts\start-runtime-wp.ps1'
    if (-not (Test-Path -LiteralPath $startScript)) {
        Write-Host "[FAIL] missing bootstrap script: $startScript" -ForegroundColor Red
        return $false
    }

    Write-Host '[..] starting kalk-top runtime-wp via start-runtime-wp.ps1 (fallback)' -ForegroundColor Cyan
    try {
        # Non-blocking launch + health poll: avoids -Wait hanging on the long-lived php -S child.
        Start-Process -FilePath 'powershell.exe' `
            -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`"" `
            -WindowStyle Hidden | Out-Null
    }
    catch {
        Write-Host "[FAIL] start-runtime-wp.ps1: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }

    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) {
                Write-Host "[OK] kalk-top runtime (after fallback bootstrap) $healthUrl" -ForegroundColor Green
                return $true
            }
        }
        catch {}
    }

    Write-Host "[FAIL] kalk-top runtime did not become healthy within 30s" -ForegroundColor Red
    return $false
}

if ($FullStack) {

    if (-not (Test-HttpHealth 'Daszek sandbox' 'http://127.0.0.1:8090/wp-json/')) { $warn++ }

    if (-not (Ensure-KalkTopRuntime)) { $warn++ }

    if (-not (Test-TcpPort 'GraphStore Postgres' '127.0.0.1' 54130)) { $warn++ }

    if (-not (Test-TcpPort 'mailbox Postgres' '127.0.0.1' 54129)) { $warn++ }

}



if ($fail -gt 0) { exit 1 }

if ($FullStack -and $warn -gt 0) { exit 2 }

exit 0
