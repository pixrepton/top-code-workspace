# Cross-repo local stack env sync (no secrets printed).
# Usage: pwsh -File scripts/sync-local-stack-env.ps1
param(
    [string]$LocalVpsPath = '',
    [string]$AuditEnvPath = '',
    [switch]$ProofOnly
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

$nodebPort = 8766
$gmailRoot = Join-Path $env:TOP_CODE_ROOT 'gmail-agent'
$ragRoot = Join-Path $env:TOP_CODE_ROOT 'rag-chat-asystent'
$maxEnvFileBytes = 5MB

function Get-EnvExamplePath([string]$Path) {
    if ($Path -like '*.example') { return $Path }
    return "$Path.example"
}

function Get-LatestCorruptBackup([string]$Path) {
    $parent = Split-Path $Path -Parent
    $leaf = Split-Path $Path -Leaf
    if (-not $parent -or -not (Test-Path -LiteralPath $parent)) { return '' }
    $candidate = Get-ChildItem -LiteralPath $parent -Filter "$leaf.corrupt.*.bak" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($candidate) { return $candidate.FullName }
    return ''
}

function Test-UsableSecretValue([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    if ($Value -match 'YOUR_|CHANGE_ME') { return $false }
    return $true
}

function Ensure-EnvFileHealthy([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -le $maxEnvFileBytes) { return }
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
    $backupPath = "$Path.corrupt.$stamp.bak"
    Copy-Item -LiteralPath $Path -Destination $backupPath
    $examplePath = Get-EnvExamplePath $Path
    $parent = Split-Path $Path -Parent
    if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    if (Test-Path -LiteralPath $examplePath) {
        $seedContent = [IO.File]::ReadAllText((Resolve-Path -LiteralPath $examplePath))
    }
    else {
        $seedContent = ''
    }
    [IO.File]::WriteAllText((Resolve-Path -LiteralPath $Path), $seedContent, [Text.UTF8Encoding]::new($false))
    Write-Warning "Reset oversized env file: $Path -> $backupPath"
}

function Read-EnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) { return '' }
    foreach ($line in [IO.File]::ReadLines((Resolve-Path -LiteralPath $Path))) {
        if ($line -match "^$([regex]::Escape($Key))=(.*)$") { return $Matches[1].Trim() }
    }
    return ''
}

function Read-ResolvedEnvValue([string[]]$Paths, [string]$Key) {
    $fallback = ''
    foreach ($path in $Paths) {
        if (-not $path) { continue }
        $value = Read-EnvValue $path $Key
        if (-not $value) { continue }
        if (Test-UsableSecretValue $value) { return $value }
        if (-not $fallback) { $fallback = $value }
    }
    return $fallback
}

function Update-EnvFile([string]$Path, [hashtable]$Updates) {
    Ensure-EnvFileHealthy $Path
    $seen = @{}
    $linesOut = [System.Collections.Generic.List[string]]::new()
    $parent = Split-Path $Path -Parent
    if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    if (Test-Path $Path) {
        foreach ($line in [IO.File]::ReadLines((Resolve-Path -LiteralPath $Path))) {
            if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
                $key = $Matches[1]
                if ($Updates.ContainsKey($key)) {
                    if (-not $seen.ContainsKey($key)) {
                        $linesOut.Add("$key=$($Updates[$key])")
                        $seen[$key] = $true
                    }
                    continue
                }
            }
            $linesOut.Add($line)
        }
    }
    foreach ($key in $Updates.Keys) {
        if (-not $seen.ContainsKey($key)) { $linesOut.Add("$key=$($Updates[$key])") }
    }
    $resolvedPath = if (Test-Path -LiteralPath $Path) { [string](Resolve-Path -LiteralPath $Path) } else { $Path }
    [IO.File]::WriteAllText($resolvedPath, (($linesOut -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))
}

