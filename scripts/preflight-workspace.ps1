# Workspace structure + hygiene preflight
$ErrorActionPreference = 'Stop'
$paths = . (Join-Path $PSScriptRoot 'resolve-paths.ps1')
$root = $env:TOP_CODE_ROOT
$warns = @()

$required = @(
    'knowledge', 'gmail-agent', 'kalk-top', 'daszek', 'wp-bridges',
    'rag-chat-asystent', 'rag-widget', 'cieplo-orchestrator',
    'top-instal-generator', 'fast-kalk'
)

$missing = @()
foreach ($dir in $required) {
    $p = Join-Path $root $dir
    if (-not (Test-Path $p)) { $missing += $dir }
}

if ($missing.Count -gt 0) {
    Write-Host "Missing folders: $($missing -join ', ')" -ForegroundColor Red
    exit 1
}

foreach ($f in @('AGENTS.md', 'knowledge/memory/OPERATOR_DECISIONS.md', '.cursorignore')) {
    $p = Join-Path $root $f
    if (-not (Test-Path $p)) {
        Write-Host "Missing: $f" -ForegroundColor Red
        exit 1
    }
}

# Graphify
$graphJson = Join-Path $root 'knowledge\graphify\graphify-out\graph.json'
if (-not (Test-Path $graphJson)) {
    $warns += 'graphify graph missing - run knowledge/graphify/build-knowledge-graph.ps1 -Mode structural'
}
else {
    $gAge = (Get-Date) - (Get-Item $graphJson).LastWriteTime
    if ($gAge.TotalDays -gt 14) {
        $warns += "graphify graph stale ($([math]::Round($gAge.TotalDays))d) - rebuild after large doc changes"
    }
}

# GitNexus unified mirror
$gnxDir = Join-Path $root 'knowledge\gitnexus\unified-workspace\mirror\repos\.gitnexus'
if (-not (Test-Path $gnxDir)) {
    $warns += 'GitNexus unified missing - run knowledge/gitnexus/unified-workspace/analyze-unified-workspace.ps1'
}

# Regenerable bloat on disk
if (Test-Path (Join-Path $root '_graphify-corpus')) {
    $warns += '_graphify-corpus/ present (~GB mirror) - safe to delete; regenerate via mirror-workspace-corpus.ps1'
}
if (Test-Path (Join-Path $root 'graphify-out')) {
    $warns += 'root graphify-out/ orphaned - delete; canonical: knowledge/graphify/graphify-out/'
}

# UA freshness
$uaMeta = Join-Path $root '.understand-anything\meta.json'
if (Test-Path $uaMeta) {
    try {
        $meta = Get-Content $uaMeta -Raw | ConvertFrom-Json
        if ($meta.analyzedAt) {
            $analyzed = [datetimeoffset]::Parse($meta.analyzedAt)
            $age = (Get-Date) - $analyzed.DateTime
            if ($age.TotalDays -gt 7) {
                $warns += "UA graph stale ($([math]::Round($age.TotalDays))d) - run knowledge/gitnexus/run-understand-workspace-ecosystem.ps1"
            }
        }
        if ($meta.gitCommitHash -eq 'unknown') {
            $warns += 'UA meta gitCommitHash unknown - reindex recommended after major code changes'
        }
    }
    catch { $warns += 'UA meta.json unreadable' }
}

# ECOSYSTEM_MAP date
$ecoPath = Join-Path $root 'ECOSYSTEM_MAP.yaml'
if (Test-Path $ecoPath) {
    $eco = Get-Content $ecoPath -Raw
    if ($eco -match 'updated:\s*(\d{4}-\d{2}-\d{2})') {
        $ecoDate = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd', $null)
        $wsPath = Join-Path $root 'knowledge\world-state.yaml'
        if ((Test-Path $wsPath) -and ((Get-Content $wsPath -Raw) -match 'updated_at:\s*(\d{4}-\d{2}-\d{2})')) {
            $wsDate = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd', $null)
            if ($ecoDate -lt $wsDate) {
                $warns += 'ECOSYSTEM_MAP updated older than world-state.yaml - run compile-world-state.py'
            }
        }
    }
}
else {
    $warns += 'ECOSYSTEM_MAP.yaml missing - deprecated as parallel SoT; canonical state is knowledge/world-state.yaml'
}

# Stale Desktop\knowledge paths in active docs (sample)
$stalePath = 'Desktop\knowledge'
$checkFiles = @(
    'knowledge\docs\CODE_INTELLIGENCE_STACK.md',
    'knowledge\AGENT_OPERATOR_ENVIRONMENT.md'
)
foreach ($rel in $checkFiles) {
    $fp = Join-Path $root $rel
    if ((Test-Path $fp) -and (Select-String -Path $fp -Pattern ([regex]::Escape($stalePath)) -Quiet)) {
        $warns += "stale path $stalePath in $rel"
    }
}

foreach ($w in $warns) { Write-Host "WARN: $w" -ForegroundColor Yellow }
Write-Host 'Workspace preflight OK' -ForegroundColor Green
exit 0
