#Requires -Version 5.1
<#
.SYNOPSIS
    Inject Bitwarden Secrets Manager secrets into target .env files.

.DESCRIPTION
    Reads secrets from Bitwarden vault and injects ONLY missing keys into
    the target .env file. Does not overwrite existing local values unless
    -Force is specified.

    Prerequisites:
      - bws CLI installed (see knowledge/agent-os/environment/bitwarden-setup.md)
      - BWS_ACCESS_TOKEN environment variable set
      - Bitwarden project "top-instal-agent-tooling" configured

.PARAMETER EnvTarget
    Path to the .env file to update (default: workspace root .env.daszek-local).

.PARAMETER Force
    Overwrite existing keys in target .env.

.PARAMETER DryRun
    Print what would be injected without writing.

.EXAMPLE
    $env:BWS_ACCESS_TOKEN = "your-token"
    pwsh -File scripts/load-secrets.ps1

.EXAMPLE
    pwsh -File scripts/load-secrets.ps1 -DryRun

.NOTES
    Secrets migrated (Phase 1 — cookies only):
      topinstal/daszek/session-cookie        → DASZEK_SESSION_COOKIE in .env.daszek-local
      topinstal/google/browser-session-cookie → GOOGLE_BROWSER_SESSION_COOKIE in .env.daszek-local

    Next step after this script:
      scripts/sync-local-stack-env.ps1
      scripts/preflight-local-stack.ps1
#>