$vpsEnv = Join-Path $gmailRoot '.env.vps'
$canonicalLocalVps = Join-Path $gmailRoot '.env.local-vps'
$canonicalAuditEnv = Join-Path $gmailRoot 'tools\gmail_audit\.env'
$localVps = if ($LocalVpsPath) { $LocalVpsPath } else { $canonicalLocalVps }
$auditEnv = if ($AuditEnvPath) { $AuditEnvPath } else { $canonicalAuditEnv }
$daszekEnvRoot = Join-Path $env:TOP_CODE_ROOT '.env.daszek-local'
$vpsEnvBackup = Get-LatestCorruptBackup $vpsEnv
$localVpsBackup = Get-LatestCorruptBackup $canonicalLocalVps
$auditEnvBackup = Get-LatestCorruptBackup $canonicalAuditEnv

$mailboxPgPort = Read-ResolvedEnvValue @($vpsEnv, $vpsEnvBackup) 'MAILBOX_MEMORY_PG_PORT'
if (-not $mailboxPgPort) { $mailboxPgPort = '54129' }
$mailboxPgPass = Read-ResolvedEnvValue @($vpsEnv, $vpsEnvBackup) 'MAILBOX_MEMORY_POSTGRES_PASSWORD'
$mailboxPgUser = Read-ResolvedEnvValue @($vpsEnv, $vpsEnvBackup) 'MAILBOX_MEMORY_POSTGRES_USER'
if (-not $mailboxPgUser) { $mailboxPgUser = 'mailbox_memory' }
$mailboxPgDb = Read-ResolvedEnvValue @($vpsEnv, $vpsEnvBackup) 'MAILBOX_MEMORY_POSTGRES_DB'
if (-not $mailboxPgDb) { $mailboxPgDb = 'mailbox_memory' }
$neoPass = Read-ResolvedEnvValue @($vpsEnv, $vpsEnvBackup) 'NEO4J_PASSWORD'
$registryToken = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $daszekEnvRoot) 'NODE_B_REGISTRY_TOKEN'
if (-not $registryToken) { $registryToken = Read-ResolvedEnvValue @($daszekEnvRoot) 'DASZEK_NODE_B_API_TOKEN' }
if (-not $registryToken) { $registryToken = Read-ResolvedEnvValue @($daszekEnvRoot) 'DASZEK_BRIDGE_TOKEN' }
if (-not $registryToken) { $registryToken = Read-ResolvedEnvValue @($daszekEnvRoot) 'DASZEK_NODE_B_SERVICE_TOKEN' }
$groqKey = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $vpsEnv, $vpsEnvBackup) 'GROQ_API_KEY'
$openrouterKey = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $vpsEnv, $vpsEnvBackup) 'AGENT_OPENAI_API_KEY'
$openaiNative = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $vpsEnv, $vpsEnvBackup) 'AGENT_OPENAI_NATIVE_API_KEY'
if (-not $openaiNative) { $openaiNative = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $vpsEnv, $vpsEnvBackup) 'OPENAI_API_KEY' }
$googleClientId = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $vpsEnv, $vpsEnvBackup) 'GOOGLE_CLIENT_ID'
$googleClientSecret = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $vpsEnv, $vpsEnvBackup) 'GOOGLE_CLIENT_SECRET'
$googleRefreshToken = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $vpsEnv, $vpsEnvBackup) 'GOOGLE_REFRESH_TOKEN'
$googleOauthScopes = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup, $vpsEnv, $vpsEnvBackup) 'GOOGLE_OAUTH_SCOPES'
$googleDriveRootFolderId = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup) 'GOOGLE_DRIVE_ROOT_FOLDER_ID'
$googleDriveSharedDriveId = Read-ResolvedEnvValue @($canonicalLocalVps, $localVpsBackup, $canonicalAuditEnv, $auditEnvBackup) 'GOOGLE_DRIVE_SHARED_DRIVE_ID'
$llmPrimaryKey = if ($openaiNative) { $openaiNative } elseif ($openrouterKey) { $openrouterKey } else { '' }
$llmPrimaryIsOpenAi = $llmPrimaryKey -match '^sk-proj-'

foreach ($envPath in @($localVps, $auditEnv)) {
    Ensure-EnvFileHealthy $envPath
}
if (-not $ProofOnly) {
    foreach ($envPath in @($vpsEnv, (Join-Path $gmailRoot 'deploy\.env.daszek-local'))) {
        Ensure-EnvFileHealthy $envPath
    }
}

