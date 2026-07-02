# Cross-repo local stack env sync (no secrets printed).
# Usage: pwsh -File scripts/sync-local-stack-env.ps1
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'resolve-paths.ps1') | Out-Null

$nodebPort = 8766
$gmailRoot = Join-Path $env:TOP_CODE_ROOT 'gmail-agent'
$ragRoot = Join-Path $env:TOP_CODE_ROOT 'rag-chat-asystent'

function Read-EnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) { return '' }
    foreach ($line in Get-Content $Path) {
        if ($line -match "^$([regex]::Escape($Key))=(.*)$") { return $Matches[1].Trim() }
    }
    return ''
}

function Update-EnvFile([string]$Path, [hashtable]$Updates) {
    $lines = @()
    if (Test-Path $Path) { $lines = @(Get-Content $Path) }
    $seen = @{}
    $out = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $lines) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $key = $Matches[1]
            if ($Updates.ContainsKey($key)) {
                if (-not $seen.ContainsKey($key)) {
                    $out.Add("$key=$($Updates[$key])")
                    $seen[$key] = $true
                }
                continue
            }
        }
        $out.Add($line)
    }
    foreach ($key in $Updates.Keys) {
        if (-not $seen.ContainsKey($key)) { $out.Add("$key=$($Updates[$key])") }
    }
    $parent = Split-Path $Path -Parent
    if ($parent -and -not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    [IO.File]::WriteAllText($Path, ($out -join "`n") + "`n")
}

$vpsEnv = Join-Path $gmailRoot '.env.vps'
$localVps = Join-Path $gmailRoot '.env.local-vps'
$auditEnv = Join-Path $gmailRoot 'tools\gmail_audit\.env'
$mailboxPgPort = Read-EnvValue $vpsEnv 'MAILBOX_MEMORY_PG_PORT'
if (-not $mailboxPgPort) { $mailboxPgPort = '54129' }
$mailboxPgPass = Read-EnvValue $vpsEnv 'MAILBOX_MEMORY_POSTGRES_PASSWORD'
$mailboxPgUser = Read-EnvValue $vpsEnv 'MAILBOX_MEMORY_POSTGRES_USER'
if (-not $mailboxPgUser) { $mailboxPgUser = 'mailbox_memory' }
$mailboxPgDb = Read-EnvValue $vpsEnv 'MAILBOX_MEMORY_POSTGRES_DB'
if (-not $mailboxPgDb) { $mailboxPgDb = 'mailbox_memory' }
$neoPass = Read-EnvValue $vpsEnv 'NEO4J_PASSWORD'
$registryToken = Read-EnvValue $localVps 'NODE_B_REGISTRY_TOKEN'
if (-not $registryToken) { $registryToken = Read-EnvValue $auditEnv 'NODE_B_REGISTRY_TOKEN' }
$groqKey = Read-EnvValue $localVps 'GROQ_API_KEY'
if (-not $groqKey) { $groqKey = Read-EnvValue $auditEnv 'GROQ_API_KEY' }
$openrouterKey = Read-EnvValue $localVps 'AGENT_OPENAI_API_KEY'
if (-not $openrouterKey) { $openrouterKey = Read-EnvValue $auditEnv 'AGENT_OPENAI_API_KEY' }
$openaiNative = Read-EnvValue $localVps 'AGENT_OPENAI_NATIVE_API_KEY'
if (-not $openaiNative) { $openaiNative = Read-EnvValue $localVps 'OPENAI_API_KEY' }
if (-not $openaiNative) { $openaiNative = Read-EnvValue $auditEnv 'OPENAI_API_KEY' }
$llmPrimaryKey = if ($openaiNative) { $openaiNative } elseif ($openrouterKey) { $openrouterKey } else { '' }
$llmPrimaryIsOpenAi = $llmPrimaryKey -match '^sk-proj-'

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
    Update-EnvFile $ragKeys @{
        NODE_B_REGISTRY_TOKEN        = $registryToken
        GMAIL_AGENT_NODE_B_TOKEN     = $registryToken
        NODE_B_REGISTRY_BASE_URL     = "http://127.0.0.1:$nodebPort"
        DASZEK_BRIDGE_TOKEN          = $registryToken
        DASZEK_BASE_URL              = 'http://127.0.0.1:8090'
        EVENT_SPINE_RAG_EMIT_ENABLED = '1'
    }
    Update-EnvFile $ragEnv @{
        GMAIL_AGENT_CONTEXT_PACK_URL          = "http://host.docker.internal:$nodebPort"
        GMAIL_AGENT_NODE_B_TOKEN              = $registryToken
        GMAIL_AGENT_FETCH_CONTEXT_PACK        = '1'
        GMAIL_AGENT_FETCH_ENGAGEMENT_SNAPSHOT = '1'
    }
}

