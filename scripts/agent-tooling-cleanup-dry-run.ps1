<#
.SYNOPSIS
    Dry-run cleanup report for agent tooling (plans, sessions, transcripts, skills).
    Run without -Execute for a safe preview. Add -Execute to apply changes.

.PARAMETER Execute
    If specified, perform the actual archive/delete operations. Default: dry run only.

.PARAMETER BackupRoot
    Root directory for archives. Default: C:\Users\compg\agent-tooling-backups
#>
param(
    [switch]$Execute,
    [string]$BackupRoot = "C:\Users\compg\agent-tooling-backups"
)

$ErrorActionPreference = "Stop"
$ts = Get-Date -Format "yyyy-MM-dd-HHmm"
$archiveBase = "$BackupRoot\$ts"
$report = [System.Text.StringBuilder]::new()
$null = $report.AppendLine("# Agent Tooling Cleanup Report")
$null = $report.AppendLine("Generated: $(Get-Date -Format 'yyyy-MM-dd HH:mm')")
$null = $report.AppendLine("Mode: $(if ($Execute) { 'EXECUTE' } else { 'DRY-RUN (no changes)' })")
$null = $report.AppendLine("")
$null = $report.AppendLine("| Category | Action | Path | Size | Reason |")
$null = $report.AppendLine("| -------- | ------ | ---- | ---- | ------ |")

$cutoff90 = (Get-Date).AddDays(-90)
$cutoff180 = (Get-Date).AddDays(-180)
$cutoff60 = (Get-Date).AddDays(-60)

function Add-Report([string]$Cat, [string]$Act, [string]$P, [string]$Sz = "", [string]$Why = "") {
    $null = $report.AppendLine("| $Cat | $Act | ``$P`` | $Sz | $Why |")
}

function Ensure-Archive([string]$subdir) {
    $d = "$archiveBase\$subdir"
    if ($Execute -and (-not (Test-Path $d))) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
    return $d
}

# .cursor\plans
$plansDir = "C:\Users\compg\.cursor\plans"
$plans = Get-ChildItem "$plansDir\*.plan.md" -EA SilentlyContinue
if ($plans.Count -eq 0) {
    Add-Report "cursor-plans" "SKIP" $plansDir "-" "no plan files found"
}
foreach ($f in $plans) {
    if ($f.LastWriteTime -lt $cutoff90) {
        $sz = "$([math]::Round($f.Length/1KB,1)) KB"
        Add-Report "cursor-plans" "ARCHIVE" $f.FullName $sz "older than 90 days"
        if ($Execute) {
            $d = Ensure-Archive "cursor-plans"
            Move-Item $f.FullName $d -Force
        }
    }
}

# .codex\sessions
$sessDir = "C:\Users\compg\.codex\sessions"
$sessions = Get-ChildItem $sessDir -Recurse -Filter "*.jsonl" -EA SilentlyContinue
if ($sessions.Count -eq 0) {
    Add-Report "codex-sessions" "SKIP" $sessDir "-" "no session JSONL files"
}
foreach ($f in $sessions) {
    if ($f.LastWriteTime -lt $cutoff90) {
        $sz = "$([math]::Round($f.Length/1KB,1)) KB"
        $act = if ($f.LastWriteTime -lt $cutoff180) { "ARCHIVE+DELETE-READY" } else { "ARCHIVE" }
        Add-Report "codex-sessions" $act $f.FullName $sz "older than 90 days"
        if ($Execute) {
            $d = Ensure-Archive "codex-sessions"
            Move-Item $f.FullName $d -Force
        }
    }
}

# agent-transcripts
$transcriptDirs = Get-ChildItem "C:\Users\compg\.cursor\projects" -Recurse -Directory -Filter "agent-transcripts" -EA SilentlyContinue
foreach ($tDir in $transcriptDirs) {
    $jsonls = Get-ChildItem $tDir.FullName -Filter "*.jsonl" -EA SilentlyContinue
    foreach ($f in $jsonls) {
        if ($f.LastWriteTime -lt $cutoff60) {
            $sz = "$([math]::Round($f.Length/1KB,1)) KB"
            Add-Report "agent-transcripts" "ARCHIVE" $f.FullName $sz "older than 60 days"
            if ($Execute) {
                $d = Ensure-Archive "agent-transcripts"
                Move-Item $f.FullName $d -Force
            }
        }
    }
}

# .agents\skills (duplicates of .cursor\skills)
$agentsSkillsDir = "C:\Users\compg\.agents\skills"
$agentsSkills = Get-ChildItem $agentsSkillsDir -Directory -EA SilentlyContinue
foreach ($d in $agentsSkills) {
    $cursorEquiv = "C:\Users\compg\.cursor\skills\$($d.Name)"
    if (Test-Path $cursorEquiv) {
        Add-Report ".agents-skills" "ARCHIVE (duplicate)" $d.FullName "-" "identical copy in .cursor\skills\$($d.Name)"
        if ($Execute) {
            $dest = Ensure-Archive "agents-skills-duplicates"
            Move-Item $d.FullName $dest -Force
        }
    }
}

# .codex\skills\compress (duplicate)
$compressSkill = "C:\Users\compg\.codex\skills\compress"
if (Test-Path $compressSkill) {
    Add-Report "codex-skills" "ARCHIVE (duplicate)" $compressSkill "-" "same purpose as caveman-compress; superseded by .cursor\skills\caveman-compress"
    if ($Execute) {
        $dest = Ensure-Archive "codex-skills-duplicates"
        Move-Item $compressSkill $dest -Force
    }
}

# Secret-bearing files (manual only -- require Bitwarden migration first)
$secretFiles = @(
    "C:\Users\compg\.agent-browser\sessions\daszek-ai-default.json"
)
foreach ($p in $secretFiles) {
    if (Test-Path -LiteralPath $p) {
        $sz = "$([math]::Round((Get-Item -LiteralPath $p).Length/1KB,1)) KB"
        Add-Report "SECRET-bearing" "MIGRATE+DELETE (MANUAL)" $p $sz "Contains browser cookies -- see bitwarden-setup.md BEFORE touching"
    }
}

# Cursor globalStorage (HIGH RISK -- manual only)
$stateDb = "C:\Users\compg\AppData\Roaming\Cursor\User\globalStorage\state.vscdb"
if (Test-Path -LiteralPath $stateDb) {
    $sz = "$([math]::Round((Get-Item -LiteralPath $stateDb).Length/1MB,1)) MB"
    Add-Report "CURSOR-STATE" "MANUAL ONLY" $stateDb $sz "HIGH RISK -- backup + close Cursor first"
}

$null = $report.AppendLine("")
$null = $report.AppendLine("## Summary")
$null = $report.AppendLine("")
$null = $report.AppendLine("Mode: **$(if ($Execute) { 'EXECUTED' } else { 'DRY-RUN' })**")

$reportText = $report.ToString()
Write-Host $reportText

if (-not $Execute) {
    Write-Host ""
    Write-Host "--- DRY RUN COMPLETE ---"
    Write-Host "No files were changed. Review the report above."
    Write-Host "Re-run with -Execute to apply archive/delete operations."
}
else {
    Write-Host ""
    Write-Host "--- EXECUTE COMPLETE ---"
    Write-Host "Archives written to: $archiveBase"
    $reportText | Set-Content "$archiveBase\cleanup-report.md" -Encoding UTF8
    Write-Host "Report saved: $archiveBase\cleanup-report.md"
}