param(
    [string]$EnvTarget = "",
    [switch]$Force,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Resolve workspace root ───────────────────────────────────────────────────
$ScriptDir = Split-Path $MyInvocation.MyCommand.Path -Parent
$WorkspaceRoot = Split-Path $ScriptDir -Parent
if (-not $EnvTarget) {
    $EnvTarget = Join-Path $WorkspaceRoot ".env.daszek-local"
}

Write-Host "=== load-secrets.ps1 ===" -ForegroundColor Cyan
Write-Host "Target .env : $EnvTarget"
Write-Host "Mode        : $(if ($DryRun) { 'DryRun' } elseif ($Force) { 'Force' } else { 'AddMissing' })"

# ── Check prerequisites ──────────────────────────────────────────────────────
if (-not $env:BWS_ACCESS_TOKEN) {
    Write-Error @"
BWS_ACCESS_TOKEN is not set.
Set it first:
  [System.Environment]::SetEnvironmentVariable('BWS_ACCESS_TOKEN', 'your-token', 'User')
  # then restart the terminal
See: knowledge/agent-os/environment/bitwarden-setup.md
"@
    exit 1
}

$bws = Get-Command bws -ErrorAction SilentlyContinue
if (-not $bws) {
    Write-Error "bws not found in PATH. Install from: https://github.com/bitwarden/sdk/releases"
    exit 1
}

# ── Phase 1: secret key → .env key mapping ──────────────────────────────────
# Extend this table as more secrets are migrated to vault.
$SecretMap = @(
    # Browser session cookies
    @{ BwsKey = "topinstal/daszek/session-cookie"; EnvKey = "DASZEK_SESSION_COOKIE" },
    @{ BwsKey = "topinstal/google/browser-session-cookie"; EnvKey = "GOOGLE_BROWSER_SESSION_COOKIE" }

    # LLM API keys
    @{ BwsKey = "topinstal/llm/groq-api-key"; EnvKey = "GROQ_API_KEY" }
    @{ BwsKey = "topinstal/llm/groq-api-key-prod"; EnvKey = "GROQ_API_KEY_PROD" }
    @{ BwsKey = "topinstal/llm/groq-api-vl"; EnvKey = "GROQ_API_VL" }
    @{ BwsKey = "topinstal/llm/cerebras-api-key"; EnvKey = "CEREBRAS_API_KEY" }
    @{ BwsKey = "topinstal/llm/nvidia-api-key"; EnvKey = "NVIDIA_API_KEY" }
    @{ BwsKey = "topinstal/llm/openrouter-api-key"; EnvKey = "OPENROUTER_API_KEY" }

    # Google OAuth
    @{ BwsKey = "topinstal/google/client-id"; EnvKey = "GOOGLE_CLIENT_ID" }
    @{ BwsKey = "topinstal/google/client-secret-v1"; EnvKey = "GOOGLE_CLIENT_SECRET" }
    @{ BwsKey = "topinstal/google/refresh-token-v1"; EnvKey = "GOOGLE_REFRESH_TOKEN" }
    @{ BwsKey = "topinstal/google/drive-root-folder-id"; EnvKey = "GOOGLE_DRIVE_ROOT_FOLDER_ID" }

    # Daszek auth
    @{ BwsKey = "topinstal/daszek/password-prod"; EnvKey = "DASZEK_PASSWORD_PROD" }
    @{ BwsKey = "topinstal/daszek/bridge-token-prod"; EnvKey = "DASZEK_BRIDGE_TOKEN_PROD" }
    @{ BwsKey = "topinstal/daszek/bridge-token-local"; EnvKey = "DASZEK_BRIDGE_TOKEN" }

    # SMTP
    @{ BwsKey = "topinstal/smtp/password"; EnvKey = "SMTP_PASSWORD" }

    # HVAC API keys
    @{ BwsKey = "topinstal/hvac/public-api-key"; EnvKey = "HVAC_PUBLIC_API_KEY" }
    @{ BwsKey = "topinstal/hvac/admin-api-key"; EnvKey = "HVAC_ADMIN_API_KEY" }

    # Infrastructure
    @{ BwsKey = "topinstal/neo4j/password-local"; EnvKey = "NEO4J_PASSWORD" }
)

# ── Fetch secrets from vault ─────────────────────────────────────────────────
Write-Host "`nFetching secrets from Bitwarden vault..."
try {
    $rawList = & bws secret list 2>&1
    if ($LASTEXITCODE -ne 0) { throw "bws secret list failed: $rawList" }
    $secrets = $rawList | ConvertFrom-Json
}
catch {
    Write-Error "Failed to list secrets: $_"
    exit 1
}

# Build lookup: key → value
$vault = @{}
foreach ($s in $secrets) {
    if ($s.key -and $s.value) {
        $vault[$s.key] = $s.value
    }
}
Write-Host "Vault keys found: $($vault.Count)"

# ── Read existing .env ───────────────────────────────────────────────────────
$envContent = ""
$existingKeys = @{}
if (Test-Path $EnvTarget) {
    $envContent = Get-Content $EnvTarget -Raw -Encoding UTF8
    foreach ($line in ($envContent -split "`n")) {
        if ($line -match "^([A-Z_]+)=") {
            $existingKeys[$Matches[1]] = $true
        }
    }
}

# ── Inject missing secrets ───────────────────────────────────────────────────
$injected = 0
$skipped = 0
$lines = [System.Collections.Generic.List[string]]::new()
$lines.Add("# Auto-injected by load-secrets.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm')")

foreach ($mapping in $SecretMap) {
    $bwsKey = $mapping.BwsKey
    $envKey = $mapping.EnvKey

    if (-not $vault.ContainsKey($bwsKey)) {
        Write-Warning "  MISSING in vault: $bwsKey"
        continue
    }

    if ($existingKeys.ContainsKey($envKey) -and -not $Force) {
        Write-Host "  SKIP (exists): $envKey" -ForegroundColor DarkGray
        $skipped++
        continue
    }

    $val = $vault[$bwsKey]
    if ($DryRun) {
        Write-Host "  WOULD SET: $envKey=<${bwsKey}>" -ForegroundColor Yellow
    }
    else {
        $lines.Add("$envKey=$val")
        Write-Host "  SET: $envKey" -ForegroundColor Green
    }
    $injected++
}

# ── Write / append ───────────────────────────────────────────────────────────
if ($injected -gt 0 -and -not $DryRun) {
    $newBlock = ($lines -join "`n") + "`n"

    if (Test-Path $EnvTarget) {
        # Remove previously injected block if present
        $envContent = $envContent -replace "# Auto-injected by load-secrets\.ps1.*?(\n(?:[A-Z_]+=.*?\n)*)", ""
        Add-Content -Path $EnvTarget -Value "`n$newBlock" -Encoding UTF8
    }
    else {
        $newBlock | Set-Content -Path $EnvTarget -Encoding UTF8
    }
    Write-Host "`nInjected $injected secret(s) into $EnvTarget"
}

Write-Host "`nSummary: injected=$injected skipped=$skipped"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  scripts/sync-local-stack-env.ps1"
Write-Host "  scripts/preflight-local-stack.ps1"