# .env.vps compose port
$vpsLines = @(Get-Content $vpsEnv)
$vpsOut = [System.Collections.Generic.List[string]]::new()
$portSeen = $false
$mailboxPortSeen = $false
foreach ($line in $vpsLines) {
    if ($line -match '^GMAIL_AGENT_NODEB_PORT=') {
        $vpsOut.Add("GMAIL_AGENT_NODEB_PORT=$nodebPort")
        $portSeen = $true
    }
    elseif ($line -match '^MAILBOX_MEMORY_PG_PORT=') {
        $vpsOut.Add("MAILBOX_MEMORY_PG_PORT=$mailboxPgPort")
        $mailboxPortSeen = $true
    }
    else { $vpsOut.Add($line) }
}
if (-not $portSeen) { $vpsOut.Add("GMAIL_AGENT_NODEB_PORT=$nodebPort") }
if (-not $mailboxPortSeen) { $vpsOut.Add("MAILBOX_MEMORY_PG_PORT=$mailboxPgPort") }
[IO.File]::WriteAllText($vpsEnv, ($vpsOut -join "`n") + "`n")

$daszekEnv = Join-Path $gmailRoot 'deploy\.env.daszek-local'
$daszekEnvRoot = Join-Path $env:TOP_CODE_ROOT '.env.daszek-local'
if ($registryToken) {
    $daszekTokenUpdates = @{
        DASZEK_NODE_B_API_TOKEN     = $registryToken
        DASZEK_BRIDGE_TOKEN         = $registryToken
        DASZEK_NODE_B_SERVICE_TOKEN = $registryToken
    }
    Update-EnvFile $daszekEnv $daszekTokenUpdates
    Update-EnvFile $daszekEnvRoot $daszekTokenUpdates
}

# D3 resolution — single signal_worker owns Gmail; cieplo-orchestrator poller disabled
$cieploEnv = Join-Path $env:TOP_CODE_ROOT 'cieplo-orchestrator'
$cieploDotEnv = Join-Path $cieploEnv '.env'
if (Test-Path $cieploDotEnv) {
    Update-EnvFile $cieploDotEnv @{
        CIEPLO_GMAIL_POLL_ENABLED         = '0'
        CIEPLO_GMAIL_POLL_ENABLED_COMMENT = 'D3: disabled — gmail-agent signal_worker owns Gmail ingress'
    }
}
$localUpdates['CIEPLO_GMAIL_POLL_ENABLED'] = '0'
$auditUpdates['CIEPLO_GMAIL_POLL_ENABLED'] = '0'

$llmMode = if ($llmPrimaryIsOpenAi) { 'openai-native gpt-4o-mini' } elseif ($llmPrimaryKey) { 'openrouter openai/gpt-4o-mini (no sk-proj)' } else { 'no LLM primary key' }
Write-Host "[OK] sync-local-stack-env: Node B :$nodebPort | LLM: $llmMode | Neo4j pilot | RAG wire | D3 resolved" -ForegroundColor Green
