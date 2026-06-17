# Resolve TOP-INSTAL workspace paths. Source from agent shell or other scripts.
$ErrorActionPreference = 'Stop'

if (-not $env:TOP_CODE_ROOT) {
    $env:TOP_CODE_ROOT = Split-Path $PSScriptRoot -Parent
}

$root = $env:TOP_CODE_ROOT
if (-not (Test-Path (Join-Path $root 'knowledge'))) {
    throw "TOP_CODE_ROOT invalid or knowledge/ missing: $root"
}

$paths = @{
    TOP_CODE_ROOT       = $root
    KNOWLEDGE_ROOT      = Join-Path $root 'knowledge'
    GMAIL_AGENT_ROOT    = Join-Path $root 'gmail-agent'
    DASZEK_ROOT         = Join-Path $root 'daszek'
    WP_BRIDGES_ROOT     = Join-Path $root 'wp-bridges'
    KALK_TOP_ROOT       = Join-Path $root 'kalk-top'
    CIEplo_ROOT         = Join-Path $root 'cieplo-orchestrator'
    GENERATOR_ROOT      = Join-Path $root 'top-instal-generator'
    RAG_BACKEND_ROOT    = Join-Path $root 'rag-chat-asystent'
    RAG_WIDGET_ROOT     = Join-Path $root 'rag-widget'
    FAST_KALK_ROOT      = Join-Path $root 'fast-kalk'
}

foreach ($key in $paths.Keys) {
    Set-Item -Path "env:$key" -Value $paths[$key]
}

return $paths
