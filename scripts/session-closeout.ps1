# Session closeout helper — writes engram skeleton and reminds memory updates.
param(
    [Parameter(Mandatory = $true)]
    [string]$Slug,
    [string]$Topic = '',
    [string[]]$Done = @(),
    [string[]]$Next = @()
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1')

$date = Get-Date -Format 'yyyy-MM-dd'
$engramDir = Join-Path $env:TOP_CODE_ROOT 'knowledge\memory\engrams'
$engramPath = Join-Path $engramDir "$date-$Slug.md"

if (-not (Test-Path $engramDir)) { New-Item -ItemType Directory -Path $engramDir -Force | Out-Null }

$doneBullets = if ($Done.Count) { ($Done | ForEach-Object { "- $_" }) -join "`n" } else { '- (fill in)' }
$nextBullets = if ($Next.Count) { ($Next | ForEach-Object { "- $_" }) -join "`n" } else { '- (fill in)' }
$topicLine = if ($Topic) { $Topic } else { $Slug }

$content = @"
# Engram — $date — $topicLine

## Scope

$topicLine

## Zrobione

$doneBullets

## Proof labels

| Claim | Tier |
| ----- | ---- |
| (fill) | local / not proven |

## Następna sesja

$nextBullets

## Hook

Written by scripts/session-closeout.ps1 — also update LAST_SESSION.md and ACTIVE_WORKSPACE.md manually or in same commit.
"@

Set-Content -Path $engramPath -Value $content -Encoding UTF8
Write-Host "Engram skeleton: $engramPath" -ForegroundColor Green
Write-Host "Also update: knowledge/memory/LAST_SESSION.md, ACTIVE_WORKSPACE.md" -ForegroundColor Yellow