$localUpdates = [ordered]@{
    GMAIL_AGENT_RUNTIME_PROFILE                   = 'default'
    NEO4J_PILOT_ENABLED                           = '1'
    NEO4J_URI                                     = 'neo4j://neo4j:7687'
    NEO4J_USERNAME                                = 'neo4j'
    NEO4J_DATABASE                                = 'neo4j'
    LLM_BACKEND                                   = 'openai_chat'
    LLM_PRIMARY_PROVIDER                          = 'openai_chat'
    OPENAI_COMPAT_BASE_URL                        = 'https://api.openai.com/v1'
    OPENAI_COMPAT_MODEL                           = 'gpt-4o-mini'
    LLM_FALLBACK_PROVIDERS                        = 'groq,cerebras'
    GROQ_BASE_URL                                 = 'https://api.groq.com'
    GROQ_MODEL                                    = 'openai/gpt-oss-120b'
    CEREBRAS_BASE_URL                             = 'https://api.cerebras.ai/v1'
    CEREBRAS_MODEL                                = 'gpt-oss-120b'
    AGENT_RUNTIME_ENABLED                         = '1'
    AGENT_RUNTIME_MODE                            = 'prep'
    AGENT_MODEL                                   = 'gpt-4o-mini'
    AGENT_MODEL_FALLBACK                          = 'deepseek/deepseek-chat:free'
    AGENT_OPENAI_BASE_URL                         = 'https://openrouter.ai/api/v1'
    AGENT_OPENAI_NATIVE_BASE_URL                  = 'https://api.openai.com/v1'
    AGENT_GROQ_BASE_URL                           = 'https://api.groq.com/openai/v1'
    AGENT_CEREBRAS_BASE_URL                       = 'https://api.cerebras.ai/v1'
    NODE_B_REGISTRY_BASE_URL                      = "http://127.0.0.1:$nodebPort"
    MAILBOX_MEMORY_VECTOR_ENABLED                 = '1'
    MAILBOX_MEMORY_STAGE_MODE                     = 'live'
    OPENAI_COMPAT_EMBEDDING_BASE_URL              = 'http://ollama:11434/v1'
    OPENAI_COMPAT_EMBEDDING_MODEL                 = 'nomic-embed-text'
    OPENAI_COMPAT_EMBEDDING_DIMENSIONS            = '768'
    DOCLING_ENABLED                               = '1'
    ATTACHMENT_EXTRACTION_ENABLED                 = '1'
    GOOGLE_DRIVE_ENABLED                          = '1'
    GOOGLE_DRIVE_INGEST_ENABLED                   = '1'
    GOOGLE_DRIVE_GRAPH_ENABLED                    = '1'
    GOOGLE_CALENDAR_ENABLED                       = '1'
    GMAIL_AGENT_OTEL_LOCAL_MIRROR_ENABLED         = '1'
    CASE_INTELLIGENCE_VNEXT_ENABLED               = '1'
    UNDERSTANDING_OUTPUT_ENABLED                  = '1'
    DECISION_PIPELINE_ENABLED                     = '1'
    SERVICE_REQUEST_PLAYBOOK_ENABLED              = '1'
    ACTION_PROPOSAL_V2_ENABLED                    = '1'
    AGENT_CONSTITUTION_RAG_ENABLED                = '1'
    SIGNAL_RUNTIME_MODE                           = 'active'
    SIGNAL_WORKER_ENABLED                         = '1'
    GMAIL_INGRESS_OWNER                           = 'signal_worker'
    GMAIL_CHANGE_DETECTION_ENABLED                = '1'
    UNIFIED_SIGNAL_RUNTIME_ENABLED                = '1'
    BUSINESS_DICTIONARY_ENABLED                   = '1'
    EVENT_SPINE_PROCESSOR_ENABLED                 = '1'
    EVENT_SPINE_PROCESSOR_MODE                    = 'shadow'
    DASZEK_V2_PUSH                                = '0'
    DASZEK_V2_READBACK_ENABLED                    = '0'
    DASZEK_BASE_URL                               = 'http://host.docker.internal:8090'
    DASZEK_LOGIN                                  = 'konrad'
    DASZEK_PASSWORD                               = 'konrad123'
    DASZEK_OPERATIONAL_FEED_AUTO_PUSH             = '1'
    DASZEK_OPERATIONAL_FEED_PUSH_MIN_INTERVAL_SEC = '15'
    DASZEK_FEED_SOURCE                            = 'engagement_snapshot_v2'
}

