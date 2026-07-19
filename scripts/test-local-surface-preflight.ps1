$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

function Test-Endpoint {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Name,
        [Parameter(Mandatory = $true)]
        [string] $Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 8
    }
    catch {
        throw "$Name health check failed for $Url`: $($_.Exception.Message)"
    }

    if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 300) {
        throw "$Name health check returned HTTP $($response.StatusCode) for $Url"
    }

    Write-Host "[OK] $Name $Url" -ForegroundColor Green
}

Test-Endpoint 'Daszek REST' 'http://127.0.0.1:8090/wp-json/'
Test-Endpoint 'kalk-top REST' 'http://127.0.0.1:8091/index.php?rest_route=/'

Write-Host '[OK] local surface preflight endpoints' -ForegroundColor Green
