# Run session-end hooks manually (operator: "uruchom hooki końca sesji").
# Same pipeline as .cursor/hooks.json sessionEnd — does not inject into chat.
param(
    [string]$TranscriptPath = ''
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1')

$root = $env:TOP_CODE_ROOT
if (-not $root) { throw 'TOP_CODE_ROOT not set (run via resolve-paths.ps1).' }

if (-not $TranscriptPath) {
    $projectsRoot = Join-Path $env:USERPROFILE '.cursor\projects'
    if (Test-Path $projectsRoot) {
        $latest = Get-ChildItem -Path $projectsRoot -Recurse -Filter '*.jsonl' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\subagents\\' } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
        if ($latest) { $TranscriptPath = $latest.FullName }
    }
}

$stdinObj = @{
    manual          = $true
    status          = 'completed'
    loop_count      = 0
    conversation_id = 'manual-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
}
if ($TranscriptPath) { $stdinObj.transcript_path = $TranscriptPath }

$stdin = $stdinObj | ConvertTo-Json -Compress

$hooks = @(
    'session-stop-reflect.js',
    'session-stop-arch-refresh.js',
    'session-stop-engram.js',
    'session-stop-parse-transcript.js',
    'session-stop-auto-review.js'
)

Write-Host 'Session closeout hooks (manual)' -ForegroundColor Cyan
foreach ($hook in $hooks) {
    $hookPath = Join-Path (Join-Path $root '.cursor\hooks') $hook
    if (-not (Test-Path $hookPath)) {
        Write-Warning "Missing: $hookPath"
        continue
    }
    Write-Host "  -> $hook" -ForegroundColor Gray
    $stdin | node $hookPath
}

Write-Host "Done. Log: top-code-memory/SESSION_CLOSEOUT.log" -ForegroundColor Green