if ($neoPass) { $localUpdates['NEO4J_PASSWORD'] = $neoPass }
if ($googleClientId) { $localUpdates['GOOGLE_CLIENT_ID'] = $googleClientId }
if ($googleClientSecret) { $localUpdates['GOOGLE_CLIENT_SECRET'] = $googleClientSecret }
if ($googleRefreshToken) { $localUpdates['GOOGLE_REFRESH_TOKEN'] = $googleRefreshToken }
if ($googleOauthScopes) { $localUpdates['GOOGLE_OAUTH_SCOPES'] = $googleOauthScopes }
if ($googleDriveRootFolderId) { $localUpdates['GOOGLE_DRIVE_ROOT_FOLDER_ID'] = $googleDriveRootFolderId }
if ($googleDriveSharedDriveId) { $localUpdates['GOOGLE_DRIVE_SHARED_DRIVE_ID'] = $googleDriveSharedDriveId }
if ($groqKey) {
    $localUpdates['GROQ_API_KEY'] = $groqKey
    $localUpdates['AGENT_GROQ_MODEL'] = 'openai/gpt-oss-120b'
}
if ($openrouterKey) { $localUpdates['AGENT_OPENAI_API_KEY'] = $openrouterKey }
if ($llmPrimaryKey) {
    $localUpdates['AGENT_OPENAI_NATIVE_API_KEY'] = $llmPrimaryKey
    $localUpdates['OPENAI_COMPAT_API_KEY'] = $llmPrimaryKey
    if ($llmPrimaryIsOpenAi) {
        $localUpdates['OPENAI_COMPAT_BASE_URL'] = 'https://api.openai.com/v1'
        $localUpdates['AGENT_OPENAI_NATIVE_BASE_URL'] = 'https://api.openai.com/v1'
        $localUpdates['OPENAI_COMPAT_MODEL'] = 'gpt-4o-mini'
        $localUpdates['AGENT_MODEL'] = 'gpt-4o-mini'
    }
    else {
        # No sk-proj key — gpt-4o-mini via OpenRouter on planner slot 1 + structured stages
        $localUpdates['OPENAI_COMPAT_BASE_URL'] = 'https://openrouter.ai/api/v1'
        $localUpdates['AGENT_OPENAI_NATIVE_BASE_URL'] = 'https://openrouter.ai/api/v1'
        $localUpdates['OPENAI_COMPAT_MODEL'] = 'openai/gpt-4o-mini'
        $localUpdates['AGENT_MODEL'] = 'openai/gpt-4o-mini'
    }
}
if ($registryToken) {
    $localUpdates['NODE_B_REGISTRY_TOKEN'] = $registryToken
    $localUpdates['DASZEK_BRIDGE_TOKEN'] = $registryToken
    $localUpdates['DASZEK_NODE_B_SERVICE_TOKEN'] = $registryToken
}
if ($mailboxPgPass) {
    $localUpdates['MAILBOX_MEMORY_DATABASE_URL'] = "postgresql://${mailboxPgUser}:$mailboxPgPass@mailbox-memory-db:5432/${mailboxPgDb}"
}

Update-EnvFile $localVps $localUpdates

$auditUpdates = @{
    NODE_B_REGISTRY_BASE_URL           = "http://127.0.0.1:$nodebPort"
    GMAIL_AGENT_RUNTIME_PROFILE        = 'default'
    MAILBOX_MEMORY_STAGE_MODE          = 'live'
    OPENAI_COMPAT_EMBEDDING_DIMENSIONS = '768'
    NEO4J_PILOT_ENABLED                = '1'
    DASZEK_BASE_URL                    = 'http://host.docker.internal:8090'
    DASZEK_OPERATIONAL_FEED_AUTO_PUSH  = '1'
}
if ($googleClientId) { $auditUpdates['GOOGLE_CLIENT_ID'] = $googleClientId }
if ($googleClientSecret) { $auditUpdates['GOOGLE_CLIENT_SECRET'] = $googleClientSecret }
if ($googleRefreshToken) { $auditUpdates['GOOGLE_REFRESH_TOKEN'] = $googleRefreshToken }
if ($googleOauthScopes) { $auditUpdates['GOOGLE_OAUTH_SCOPES'] = $googleOauthScopes }
if ($googleDriveRootFolderId) { $auditUpdates['GOOGLE_DRIVE_ROOT_FOLDER_ID'] = $googleDriveRootFolderId }
if ($googleDriveSharedDriveId) { $auditUpdates['GOOGLE_DRIVE_SHARED_DRIVE_ID'] = $googleDriveSharedDriveId }
if ($registryToken) {
    $auditUpdates['NODE_B_REGISTRY_TOKEN'] = $registryToken
    $auditUpdates['DASZEK_BRIDGE_TOKEN'] = $registryToken
    $auditUpdates['DASZEK_NODE_B_SERVICE_TOKEN'] = $registryToken
}
if ($groqKey) { $auditUpdates['GROQ_API_KEY'] = $groqKey }
if ($llmPrimaryKey) {
    $auditUpdates['AGENT_OPENAI_NATIVE_API_KEY'] = $llmPrimaryKey
    $auditUpdates['OPENAI_COMPAT_API_KEY'] = $llmPrimaryKey
    if ($llmPrimaryIsOpenAi) {
        $auditUpdates['OPENAI_COMPAT_BASE_URL'] = 'https://api.openai.com/v1'
        $auditUpdates['AGENT_OPENAI_NATIVE_BASE_URL'] = 'https://api.openai.com/v1'
        $auditUpdates['OPENAI_COMPAT_MODEL'] = 'gpt-4o-mini'
        $auditUpdates['AGENT_MODEL'] = 'gpt-4o-mini'
    }
    else {
        $auditUpdates['OPENAI_COMPAT_BASE_URL'] = 'https://openrouter.ai/api/v1'
        $auditUpdates['AGENT_OPENAI_NATIVE_BASE_URL'] = 'https://openrouter.ai/api/v1'
        $auditUpdates['OPENAI_COMPAT_MODEL'] = 'openai/gpt-4o-mini'
        $auditUpdates['AGENT_MODEL'] = 'openai/gpt-4o-mini'
    }
}
if ($openrouterKey) { $auditUpdates['AGENT_OPENAI_API_KEY'] = $openrouterKey }
if ($neoPass) {
    $auditUpdates['NEO4J_URI'] = 'neo4j://127.0.0.1:7687'
    $auditUpdates['NEO4J_USERNAME'] = 'neo4j'
    $auditUpdates['NEO4J_PASSWORD'] = $neoPass
    $auditUpdates['NEO4J_DATABASE'] = 'neo4j'
}
if ($mailboxPgPass) {
    $auditUpdates['MAILBOX_MEMORY_DATABASE_URL'] = "postgresql://${mailboxPgUser}:$mailboxPgPass@127.0.0.1:${mailboxPgPort}/${mailboxPgDb}"
}
Update-EnvFile $auditEnv $auditUpdates

$ragEnv = Join-Path $ragRoot '.env'
$ragKeys = Join-Path $ragRoot '.env-asystent-rag-keys'
if ($registryToken) {
    if (-not $ProofOnly) {
        Update-EnvFile $ragKeys @{
            NODE_B_REGISTRY_TOKEN        = $registryToken
            GMAIL_AGENT_NODE_B_TOKEN     = $registryToken
            NODE_B_REGISTRY_BASE_URL     = "http://127.0.0.1:$nodebPort"
            DASZEK_BRIDGE_TOKEN          = $registryToken
            DASZEK_BASE_URL              = 'http://127.0.0.1:8090'
            EVENT_SPINE_RAG_EMIT_ENABLED = '1'
        }
    }
    if (-not $ProofOnly) {
        Update-EnvFile $ragEnv @{
            GMAIL_AGENT_CONTEXT_PACK_URL          = "http://host.docker.internal:$nodebPort"
            GMAIL_AGENT_NODE_B_TOKEN              = $registryToken
            GMAIL_AGENT_FETCH_CONTEXT_PACK        = '1'
            GMAIL_AGENT_FETCH_ENGAGEMENT_SNAPSHOT = '1'
        }
    }
}

if (-not $ProofOnly) {
    Update-EnvFile $vpsEnv ([ordered]@{
        COMPOSE_PROJECT_NAME              = 'gmail-agent-vps'
        MAILBOX_MEMORY_POSTGRES_DB        = $mailboxPgDb
        MAILBOX_MEMORY_POSTGRES_USER      = $mailboxPgUser
        MAILBOX_MEMORY_POSTGRES_PASSWORD  = $mailboxPgPass
        MAILBOX_MEMORY_PG_PORT            = $mailboxPgPort
        MAILBOX_MEMORY_CONTAINER_NAME     = 'gmail-agent-mailbox-memory'
        NEO4J_PASSWORD                    = $neoPass
        NEO4J_HTTP_PORT                   = '7474'
        NEO4J_BOLT_PORT                   = '7687'
        GMAIL_AGENT_NODEB_PORT            = $nodebPort
        GMAIL_AGENT_INSTALL_DOCLING       = '0'
        OLLAMA_HTTP_PORT                  = '11434'
        OLLAMA_EMBEDDING_MODEL            = 'nomic-embed-text'
        GMAIL_AGENT_WORKER_COMMAND        = 'python tools/gmail_audit/gmail_intake.py signal-worker --loop --verbose'
    })
}

$daszekEnv = Join-Path $gmailRoot 'deploy\.env.daszek-local'
if ($registryToken) {
    # Token tiers (Phase 9.6): local stack mirrors one registry token into operator API,
    # bridge queue, and service paths. Production should split DASZEK_NODE_B_API_TOKEN (operator),
    # DASZEK_BRIDGE_TOKEN (WP bridge), and DASZEK_NODE_B_SERVICE_TOKEN (internal service).
    $daszekTokenUpdates = @{
        DASZEK_NODE_B_API_TOKEN     = $registryToken
        DASZEK_BRIDGE_TOKEN         = $registryToken
        DASZEK_NODE_B_SERVICE_TOKEN = $registryToken
    }
    if (-not $ProofOnly) {
        Update-EnvFile $daszekEnv $daszekTokenUpdates
        Update-EnvFile $daszekEnvRoot $daszekTokenUpdates
    }
}

# D3 resolution — single signal_worker owns Gmail; cieplo-orchestrator poller disabled
$cieploEnv = Join-Path $env:TOP_CODE_ROOT 'cieplo-orchestrator'
$cieploDotEnv = Join-Path $cieploEnv '.env'
if ((-not $ProofOnly) -and (Test-Path $cieploDotEnv)) {
    Update-EnvFile $cieploDotEnv @{
        CIEPLO_GMAIL_POLL_ENABLED         = '0'
        CIEPLO_GMAIL_POLL_ENABLED_COMMENT = 'D3: disabled — gmail-agent signal_worker owns Gmail ingress'
    }
}
$localUpdates['CIEPLO_GMAIL_POLL_ENABLED'] = '0'
$auditUpdates['CIEPLO_GMAIL_POLL_ENABLED'] = '0'

$llmMode = if ($llmPrimaryIsOpenAi) { 'openai-native gpt-4o-mini' } elseif ($llmPrimaryKey) { 'openrouter openai/gpt-4o-mini (no sk-proj)' } else { 'no LLM primary key' }
$modeLabel = if ($ProofOnly) { 'proof-only' } else { 'canonical' }
Write-Host "[OK] sync-local-stack-env: Node B :$nodebPort | LLM: $llmMode | mode=$modeLabel | Neo4j pilot | RAG wire | D3 resolved" -ForegroundColor Green
