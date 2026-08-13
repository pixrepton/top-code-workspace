# Case-by-case Fresh 38 SUT capture into gmail-agent-nodeb-api.
# Avoids full-batch OOM (Exit2 137). Uses resilient per-case docker exec.

param(
    [string[]]$CaseIds = @(),
    [string]$OutDir = '',
    [string]$Corpus = '',
    [string]$HarnessDir = '',
    [string]$PatchedRunner = '',
    [string]$Container = 'gmail-agent-nodeb-api',
    [string]$Mode = 'production_faithful',
    # FIRST_ATTEMPT evidence is a reliability measurement and must never be overwritten by a
    # later retry. RECOVERY_ATTEMPT artifacts are written to a separate subdirectory.
    [ValidateSet('FIRST_ATTEMPT', 'RECOVERY_ATTEMPT')]
    [string]$AttemptType = 'FIRST_ATTEMPT',
    [int]$AttemptNumber = 1,
    # Hard guarantee for a canonical frozen run: refuse every reuse, even a matching one.
    [switch]$NoReuse,
    # SUT source root to fingerprint and hot-sync. Defaults to the real product tree; overridable
    # so the fingerprint mechanism itself can be tested against a controlled tree.
    [string]$SutSourceRoot = '',
    # Measurement attempt identity. When omitted, each wrapper invocation receives a unique id.
    [string]$AttemptId = '',
    # Compatibility-only: a prior experimental patch used this as a post-client wait window.
    # The fail-closed measurement gate does not wait for Exec completion after docker.exe exits.
    [int]$ExecCompletionTimeoutSeconds = 0,
    # Absolute per-case bound for the callback-owned execution channel. Exceeding it is an
    # abort/NOT_QUALIFIED result, never a completion signal or a path to accepting an artifact.
    [ValidateRange(1, 86400)]
    [int]$LifecycleDeadlineSeconds = 1800
)

$ErrorActionPreference = 'Continue'
$Workspace = Split-Path $PSScriptRoot -Parent
$AuditDir = Join-Path $Workspace 'gmail-agent\tools\gmail_audit'

function Get-Sha256([string]$path) {
    if (-not (Test-Path $path)) { return '' }
    return (Get-FileHash -Path $path -Algorithm SHA256).Hash.ToLowerInvariant()
}

if (-not $Corpus) {
    $Corpus = Join-Path $AuditDir 'tests\fixtures\measurement_contract_v1\corpus-v2.json'
}
if (-not $HarnessDir) {
    # CL-03: the tracked canonical harness. Previously this defaulted into .artifacts\, which is
    # gitignored, so the runner could not be reconstructed from a fresh checkout at all.
    $HarnessDir = Join-Path $PSScriptRoot 'fresh38'
}
# Runner provenance (FIX-MEAS01): one canonical source, mechanically verified against a
# tracked hash pin. The previous default preferred an opaque session-scratch copy and fell
# back silently, so a canonical qualification run depended on a file nobody could verify.
$ProvenancePath = Join-Path $PSScriptRoot 'fresh38_runner_provenance.json'
$Provenance = $null
if (Test-Path $ProvenancePath) {
    $Provenance = Get-Content $ProvenancePath -Raw -Encoding UTF8 | ConvertFrom-Json
}
if (-not $PatchedRunner) {
    $PatchedRunner = Join-Path $HarnessDir 'run_recovery_pf.py'
}
if (-not $OutDir) {
    $stamp = Get-Date -Format 'yyyyMMddTHHmmss'
    $OutDir = Join-Path $env:TEMP "fresh38-capture-$stamp"
}

if (-not $CaseIds -or $CaseIds.Count -eq 0) {
    $CaseIds = @('NEW-03', 'FU-05', 'SVC-01', 'SVC-02', 'CTX-01')
} else {
    # Accept both @('A','B') and 'A,B' / 'A,B,C' from CLI.
    $CaseIds = @(
        $CaseIds |
            ForEach-Object { $_ -split ',' } |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$log = Join-Path $OutDir 'capture.log'
if (-not $AttemptId) {
    $AttemptId = [guid]::NewGuid().ToString('N')
}

function Log([string]$msg) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding UTF8
    Write-Host $line
}

function Quote-ProcessArgument([string]$value) {
    if ($null -eq $value) { return '""' }
    if ($value -notmatch '[\s"]') { return $value }
    return '"' + ($value.Replace('"', '\"')) + '"'
}

function Quote-ShSingleQuoted([string]$value) {
    if ($null -eq $value) { return "''" }
    $single = [string][char]39
    $double = [string][char]34
    $escaped = $value.Replace($single, $single + $double + $single + $double + $single)
    return $single + $escaped + $single
}

function Read-HostProcessIdentity([System.Diagnostics.Process]$Process) {
    $identity = [ordered]@{
        pid = $null
        parent_pid = $null
        process_name = ''
        executable_path = ''
        command_line = ''
        creation_date = ''
        start_time = ''
        has_exited = $null
        cim_error = ''
        process_error = ''
    }
    if ($null -eq $Process) { return [pscustomobject]$identity }
    try {
        $identity.pid = [int]$Process.Id
        $identity.has_exited = [bool]$Process.HasExited
        try { $identity.start_time = $Process.StartTime.ToString('o') } catch {}
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($Process.Id)" -ErrorAction Stop
        if ($cim) {
            $identity.parent_pid = [int]$cim.ParentProcessId
            $identity.process_name = [string]$cim.Name
            $identity.executable_path = [string]$cim.ExecutablePath
            $identity.command_line = [string]$cim.CommandLine
            try { $identity.creation_date = ([datetime]$cim.CreationDate).ToString('o') } catch { $identity.creation_date = [string]$cim.CreationDate }
        }
    } catch {
        $identity.cim_error = "$($_.Exception.GetType().FullName): $($_.Exception.Message)"
    }
    return [pscustomobject]$identity
}

function Get-DockerNpipeName() {
    $dockerHost = $env:DOCKER_HOST
    if (-not $dockerHost) {
        try {
            $dockerHost = (& docker context inspect --format '{{json .Endpoints.docker.Host}}' 2>$null | Select-Object -First 1)
            $dockerHost = ($dockerHost | ConvertFrom-Json)
        } catch {
            $dockerHost = ''
        }
    }
    if (-not $dockerHost -or $dockerHost -notlike 'npipe:*') { return '' }
    $pipeName = $dockerHost -replace '^npipe:/*', ''
    $pipeName = $pipeName -replace '/', '\'
    return '\\' + $pipeName.TrimStart('\')
}

function Test-CaseCaptureArtifact([string]$Path, [string]$CaseId, [string]$AttemptId = '') {
    $result = [ordered]@{
        ok              = $false
        reason          = ''
        case_id         = $CaseId
        actual_case_id  = ''
        terminal_state  = ''
        product_outcome = ''
        parsed          = $null
    }
    if (-not (Test-Path -LiteralPath $Path)) {
        $result.reason = 'missing_artifact'
        return [pscustomobject]$result
    }
    $item = Get-Item -LiteralPath $Path
    if ($item.Length -le 0) {
        $result.reason = 'empty_artifact'
        return [pscustomobject]$result
    }
    try {
        $parsed = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        $result.reason = "malformed_json: $($_.Exception.Message)"
        return [pscustomobject]$result
    }
    if ($AttemptId) {
        $artifactAttempt = ''
        if ($parsed.measurement_attempt) {
            $artifactAttempt = [string]$parsed.measurement_attempt.attempt_id
        }
        if ($artifactAttempt -ne $AttemptId) {
            $result.reason = "attempt_id_mismatch expected=$AttemptId actual=$artifactAttempt"
            return [pscustomobject]$result
        }
    }
    $cases = @($parsed.cases)
    if ($cases.Count -ne 1) {
        $result.reason = "case_count=$($cases.Count)"
        return [pscustomobject]$result
    }
    $case = $cases[0]
    $actual = [string]$case.id
    if (-not $actual) { $actual = [string]$case.case_id }
    $result.actual_case_id = $actual
    if ($actual -ne $CaseId) {
        $result.reason = "case_id_mismatch expected=$CaseId actual=$actual"
        return [pscustomobject]$result
    }
    $terminal = [string]$case.stage_reached
    $result.terminal_state = $terminal
    if (-not $terminal) {
        $result.reason = 'missing_terminal_state'
        return [pscustomobject]$result
    }
    if ($case.parity_error) {
        $result.reason = "parity_error=$($case.parity_error)"
        return [pscustomobject]$result
    }
    if ($case.case_product_outcome) {
        $result.product_outcome = [string]$case.case_product_outcome
    }
    $result.ok = $true
    $result.reason = 'ok'
    $result.parsed = $parsed
    return [pscustomobject]$result
}

function Copy-CaseCaptureArtifact([string]$Container, [string]$RemotePath, [string]$LocalPath, [string]$CaseId, [string]$AttemptId) {
    $copyOutput = & docker cp "${Container}:$RemotePath" $LocalPath 2>&1
    $copyExit = $LASTEXITCODE
    $validation = Test-CaseCaptureArtifact $LocalPath $CaseId $AttemptId
    if ($validation.ok) {
        return [pscustomobject]@{
            ok         = $true
            reason     = 'ok'
            validation = $validation
            copy_exit  = $copyExit
        }
    }
    $remoteProbe = & docker exec $Container sh -lc "if test -e '$RemotePath'; then ls -l '$RemotePath'; else echo missing; fi" 2>&1
    $probeText = (($remoteProbe | Out-String).Trim() -replace '\s+', ' ')
    $copyText = (($copyOutput | Out-String).Trim() -replace '\s+', ' ')
    Log "COPY_FAIL $CaseId copy_exit=$copyExit validation=$($validation.reason) remote=$probeText copy=$copyText"
    return [pscustomobject]@{
        ok         = $false
        reason     = [string]$validation.reason
        validation = $null
        copy_exit  = $copyExit
    }
}

function Copy-CaseRemoteLogFile([string]$Container, [string]$RemotePath, [string]$LocalPath) {
    $copyOutput = & docker cp "${Container}:$RemotePath" $LocalPath 2>&1
    $copyExit = $LASTEXITCODE
    $exists = Test-Path -LiteralPath $LocalPath
    if (-not $exists) {
        Set-Content -LiteralPath $LocalPath -Value '' -Encoding UTF8
    }
    return [pscustomobject]@{
        ok = [bool]($copyExit -eq 0 -and $exists)
        remote_path = $RemotePath
        local_path = $LocalPath
        copy_exit = $copyExit
        copy_output = (($copyOutput | Out-String).Trim())
        exists = [bool](Test-Path -LiteralPath $LocalPath)
        size = if (Test-Path -LiteralPath $LocalPath) { (Get-Item -LiteralPath $LocalPath).Length } else { 0 }
    }
}

function New-RunnerBootstrapCode() {
    return @'
import contextlib
import json
import os
import runpy
import socket
import sys
import traceback
from pathlib import Path

stdout_path = Path(os.environ["FRESH38_REMOTE_STDOUT_PATH"])
stderr_path = Path(os.environ["FRESH38_REMOTE_STDERR_PATH"])
stdout_path.parent.mkdir(parents=True, exist_ok=True)

callback_sock = None
callback_token = os.environ.get("FRESH38_LIFECYCLE_CALLBACK_TOKEN", "")
callback_host = os.environ.get("FRESH38_LIFECYCLE_CALLBACK_HOST", "")
callback_port = os.environ.get("FRESH38_LIFECYCLE_CALLBACK_PORT", "")
if callback_host and callback_port and callback_token:
    callback_sock = socket.create_connection((callback_host, int(callback_port)), timeout=30)
    callback_sock.sendall((callback_token + " " + json.dumps({
        "event": "connected",
        "pid": os.getpid(),
        "attempt_id": os.environ.get("FRESH38_ATTEMPT_ID", ""),
        "artifact_path": os.environ.get("FRESH38_ARTIFACT_PATH", ""),
    }, separators=(",", ":")) + "\n").encode("utf-8"))

exit_code = 0
with stdout_path.open("w", encoding="utf-8", buffering=1) as stdout_file, stderr_path.open("w", encoding="utf-8", buffering=1) as stderr_file:
    with contextlib.redirect_stdout(stdout_file), contextlib.redirect_stderr(stderr_file):
        sys.argv = ["run_recovery_pf.py"] + sys.argv[1:]
        try:
            runpy.run_path("run_recovery_pf.py", run_name="__main__")
        except SystemExit as exc:
            code = exc.code
            if code is None:
                exit_code = 0
            elif isinstance(code, int):
                exit_code = int(code)
            else:
                print(code, file=sys.stderr, flush=True)
                exit_code = 1
        except BaseException:
            traceback.print_exc()
            exit_code = 1

if callback_sock is not None:
    callback_sock.sendall((callback_token + " " + json.dumps({
        "event": "runner_done",
        "pid": os.getpid(),
        "exit_code": exit_code,
        "attempt_id": os.environ.get("FRESH38_ATTEMPT_ID", ""),
        "artifact_path": os.environ.get("FRESH38_ARTIFACT_PATH", ""),
    }, separators=(",", ":")) + "\n").encode("utf-8"))
    # The host waits for EOF on this socket. Do not close it before process exit;
    # the kernel close caused by os._exit is the lifecycle edge being measured.
    os._exit(exit_code)

raise SystemExit(exit_code)
'@
}

function Read-RunnerIdentityFromStderr([string]$StderrPath, [string]$AttemptId) {
    $result = [ordered]@{
        pid = ''
        proc_start_ticks = $null
        source_event = ''
    }
    if (-not (Test-Path -LiteralPath $StderrPath)) { return [pscustomobject]$result }
    try {
        $lines = Get-Content -LiteralPath $StderrPath -Encoding UTF8
        foreach ($line in $lines) {
            if ($line -notmatch '^\[fresh38-lifecycle\] ') { continue }
            $jsonText = $line.Substring('[fresh38-lifecycle] '.Length)
            $obj = $jsonText | ConvertFrom-Json
            if ($AttemptId -and ([string]$obj.attempt_id) -ne $AttemptId) { continue }
            if ($obj.runner -and $obj.runner.pid) {
                $result.pid = [string]$obj.runner.pid
                $result.proc_start_ticks = $obj.runner.proc_start_ticks
                $result.source_event = [string]$obj.event
                return [pscustomobject]$result
            }
            if ($obj.pid) {
                $result.pid = [string]$obj.pid
                $result.proc_start_ticks = $obj.proc_start_ticks
                $result.source_event = [string]$obj.event
                return [pscustomobject]$result
            }
        }
    } catch {
        return [pscustomobject]$result
    }
    return [pscustomobject]$result
}

function Read-RunnerPidFromStderr([string]$StderrPath, [string]$AttemptId) {
    return [string](Read-RunnerIdentityFromStderr $StderrPath $AttemptId).pid
}

function Invoke-ContainerOwnershipProbe(
    [string]$Container,
    [string]$AttemptId,
    [string]$RemotePath,
    [string]$RunnerPid,
    [object]$RunnerStartTicks,
    [string]$OutputPath
) {
    $probeCode = @'
import json, os
from pathlib import Path

attempt = os.environ.get("FRESH38_PROBE_ATTEMPT", "")
remote = os.environ.get("FRESH38_PROBE_PATH", "")
runner_pid = os.environ.get("FRESH38_PROBE_RUNNER_PID", "")
runner_start_ticks = os.environ.get("FRESH38_PROBE_RUNNER_START_TICKS", "")

def read(path):
    try:
        return Path(path).read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except Exception:
        return ""

def read_environ(pid):
    return read(f"/proc/{pid}/environ")

def proc_info(pid):
    if not pid:
        return None
    p = Path("/proc") / str(pid)
    if not p.exists():
        return {"pid": str(pid), "exists": False}
    stat = read(str(p / "stat"))
    parts = stat.split()
    children = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        child_stat = read(str(entry / "stat"))
        child_parts = child_stat.split()
        if len(child_parts) > 3 and child_parts[3] == str(pid):
            children.append({
                "pid": entry.name,
                "ppid": child_parts[3],
                "cmdline": read(str(entry / "cmdline")),
                "proc_start_ticks": int(child_parts[21]) if len(child_parts) > 21 and child_parts[21].isdigit() else None,
            })
    return {
        "pid": str(pid),
        "exists": True,
        "ppid": parts[3] if len(parts) > 3 else "",
        "cmdline": read(str(p / "cmdline")),
        "proc_start_ticks": int(parts[21]) if len(parts) > 21 and parts[21].isdigit() else None,
        "children": children,
    }

matching = []
attempt_env_name = f"FRESH38_ATTEMPT_ID={attempt}"
probe_pid = str(os.getpid())
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    if entry.name == probe_pid:
        continue
    cmdline = read(str(entry / "cmdline"))
    environ = read_environ(entry.name)
    matches_env = bool(attempt and attempt_env_name in environ)
    matches_cmd = bool(attempt and attempt in cmdline)
    if not (matches_env or matches_cmd):
        continue
    stat = read(str(entry / "stat")).split()
    matching.append({
        "pid": entry.name,
        "ppid": stat[3] if len(stat) > 3 else "",
        "cmdline": cmdline,
        "proc_start_ticks": int(stat[21]) if len(stat) > 21 and stat[21].isdigit() else None,
        "matched_attempt_env": matches_env,
        "matched_attempt_cmdline": matches_cmd,
    })

artifact = {"path": remote, "exists": False}
rp = Path(remote) if remote else None
if rp is not None and rp.exists():
    artifact.update({
        "exists": True,
        "size": rp.stat().st_size,
        "mtime": rp.stat().st_mtime,
    })
    try:
        parsed = json.loads(rp.read_text(encoding="utf-8"))
        artifact["valid_json"] = True
        artifact["attempt_id"] = (parsed.get("measurement_attempt") or {}).get("attempt_id")
        cases = parsed.get("cases") or []
        artifact["case_id"] = (cases[0] or {}).get("id") if cases else ""
        artifact["stage_reached"] = (cases[0] or {}).get("stage_reached") if cases else ""
    except Exception as exc:
        artifact["valid_json"] = False
        artifact["json_error"] = f"{type(exc).__name__}: {exc}"

runner_info = proc_info(runner_pid)
original_runner_alive = False
try:
    expected_ticks = int(runner_start_ticks) if runner_start_ticks else None
except Exception:
    expected_ticks = None
if runner_info and runner_info.get("exists"):
    if expected_ticks is None:
        original_runner_alive = True
    else:
        original_runner_alive = runner_info.get("proc_start_ticks") == expected_ticks

print(json.dumps({
    "probe_time_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    "attempt_id": attempt,
    "remote_path": remote,
    "runner_pid_requested": runner_pid,
    "runner_start_ticks_requested": runner_start_ticks,
    "runner_pid_info": runner_info,
    "attempt_processes": matching,
    "ownership": {
        "original_runner_alive": original_runner_alive,
        "attempt_process_count": len(matching),
        "closed": (not original_runner_alive) and len(matching) == 0,
    },
    "artifact": artifact,
}, ensure_ascii=False, sort_keys=True))
'@
    $probeOutput = $probeCode | & docker exec -i `
        -e "FRESH38_PROBE_ATTEMPT=$AttemptId" `
        -e "FRESH38_PROBE_PATH=$RemotePath" `
        -e "FRESH38_PROBE_RUNNER_PID=$RunnerPid" `
        -e "FRESH38_PROBE_RUNNER_START_TICKS=$RunnerStartTicks" `
        $Container python - 2>&1
    $probeExit = $LASTEXITCODE
    ($probeOutput | Out-String).Trim() | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Log "POST_EXEC_PROBE attempt_id=$AttemptId exit=$probeExit path=$OutputPath"
    return $probeExit
}

function New-DockerProcessStartInfo([string[]]$DockerArgs) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $dockerCommand = Get-Command docker -ErrorAction Stop
    $dockerPath = [string]$dockerCommand.Source
    $isExe = [System.IO.Path]::GetExtension($dockerPath).ToLowerInvariant() -eq '.exe'
    $psi.UseShellExecute = $false

    # PowerShell 5.1 does not expose ProcessStartInfo.ArgumentList. Prefer it when available;
    # otherwise keep UseShellExecute=false and build one deterministic argument string.
    $argumentList = $null
    try { $argumentList = $psi.ArgumentList } catch { $argumentList = $null }
    if ($null -ne $argumentList) {
        if ($isExe) {
            $psi.FileName = $dockerPath
            foreach ($arg in $DockerArgs) { [void]$psi.ArgumentList.Add([string]$arg) }
        } else {
            $psi.FileName = 'cmd.exe'
            foreach ($arg in @('/d', '/c', $dockerPath) + $DockerArgs) {
                [void]$psi.ArgumentList.Add([string]$arg)
            }
        }
        return $psi
    }

    $dockerArgsText = (($DockerArgs | ForEach-Object { Quote-ProcessArgument ([string]$_) }) -join ' ')
    if ($isExe) {
        $psi.FileName = $dockerPath
        $psi.Arguments = $dockerArgsText
    } else {
        $psi.FileName = 'cmd.exe'
        $psi.Arguments = "/d /c " + (Quote-ProcessArgument $dockerPath) + " " + $dockerArgsText
    }
    return $psi
}

function Invoke-DockerProcessCaptured([string[]]$DockerArgs) {
    $psi = New-DockerProcessStartInfo $DockerArgs
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $startedAt = (Get-Date).ToString('o')
    [void]$proc.Start()
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()
    $stdoutTask.Wait()
    $stderrTask.Wait()
    return [pscustomobject]@{
        exit_code  = [int]$proc.ExitCode
        pid        = $proc.Id
        started_at = $startedAt
        ended_at   = (Get-Date).ToString('o')
        stdout     = [string]$stdoutTask.Result
        stderr     = [string]$stderrTask.Result
        argv       = 'docker ' + (($DockerArgs | ForEach-Object { [string]$_ }) -join ' ')
    }
}

function Get-DockerDesktopProcessState {
    try {
        $proc = @(Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)
        if ($proc.Count -gt 0) { return 'PROCESS_RUNNING' }
        return 'PROCESS_NOT_FOUND'
    } catch {
        return 'UNKNOWN'
    }
}

function Test-DockerDesktopLinuxEnginePipe {
    $pipe = '\\.\pipe\dockerDesktopLinuxEngine'
    try {
        if (Test-Path -LiteralPath $pipe) { return 'REACHABLE' }
        return 'NOT_REACHABLE'
    } catch {
        return 'UNKNOWN'
    }
}

function Get-DockerHealthSnapshot([string]$Phase) {
    $serverApi = $null
    $enginePing = $null
    try { $serverApi = Invoke-DockerProcessCaptured @('version', '--format', '{{.Server.Version}}') } catch {}
    try { $enginePing = Invoke-DockerProcessCaptured @('version', '--format', '{{.Server.Version}}') } catch {}
    return [pscustomobject][ordered]@{
        phase = $Phase
        captured_at = (Get-Date).ToString('o')
        docker_desktop_state = Get-DockerDesktopProcessState
        docker_desktop_linux_engine = Test-DockerDesktopLinuxEnginePipe
        docker_server_api_reachable = [bool]($serverApi -and $serverApi.exit_code -eq 0)
        engine_ping_ok = [bool]($enginePing -and $enginePing.exit_code -eq 0)
        docker_server_api = if ($serverApi) {
            [ordered]@{
                exit_code = $serverApi.exit_code
                stdout = (($serverApi.stdout | Out-String).Trim())
                stderr = (($serverApi.stderr | Out-String).Trim())
                argv = $serverApi.argv
            }
        } else {
            [ordered]@{ exit_code = $null; stdout = ''; stderr = 'snapshot_failed'; argv = 'docker version --format {{.Server.Version}}' }
        }
        engine_ping = if ($enginePing) {
            [ordered]@{
                exit_code = $enginePing.exit_code
                stdout = (($enginePing.stdout | Out-String).Trim())
                stderr = (($enginePing.stderr | Out-String).Trim())
                argv = $enginePing.argv
            }
        } else {
            [ordered]@{ exit_code = $null; stdout = ''; stderr = 'snapshot_failed'; argv = 'docker version --format {{.Server.Version}}' }
        }
    }
}

function Resolve-DockerEngineHealth([object[]]$Snapshots) {
    $items = @($Snapshots | Where-Object { $null -ne $_ })
    if ($items.Count -eq 0) { return 'UNKNOWN' }
    $ok = @($items | Where-Object { $_.engine_ping_ok -eq $true -and $_.docker_server_api_reachable -eq $true })
    $bad = @($items | Where-Object { $_.engine_ping_ok -eq $false -or $_.docker_server_api_reachable -eq $false })
    if ($ok.Count -eq $items.Count) { return 'HEALTHY' }
    if ($ok.Count -gt 0 -and $bad.Count -gt 0) { return 'DEGRADED' }
    if ($bad.Count -gt 0) { return 'UNAVAILABLE' }
    return 'UNKNOWN'
}

function Start-DockerExecEventCollector([string]$Container, [string]$OutputPath) {
    $sinceEpoch = [DateTimeOffset]::UtcNow.AddSeconds(-2).ToUnixTimeSeconds()
    $args = @(
        'events',
        '--since', [string]$sinceEpoch,
        '--filter', "container=$Container",
        '--filter', 'event=exec_create',
        '--filter', 'event=exec_start',
        '--filter', 'event=exec_die',
        '--format', '{{json .}}'
    )
    $psi = New-DockerProcessStartInfo $args
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    $startedAt = (Get-Date).ToString('o')
    [void]$proc.Start()
    return [pscustomobject]@{
        process     = $proc
        stdout_task = $proc.StandardOutput.ReadToEndAsync()
        stderr_task = $proc.StandardError.ReadToEndAsync()
        started_at  = $startedAt
        since_epoch = $sinceEpoch
        output_path = $OutputPath
        argv        = 'docker ' + (($args | ForEach-Object { [string]$_ }) -join ' ')
    }
}

function Stop-DockerExecEventCollector($Collector) {
    if ($null -eq $Collector) { return [pscustomobject]@{ stdout = ''; stderr = ''; exit_code = $null } }
    $proc = $Collector.process
    if (-not $proc.HasExited) {
        try { $proc.Kill() } catch {}
    }
    try { [void]$proc.WaitForExit(5000) } catch {}
    try { [void]$Collector.stdout_task.Wait(5000) } catch {}
    try { [void]$Collector.stderr_task.Wait(5000) } catch {}
    $stdout = ''
    $stderr = ''
    try { $stdout = [string]$Collector.stdout_task.Result } catch {}
    try { $stderr = [string]$Collector.stderr_task.Result } catch {}
    if ($Collector.output_path) {
        $stdout | Set-Content -LiteralPath $Collector.output_path -Encoding UTF8
        $stderr | Set-Content -LiteralPath ($Collector.output_path + '.stderr') -Encoding UTF8
    }
    $exitCode = $null
    try { $exitCode = [int]$proc.ExitCode } catch {}
    return [pscustomobject]@{
        stdout    = $stdout
        stderr    = $stderr
        exit_code = $exitCode
        pid       = $proc.Id
        started_at = $Collector.started_at
        ended_at = (Get-Date).ToString('o')
        since_epoch = $Collector.since_epoch
        argv = $Collector.argv
    }
}

function Get-DockerExecEventsBackfill([string]$Container, [long]$SinceEpoch, [string]$OutputPath) {
    $untilEpoch = [DateTimeOffset]::UtcNow.AddSeconds(2).ToUnixTimeSeconds()
    $capture = Invoke-DockerProcessCaptured @(
        'events',
        '--since', [string]$SinceEpoch,
        '--until', [string]$untilEpoch,
        '--filter', "container=$Container",
        '--filter', 'event=exec_create',
        '--filter', 'event=exec_start',
        '--filter', 'event=exec_die',
        '--format', '{{json .}}'
    )
    if ($OutputPath) {
        $capture.stdout | Set-Content -LiteralPath $OutputPath -Encoding UTF8
        $capture.stderr | Set-Content -LiteralPath ($OutputPath + '.stderr') -Encoding UTF8
    }
    return $capture
}

function Get-JsonPropertyValue($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function ConvertFrom-DockerEventJsonLines([string]$Text, [string]$Source) {
    $records = @()
    foreach ($line in ($Text -split "`r?`n")) {
        $trimmed = $line.Trim()
        if (-not $trimmed) { continue }
        try {
            $obj = $trimmed | ConvertFrom-Json
        } catch {
            $records += [pscustomobject]@{
                source = $Source
                parse_error = $_.Exception.Message
                raw_line = $trimmed
            }
            continue
        }
        $actor = Get-JsonPropertyValue $obj 'Actor'
        $attrs = Get-JsonPropertyValue $actor 'Attributes'
        $action = [string](Get-JsonPropertyValue $obj 'Action')
        if (-not $action) { $action = [string](Get-JsonPropertyValue $obj 'status') }
        $kind = ''
        if ($action -like 'exec_create*') { $kind = 'exec_create' }
        elseif ($action -like 'exec_start*') { $kind = 'exec_start' }
        elseif ($action -like 'exec_die*') { $kind = 'exec_die' }
        $timeUtc = ''
        try {
            $eventTime = Get-JsonPropertyValue $obj 'time'
            if ($null -ne $eventTime) {
                $timeUtc = [DateTimeOffset]::FromUnixTimeSeconds([int64]$eventTime).UtcDateTime.ToString('o')
            }
        } catch {}
        $records += [pscustomobject]@{
            source = $Source
            kind = $kind
            action = $action
            exec_id = [string](Get-JsonPropertyValue $attrs 'execID')
            exit_code = [string](Get-JsonPropertyValue $attrs 'exitCode')
            container_id = [string](Get-JsonPropertyValue $actor 'ID')
            container_name = [string](Get-JsonPropertyValue $attrs 'name')
            image = [string](Get-JsonPropertyValue $attrs 'image')
            time = Get-JsonPropertyValue $obj 'time'
            time_nano = Get-JsonPropertyValue $obj 'timeNano'
            time_utc = $timeUtc
            raw_line = $trimmed
        }
    }
    return @($records)
}

function Test-ContainsLiteral([string]$Text, [string]$Needle) {
    if (-not $Needle) { return $true }
    return $Text.IndexOf($Needle, [System.StringComparison]::Ordinal) -ge 0
}

function Resolve-ExactDockerExecCorrelation(
    [object[]]$Events,
    [string]$AttemptId,
    [string]$RemotePath,
    [string]$CaseId
) {
    $execEvents = @($Events | Where-Object { $_.exec_id })
    $groups = @($execEvents | Group-Object -Property exec_id)
    $tokens = @('run_recovery_pf.py', $RemotePath, $CaseId)
    if ($AttemptId) { $tokens += $AttemptId }
    $summaries = @()
    $candidates = @()
    foreach ($group in $groups) {
        $items = @($group.Group)
        $blob = (($items | ForEach-Object { [string]$_.raw_line }) -join "`n")
        $missing = @($tokens | Where-Object { -not (Test-ContainsLiteral $blob ([string]$_)) })
        $kinds = @($items | ForEach-Object { $_.kind } | Where-Object { $_ } | Sort-Object -Unique)
        $summary = [ordered]@{
            exec_id = [string]$group.Name
            kinds = $kinds
            event_count = $items.Count
            token_match = $missing.Count -eq 0
            missing_tokens = $missing
            actions = @($items | ForEach-Object { $_.action } | Sort-Object -Unique)
        }
        $summaries += [pscustomobject]$summary
        if ($missing.Count -eq 0) {
            $candidates += [pscustomobject]@{ exec_id = [string]$group.Name; events = $items; summary = $summary }
        }
    }
    if ($candidates.Count -ne 1) {
        return [pscustomobject]@{
            ok = $false
            reason = "candidate_count=$($candidates.Count)"
            exec_id = ''
            all_exec_groups = $summaries
            events = @()
            exec_create = ''
            exec_start = ''
            exec_die = ''
        }
    }
    $main = $candidates[0]
    $mainEvents = @($main.events)
    $create = @($mainEvents | Where-Object { $_.kind -eq 'exec_create' } | Select-Object -First 1)
    $start = @($mainEvents | Where-Object { $_.kind -eq 'exec_start' } | Select-Object -First 1)
    $die = @($mainEvents | Where-Object { $_.kind -eq 'exec_die' } | Select-Object -First 1)
    return [pscustomobject]@{
        ok = $true
        reason = 'ok'
        exec_id = [string]$main.exec_id
        all_exec_groups = $summaries
        events = $mainEvents
        exec_create = if ($create.Count) { [string]$create[0].time_utc } else { '' }
        exec_start = if ($start.Count) { [string]$start[0].time_utc } else { '' }
        exec_die = if ($die.Count) { [string]$die[0].time_utc } else { '' }
    }
}

function New-EngineApiExecCorrelation([object]$ExecResult) {
    $execId = ''
    if ($ExecResult -and (Get-JsonPropertyValue $ExecResult 'exact_exec_id')) {
        $execId = [string](Get-JsonPropertyValue $ExecResult 'exact_exec_id')
    }
    if (-not $execId) {
        return [pscustomobject]@{
            ok = $false
            reason = 'engine_api_exec_id_missing'
            exec_id = ''
            all_exec_groups = @()
            events = @()
            exec_create = ''
            exec_start = ''
            exec_die = ''
        }
    }
    return [pscustomobject]@{
        ok = $true
        reason = 'engine_api_create_id'
        exec_id = $execId
        all_exec_groups = @()
        events = @()
        exec_create = ''
        exec_start = ''
        exec_die = ''
    }
}

function Test-ExecInspectMatchesCase([object]$ExecInspect, [string]$RemotePath, [string]$CaseId) {
    if (-not $ExecInspect -or $ExecInspect.ok -ne $true) { return $false }
    $processConfig = Get-JsonPropertyValue $ExecInspect 'ProcessConfig'
    if (-not $processConfig) { return $false }
    $entrypoint = [string](Get-JsonPropertyValue $processConfig 'entrypoint')
    $arguments = @((Get-JsonPropertyValue $processConfig 'arguments') | ForEach-Object { [string]$_ })
    $blob = ($entrypoint, ($arguments -join ' ')) -join ' '
    if (-not (Test-ContainsLiteral $blob $RemotePath)) { return $false }
    if (-not (Test-ContainsLiteral $blob $CaseId)) { return $false }
    if (-not ((Test-ContainsLiteral $blob 'run_recovery_pf.py') -or (Test-ContainsLiteral $blob 'runpy.run_path'))) { return $false }
    return $true
}

function Find-DockerExecDieEvent([object[]]$Events, [string]$ExecId) {
    $matches = @(
        $Events |
            Where-Object { $_.kind -eq 'exec_die' -and ([string]$_.exec_id) -eq $ExecId } |
            Sort-Object -Property @{ Expression = { $_.time_nano }; Ascending = $true }
    )
    if ($matches.Count -eq 0) { return $null }
    return $matches[0]
}

function Get-ExecEventInspectExitCodeParity([object]$ExecDieExitCode, [object]$FinalExecExitCode) {
    if ($null -eq $ExecDieExitCode -or [string]$ExecDieExitCode -eq '') {
        return 'NOT_AVAILABLE'
    }
    if ($null -eq $FinalExecExitCode -or [string]$FinalExecExitCode -eq '') {
        return 'NOT_AVAILABLE'
    }
    if ([string]$ExecDieExitCode -eq [string]$FinalExecExitCode) {
        return 'PASS'
    }
    return 'FAIL'
}

function New-Fresh38MeasurementVerdict(
    [string]$ExecutionChannelIntegrity,
    [string]$RunnerOwnershipIntegrity,
    [string]$ArtifactCaptureIntegrity,
    [string]$MeasurementQualification,
    [string]$FailureClass,
    [string]$FailureSubclass
) {
    return [pscustomobject][ordered]@{
        execution_channel_integrity = $ExecutionChannelIntegrity
        runner_ownership_integrity = $RunnerOwnershipIntegrity
        artifact_capture_integrity = $ArtifactCaptureIntegrity
        measurement_qualification = $MeasurementQualification
        failure_class = $FailureClass
        failure_subclass = $FailureSubclass
        l3_interpretation_allowed = if ($MeasurementQualification -eq 'QUALIFIED') { 'YES' } else { 'NO' }
        judge_run = 'NO'
        scoring_run = 'NO'
        capability_classified = 'NO'
    }
}

function Get-ArtifactFailureSubclass([string]$Reason) {
    if ($Reason -like 'missing_artifact*') { return 'ARTIFACT_MISSING' }
    if ($Reason -like 'empty_artifact*' -or $Reason -like 'malformed_json*') { return 'ARTIFACT_CORRUPT' }
    if ($Reason -like 'attempt_id_mismatch*' -or $Reason -like 'case_id_mismatch*' -or $Reason -like 'case_count=*') {
        return 'ARTIFACT_IDENTITY_MISMATCH'
    }
    if ($Reason -like 'missing_terminal_state*' -or $Reason -like 'parity_error*') { return 'ARTIFACT_NON_TERMINAL' }
    return 'ARTIFACT_CORRUPT'
}

function Get-OwnershipFailureSubclass([string]$Reason) {
    if ($Reason -eq 'runner_identity_missing' -or $Reason -eq 'ownership_probe_missing' -or $Reason -eq 'ownership_not_closed') {
        return 'RUNNER_IDENTITY_UNPROVEN'
    }
    if ($Reason -eq 'original_runner_still_alive') { return 'RUNNER_STILL_ALIVE' }
    if ($Reason -like 'attempt_processes_alive=*') { return 'OWNED_CHILD_STILL_ALIVE' }
    return 'OWNERSHIP_FAILURE'
}

function Get-EngineApiLifecycleFailureSubclass([string]$Reason) {
    if ($Reason -eq 'lifecycle_deadline_exceeded') { return 'LIFECYCLE_DEADLINE_EXCEEDED' }
    if ($Reason -eq 'lifecycle_callback_not_connected' -or $Reason -eq 'lifecycle_callback_missing_runner_done') {
        return 'LIFECYCLE_CALLBACK_INVALID'
    }
    if ($Reason -eq 'exec_still_running_after_lifecycle_eof') { return 'EXEC_STILL_RUNNING_AFTER_LIFECYCLE_EOF' }
    if ($Reason -eq 'exec_inspect_failed') { return 'EXEC_STATE_UNPROVEN' }
    return 'ENGINE_API_LIFECYCLE_FAILURE'
}

function Resolve-Fresh38MeasurementVerdict(
    [object]$HostProcess,
    [object]$ExecCorrelation,
    [object]$ExecInspect,
    [object]$ExecDieEvent,
    [object]$OwnershipResult,
    [object]$ArtifactValidation
) {
    $hostExitKnown = [bool]($HostProcess -and (Get-JsonPropertyValue $HostProcess 'exit_known') -eq $true)
    $hostExitCode = $null
    if ($HostProcess -and $null -ne (Get-JsonPropertyValue $HostProcess 'exit_code')) {
        try { $hostExitCode = [int](Get-JsonPropertyValue $HostProcess 'exit_code') } catch { $hostExitCode = $null }
    }

    $executionChannel = [string](Get-JsonPropertyValue $HostProcess 'execution_channel')
    if ($executionChannel -eq 'docker_engine_api_npipe') {
        $engineApi = Get-JsonPropertyValue $HostProcess 'engine_api'
        if (-not $engineApi -or (Get-JsonPropertyValue $engineApi 'ok') -ne $true) {
            $reason = if ($engineApi) { [string](Get-JsonPropertyValue $engineApi 'reason') } else { 'engine_api_result_missing' }
            return New-Fresh38MeasurementVerdict `
                'FAIL' `
                'NOT_EVALUATED' `
                'NOT_EVALUATED' `
                'NOT_QUALIFIED' `
                'EXECUTION_CHANNEL_INTEGRITY_FAILURE' `
                (Get-EngineApiLifecycleFailureSubclass $reason)
        }
    }

    if (-not $ExecCorrelation -or $ExecCorrelation.ok -ne $true) {
        $subclass = 'EXEC_IDENTITY_UNPROVEN'
        if ($hostExitKnown -and $null -ne $hostExitCode -and $hostExitCode -ne 0) {
            $subclass = 'HOST_CLIENT_FAILURE_OR_UNKNOWN_EXEC'
        }
        return New-Fresh38MeasurementVerdict 'FAIL' 'NOT_EVALUATED' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'EXECUTION_CHANNEL_INTEGRITY_FAILURE' $subclass
    }

    if (-not $ExecInspect -or $ExecInspect.ok -ne $true) {
        $subclass = 'EXEC_IDENTITY_UNPROVEN'
        if ($hostExitKnown -and $null -ne $hostExitCode -and $hostExitCode -ne 0) {
            $subclass = 'HOST_CLIENT_FAILURE_OR_UNKNOWN_EXEC'
        }
        return New-Fresh38MeasurementVerdict 'FAIL' 'NOT_EVALUATED' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'EXECUTION_CHANNEL_INTEGRITY_FAILURE' $subclass
    }

    if (-not $hostExitKnown) {
        return New-Fresh38MeasurementVerdict 'FAIL' 'NOT_EVALUATED' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'EXECUTION_CHANNEL_INTEGRITY_FAILURE' 'HOST_CLIENT_FAILURE_OR_UNKNOWN_EXEC'
    }
    if ($null -ne $hostExitCode -and $hostExitCode -ne 0) {
        return New-Fresh38MeasurementVerdict 'FAIL' 'NOT_EVALUATED' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'EXECUTION_CHANNEL_INTEGRITY_FAILURE' 'HOST_CLIENT_FAILURE_OR_UNKNOWN_EXEC'
    }
    if ($hostExitCode -eq 0 -and $ExecInspect.Running -eq $true) {
        return New-Fresh38MeasurementVerdict 'FAIL' 'NOT_EVALUATED' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'EXECUTION_CHANNEL_INTEGRITY_FAILURE' 'DOCKER_ATTACH_LIFECYCLE_ANOMALY'
    }

    $execDieExitCode = ''
    if ($ExecDieEvent) { $execDieExitCode = [string](Get-JsonPropertyValue $ExecDieEvent 'exit_code') }
    $exitParity = Get-ExecEventInspectExitCodeParity $execDieExitCode $ExecInspect.ExitCode
    if ($exitParity -eq 'FAIL') {
        return New-Fresh38MeasurementVerdict 'FAIL' 'NOT_EVALUATED' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'EXECUTION_CHANNEL_INTEGRITY_FAILURE' 'EXEC_STATE_INCONSISTENCY'
    }
    if ($ExecInspect.Running -eq $false -and $null -ne $ExecInspect.ExitCode -and [int]$ExecInspect.ExitCode -ne 0) {
        return New-Fresh38MeasurementVerdict 'FAIL' 'NOT_EVALUATED' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'EXEC_FAILURE' 'EXEC_NONZERO'
    }
    if ($ExecInspect.Running -ne $false -or $null -eq $ExecInspect.ExitCode) {
        return New-Fresh38MeasurementVerdict 'FAIL' 'NOT_EVALUATED' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'EXECUTION_CHANNEL_INTEGRITY_FAILURE' 'EXEC_STATE_INCONSISTENCY'
    }

    if (-not $OwnershipResult -or $OwnershipResult.ok -ne $true) {
        $reason = if ($OwnershipResult) { [string]$OwnershipResult.reason } else { 'ownership_probe_missing' }
        return New-Fresh38MeasurementVerdict 'PASS' 'FAIL' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'OWNERSHIP_FAILURE' (Get-OwnershipFailureSubclass $reason)
    }

    if (-not $ArtifactValidation) {
        return New-Fresh38MeasurementVerdict 'PASS' 'PASS' 'NOT_EVALUATED' 'NOT_QUALIFIED' 'NONE' 'NONE'
    }
    if ($ArtifactValidation.ok -ne $true) {
        return New-Fresh38MeasurementVerdict 'PASS' 'PASS' 'FAIL' 'NOT_QUALIFIED' 'ARTIFACT_FAILURE' (Get-ArtifactFailureSubclass ([string]$ArtifactValidation.reason))
    }
    return New-Fresh38MeasurementVerdict 'PASS' 'PASS' 'PASS' 'QUALIFIED' 'NONE' 'NONE'
}

function Test-AttemptProcessOwnershipClosed($Probe, $RunnerIdentity) {
    if (-not $RunnerIdentity -or -not [string]$RunnerIdentity.pid) {
        return [pscustomobject]@{ ok = $false; status = 'FAIL'; reason = 'runner_identity_missing' }
    }
    if (-not $Probe) {
        return [pscustomobject]@{ ok = $false; status = 'FAIL'; reason = 'ownership_probe_missing' }
    }
    $ownership = $Probe.ownership
    if ($ownership -and $ownership.closed -eq $true) {
        return [pscustomobject]@{ ok = $true; status = 'PASS'; reason = 'closed' }
    }
    if ($ownership -and $ownership.original_runner_alive -eq $true) {
        return [pscustomobject]@{ ok = $false; status = 'FAIL'; reason = 'original_runner_still_alive' }
    }
    $attemptProcesses = @($Probe.attempt_processes)
    if ($attemptProcesses.Count -gt 0) {
        return [pscustomobject]@{ ok = $false; status = 'FAIL'; reason = "attempt_processes_alive=$($attemptProcesses.Count)" }
    }
    return [pscustomobject]@{ ok = $false; status = 'FAIL'; reason = 'ownership_not_closed' }
}

function Invoke-DockerExecInspectViaNpipe([string]$ExecId) {
    $pipeName = Get-DockerNpipeName
    if (-not $pipeName) {
        return [pscustomobject]@{ ok = $false; reason = 'docker_host_not_npipe'; stdout = ''; stderr = '' }
    }
    $py = @'
import json
import os
import re
import sys

try:
    import win32file
except Exception as exc:
    print(json.dumps({"ok": False, "reason": "pywin32_unavailable", "error": f"{type(exc).__name__}: {exc}"}))
    raise SystemExit(0)

exec_id = os.environ.get("FRESH38_EXEC_INSPECT_ID", "")
pipe_name = os.environ.get("FRESH38_DOCKER_NPIPE", "")
request = (
    f"GET /exec/{exec_id}/json HTTP/1.1\r\n"
    "Host: docker\r\n"
    "Connection: close\r\n"
    "\r\n"
).encode("ascii")

def decode_chunked(body: bytes) -> bytes:
    out = bytearray()
    idx = 0
    while True:
        marker = body.find(b"\r\n", idx)
        if marker < 0:
            return body
        line = body[idx:marker].split(b";", 1)[0].strip()
        try:
            size = int(line, 16)
        except ValueError:
            return body
        idx = marker + 2
        if size == 0:
            return bytes(out)
        out.extend(body[idx:idx + size])
        idx += size + 2

try:
    handle = win32file.CreateFile(
        pipe_name,
        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
        0,
        None,
        win32file.OPEN_EXISTING,
        0,
        None,
    )
    win32file.WriteFile(handle, request)
    chunks = []
    while True:
        try:
            _hr, data = win32file.ReadFile(handle, 65536)
        except Exception:
            break
        if not data:
            break
        chunks.append(data)
    raw = b"".join(chunks)
    header, _, body = raw.partition(b"\r\n\r\n")
    header_text = header.decode("iso-8859-1", errors="replace")
    status_match = re.match(r"HTTP/\S+\s+(\d+)", header_text)
    status = int(status_match.group(1)) if status_match else 0
    if b"transfer-encoding: chunked" in header.lower():
        body = decode_chunked(body)
    body_text = body.decode("utf-8", errors="replace")
    parsed = None
    if body_text.strip():
        try:
            parsed = json.loads(body_text)
        except Exception:
            parsed = None
    print(json.dumps({
        "ok": 200 <= status < 300 and isinstance(parsed, dict),
        "status": status,
        "headers": header_text,
        "body": parsed,
        "body_text": body_text,
    }, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"ok": False, "reason": "npipe_request_failed", "error": f"{type(exc).__name__}: {exc}"}))
'@
    $oldExec = $env:FRESH38_EXEC_INSPECT_ID
    $oldPipe = $env:FRESH38_DOCKER_NPIPE
    try {
        $env:FRESH38_EXEC_INSPECT_ID = $ExecId
        $env:FRESH38_DOCKER_NPIPE = $pipeName
        $out = $py | python - 2>&1
        $text = ($out | Out-String).Trim()
        if (-not $text) { return [pscustomobject]@{ ok = $false; reason = 'empty_npipe_response'; stdout = ''; stderr = '' } }
        $parsed = $text | ConvertFrom-Json
        return $parsed
    } finally {
        if ($null -eq $oldExec) { Remove-Item Env:FRESH38_EXEC_INSPECT_ID -ErrorAction SilentlyContinue } else { $env:FRESH38_EXEC_INSPECT_ID = $oldExec }
        if ($null -eq $oldPipe) { Remove-Item Env:FRESH38_DOCKER_NPIPE -ErrorAction SilentlyContinue } else { $env:FRESH38_DOCKER_NPIPE = $oldPipe }
    }
}

function Invoke-DockerExecInspect([string]$ExecId) {
    $invokedAt = (Get-Date).ToString('o')
    $cli = Invoke-DockerProcessCaptured @('inspect', $ExecId)
    $parsed = $null
    $cliOk = $false
    try {
        $candidate = $cli.stdout | ConvertFrom-Json
        if ($candidate -is [array]) { $parsed = @($candidate)[0] } else { $parsed = $candidate }
        $cliOk = $null -ne $parsed -and $null -ne (Get-JsonPropertyValue $parsed 'Running')
    } catch {
        $cliOk = $false
    }
    if ($cliOk) {
        return [pscustomobject]@{
            ok = $true
            source = 'docker_cli_inspect'
            invoked_at = $invokedAt
            exit_code = $cli.exit_code
            Running = Get-JsonPropertyValue $parsed 'Running'
            ExitCode = Get-JsonPropertyValue $parsed 'ExitCode'
            Pid = Get-JsonPropertyValue $parsed 'Pid'
            ProcessConfig = Get-JsonPropertyValue $parsed 'ProcessConfig'
            ContainerID = Get-JsonPropertyValue $parsed 'ContainerID'
            raw = $parsed
            stderr = $cli.stderr
        }
    }

    $npipe = Invoke-DockerExecInspectViaNpipe $ExecId
    $body = Get-JsonPropertyValue $npipe 'body'
    if ($npipe.ok -and $body) {
        return [pscustomobject]@{
            ok = $true
            source = 'docker_engine_npipe'
            invoked_at = $invokedAt
            exit_code = $null
            Running = Get-JsonPropertyValue $body 'Running'
            ExitCode = Get-JsonPropertyValue $body 'ExitCode'
            Pid = Get-JsonPropertyValue $body 'Pid'
            ProcessConfig = Get-JsonPropertyValue $body 'ProcessConfig'
            ContainerID = Get-JsonPropertyValue $body 'ContainerID'
            raw = $body
            stderr = $cli.stderr
        }
    }
    return [pscustomobject]@{
        ok = $false
        source = 'unavailable'
        invoked_at = $invokedAt
        exit_code = $cli.exit_code
        Running = $null
        ExitCode = $null
        Pid = $null
        ProcessConfig = $null
        ContainerID = $null
        raw = $null
        stderr = (($cli.stderr, (ConvertTo-Json $npipe -Depth 8 -Compress)) -join "`n")
    }
}

function Read-JsonFileOrNull([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}

function Write-CaseExecEvidence([string]$Path, [object]$Evidence) {
    ($Evidence | ConvertTo-Json -Depth 60) | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Invoke-CaseSubprocessViaDockerCli(
    [string]$Container,
    [string]$Mode,
    [string]$RemoteOut,
    [string]$CaseId,
    [string]$StdoutPath,
    [string]$StderrPath,
    [string]$AttemptId,
    [string]$RemoteStdoutPath,
    [string]$RemoteStderrPath
) {
    $args = @(
        'exec',
        '-w',
        '/tmp/fresh38-sentinel'
    )
    $lifecycleDiag = if ($env:FRESH38_LIFECYCLE_DIAG) { [string]$env:FRESH38_LIFECYCLE_DIAG } else { '1' }
    $lifecycleDiagCase = if ($env:FRESH38_LIFECYCLE_DIAG_CASE) { [string]$env:FRESH38_LIFECYCLE_DIAG_CASE } else { $CaseId }
    $args += @('-e', "FRESH38_LIFECYCLE_DIAG=$lifecycleDiag")
    if ($lifecycleDiagCase) {
        $args += @('-e', "FRESH38_LIFECYCLE_DIAG_CASE=$lifecycleDiagCase")
    }
    if ($AttemptId) {
        $args += @('-e', "FRESH38_ATTEMPT_ID=$AttemptId")
    }
    if ($RemoteOut) {
        $args += @('-e', "FRESH38_ARTIFACT_PATH=$RemoteOut")
    }
    if ($RemoteStdoutPath) {
        $args += @('-e', "FRESH38_REMOTE_STDOUT_PATH=$RemoteStdoutPath")
    }
    if ($RemoteStderrPath) {
        $args += @('-e', "FRESH38_REMOTE_STDERR_PATH=$RemoteStderrPath")
    }
    $runnerArgs = @(
        $Mode,
        'corpus-v2.json',
        $RemoteOut,
        $CaseId
    )
    $args += @(
        $Container,
        'python',
        '-u',
        '-c',
        (New-RunnerBootstrapCode)
    )
    $args += $runnerArgs
    $argvForLog = ($args -join ' ')
    $startedAt = (Get-Date).ToString('o')
    Log "EXEC_START $CaseId process=docker attempt_id=$AttemptId started_at=$startedAt argv=docker $argvForLog"
    $psi = New-DockerProcessStartInfo $args
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    $identityAtStart = Read-HostProcessIdentity $proc
    Log "EXEC_PROCESS $CaseId host_docker_pid=$($proc.Id) parent_pid=$($identityAtStart.parent_pid) file=$($psi.FileName) start_time=$($identityAtStart.start_time)"
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
    $stderrTask = $proc.StandardError.ReadToEndAsync()
    $proc.WaitForExit()
    $stdoutTask.Wait()
    $stderrTask.Wait()
    $identityAfterExit = Read-HostProcessIdentity $proc
    # These are Docker attach-stream bytes, not runner telemetry. They are kept only as
    # client diagnostics and are overwritten by runner log files after exact Exec closure.
    Set-Content -LiteralPath $StdoutPath -Value $stdoutTask.Result -Encoding UTF8
    Set-Content -LiteralPath $StderrPath -Value $stderrTask.Result -Encoding UTF8
    $endedAt = (Get-Date).ToString('o')
    $exitKnown = $true
    $exitCode = [int]$proc.ExitCode
    Log "EXEC_DONE $CaseId process=docker pid=$($proc.Id) exit=$exitCode exit_known=$exitKnown ended_at=$endedAt"
    return [pscustomobject]@{
        exit_code  = $exitCode
        exit_known = $exitKnown
        pid        = $proc.Id
        started_at = $startedAt
        ended_at   = $endedAt
        file_name  = $psi.FileName
        arguments  = $psi.Arguments
        identity_at_start = $identityAtStart
        identity_after_exit = $identityAfterExit
        argv       = 'docker ' + (($args | ForEach-Object { [string]$_ }) -join ' ')
        remote_stdout_path = $RemoteStdoutPath
        remote_stderr_path = $RemoteStderrPath
        attach_stdout = [string]$stdoutTask.Result
        attach_stderr = [string]$stderrTask.Result
        attach_stdout_len = ([string]$stdoutTask.Result).Length
        attach_stderr_len = ([string]$stderrTask.Result).Length
    }
}

function Invoke-CaseSubprocessViaEngineApi(
    [string]$Container,
    [string]$Mode,
    [string]$RemoteOut,
    [string]$CaseId,
    [string]$StdoutPath,
    [string]$StderrPath,
    [string]$AttemptId,
    [string]$RemoteStdoutPath,
    [string]$RemoteStderrPath,
    [int]$LifecycleDeadlineSeconds
) {
    $pipeName = Get-DockerNpipeName
    if (-not $pipeName) {
        Log "EXEC_START $CaseId process=docker_engine_api attempt_id=$AttemptId failed_before_start reason=docker_host_not_npipe"
        return [pscustomobject]@{
            exit_code = 1
            exit_known = $true
            pid = $null
            started_at = (Get-Date).ToString('o')
            ended_at = (Get-Date).ToString('o')
            file_name = 'python'
            arguments = 'docker_engine_api_npipe_unavailable'
            identity_at_start = $null
            identity_after_exit = $null
            argv = 'docker-engine-api exec'
            remote_stdout_path = $RemoteStdoutPath
            remote_stderr_path = $RemoteStderrPath
            attach_stdout = ''
            attach_stderr = 'docker_host_not_npipe'
            attach_stdout_len = 0
            attach_stderr_len = 'docker_host_not_npipe'.Length
            execution_channel = 'docker_engine_api_npipe'
            exact_exec_id = ''
            engine_api = [ordered]@{ ok = $false; reason = 'docker_host_not_npipe' }
        }
    }

    $lifecycleDiag = if ($env:FRESH38_LIFECYCLE_DIAG) { [string]$env:FRESH38_LIFECYCLE_DIAG } else { '1' }
    $lifecycleDiagCase = if ($env:FRESH38_LIFECYCLE_DIAG_CASE) { [string]$env:FRESH38_LIFECYCLE_DIAG_CASE } else { $CaseId }
    $envList = @(
        "FRESH38_LIFECYCLE_DIAG=$lifecycleDiag",
        "FRESH38_ATTEMPT_ID=$AttemptId",
        "FRESH38_ARTIFACT_PATH=$RemoteOut",
        "FRESH38_REMOTE_STDOUT_PATH=$RemoteStdoutPath",
        "FRESH38_REMOTE_STDERR_PATH=$RemoteStderrPath"
    )
    if ($lifecycleDiagCase) {
        $envList += "FRESH38_LIFECYCLE_DIAG_CASE=$lifecycleDiagCase"
    }
    $cmd = @(
        'python',
        '-u',
        '-c',
        (New-RunnerBootstrapCode),
        $Mode,
        'corpus-v2.json',
        $RemoteOut,
        $CaseId
    )
    $spec = [ordered]@{
        container = $Container
        working_dir = '/tmp/fresh38-sentinel'
        cmd = $cmd
        env = $envList
        lifecycle_deadline_seconds = $LifecycleDeadlineSeconds
    }
    $specJson = $spec | ConvertTo-Json -Depth 20 -Compress
    $argvForLog = "POST /containers/$Container/exec Cmd=$($cmd -join ' ')"
    $startedAt = (Get-Date).ToString('o')
    Log "EXEC_START $CaseId process=docker_engine_api attempt_id=$AttemptId started_at=$startedAt argv=$argvForLog"

    $py = @'
import json
import os
import re
import secrets
import socket
import sys
import time

try:
    import win32file
except Exception as exc:
    print(json.dumps({"ok": False, "reason": "pywin32_unavailable", "error": f"{type(exc).__name__}: {exc}"}))
    raise SystemExit(0)

pipe = os.environ["FRESH38_DOCKER_NPIPE"]
spec = json.loads(os.environ["FRESH38_ENGINE_EXEC_SPEC"])
lifecycle_deadline_seconds = max(1, int(spec.get("lifecycle_deadline_seconds", 1800)))

def decode_chunked(body: bytes) -> bytes:
    out = bytearray()
    idx = 0
    while True:
        marker = body.find(b"\r\n", idx)
        if marker < 0:
            return body
        line = body[idx:marker].split(b";", 1)[0].strip()
        try:
            size = int(line, 16)
        except ValueError:
            return body
        idx = marker + 2
        if size == 0:
            return bytes(out)
        out.extend(body[idx:idx + size])
        idx += size + 2

def request(method: str, path: str, body_obj=None):
    body = b""
    headers = ["Host: docker", "Connection: close"]
    if body_obj is not None:
        body = json.dumps(body_obj, separators=(",", ":")).encode("utf-8")
        headers.extend(["Content-Type: application/json", f"Content-Length: {len(body)}"])
    raw = (f"{method} {path} HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body
    handle = win32file.CreateFile(
        pipe,
        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
        0,
        None,
        win32file.OPEN_EXISTING,
        0,
        None,
    )
    win32file.WriteFile(handle, raw)
    chunks = []
    read_errors = []
    while True:
        try:
            _hr, data = win32file.ReadFile(handle, 65536)
        except Exception as exc:
            read_errors.append(f"{type(exc).__name__}: {exc}")
            break
        if not data:
            break
        chunks.append(data)
    response = b"".join(chunks)
    header, _, body = response.partition(b"\r\n\r\n")
    header_text = header.decode("iso-8859-1", errors="replace")
    status_match = re.match(r"HTTP/\S+\s+(\d+)", header_text)
    status = int(status_match.group(1)) if status_match else 0
    if b"transfer-encoding: chunked" in header.lower():
        body = decode_chunked(body)
    body_text = body.decode("utf-8", errors="replace")
    parsed = None
    if body_text.strip():
        try:
            parsed = json.loads(body_text)
        except Exception:
            parsed = None
    return {
        "status": status,
        "headers": header_text,
        "body": parsed,
        "body_text": body_text,
        "body_len": len(body),
        "read_errors": read_errors,
    }

started = time.time()
deadline_at = time.monotonic() + lifecycle_deadline_seconds
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("0.0.0.0", 0))
listener.listen(1)
# A runner bootstrap should connect immediately. This remains bounded separately from the
# longer execution deadline so a never-created callback cannot stall a qualification case.
listener.settimeout(min(60, lifecycle_deadline_seconds))
callback_port = listener.getsockname()[1]
callback_token = secrets.token_urlsafe(24)
env = list(spec["env"])
env.extend([
    "FRESH38_LIFECYCLE_CALLBACK_HOST=host.docker.internal",
    f"FRESH38_LIFECYCLE_CALLBACK_PORT={callback_port}",
    f"FRESH38_LIFECYCLE_CALLBACK_TOKEN={callback_token}",
])
create_body = {
    "AttachStdin": False,
    "AttachStdout": False,
    "AttachStderr": False,
    "Tty": False,
    "WorkingDir": spec["working_dir"],
    "Env": env,
    "Cmd": spec["cmd"],
}
def parse_lifecycle_lines(text: str):
    parsed = []
    for line in text.splitlines():
        if not line.startswith(callback_token + " "):
            parsed.append({"trusted": False, "raw": line})
            continue
        payload = line[len(callback_token) + 1:]
        try:
            obj = json.loads(payload)
        except Exception:
            obj = {"event": "malformed", "raw": payload}
        obj["trusted"] = True
        parsed.append(obj)
    return parsed

try:
    create = request("POST", f"/containers/{spec['container']}/exec", create_body)
    exec_id = (create.get("body") or {}).get("Id", "")
    start_started = time.time()
    start = request("POST", f"/exec/{exec_id}/start", {"Detach": True, "Tty": False}) if exec_id else {"status": 0, "body_len": 0, "body_text": "", "read_errors": []}
    start_ended = time.time()
    lifecycle = {
        "connected": False,
        "done": False,
        "accepted": False,
        "accept_error": "",
        "remote_addr": "",
        "bytes": 0,
        "lines": [],
        "callback_port": callback_port,
        "deadline_seconds": lifecycle_deadline_seconds,
        "deadline_exceeded": False,
        "status": "WAITING",
    }
    if exec_id and start.get("status") in (200, 201):
        try:
            conn, addr = listener.accept()
            lifecycle["accepted"] = True
            lifecycle["status"] = "CONNECTED"
            lifecycle["remote_addr"] = f"{addr[0]}:{addr[1]}"
            chunks = []
            with conn:
                while True:
                    remaining = deadline_at - time.monotonic()
                    if remaining <= 0:
                        raise socket.timeout("lifecycle deadline exceeded")
                    conn.settimeout(remaining)
                    data = conn.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
            callback_text = b"".join(chunks).decode("utf-8", errors="replace")
            lifecycle["bytes"] = len(callback_text.encode("utf-8"))
            lifecycle["lines"] = parse_lifecycle_lines(callback_text)
            lifecycle["connected"] = any(item.get("trusted") and item.get("event") == "connected" for item in lifecycle["lines"])
            lifecycle["done"] = any(item.get("trusted") and item.get("event") == "runner_done" for item in lifecycle["lines"])
            lifecycle["status"] = "EOF"
        except socket.timeout as exc:
            lifecycle["deadline_exceeded"] = True
            lifecycle["status"] = "DEADLINE_EXCEEDED"
            lifecycle["accept_error"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            lifecycle["status"] = "CALLBACK_ERROR"
            lifecycle["accept_error"] = f"{type(exc).__name__}: {exc}"
    try:
        listener.close()
    except Exception:
        pass
    inspect = request("GET", f"/exec/{exec_id}/json") if exec_id else {"status": 0, "body": None}
    inspect_body = inspect.get("body") or {}
    if not exec_id:
        execution_residual_state = "NO_EXEC_CREATED"
    elif inspect.get("status") == 200 and inspect_body.get("Running") is False:
        execution_residual_state = "EXEC_TERMINAL"
    elif inspect.get("status") == 200 and inspect_body.get("Running") is True:
        execution_residual_state = "ABORTED_EXEC_MAY_STILL_BE_RUNNING"
    else:
        execution_residual_state = "EXEC_STATE_UNKNOWN"
    environment_recovery_required = execution_residual_state in (
        "ABORTED_EXEC_MAY_STILL_BE_RUNNING",
        "EXEC_STATE_UNKNOWN",
    )
    ok = (
        bool(exec_id)
        and create.get("status") in (200, 201)
        and start.get("status") in (200, 201)
        and lifecycle["connected"]
        and lifecycle["done"]
        and inspect.get("status") == 200
        and inspect_body.get("Running") is False
        and inspect_body.get("ExitCode") is not None
    )
    if ok:
        reason = "ok"
    elif not exec_id:
        reason = "exec_id_missing"
    elif lifecycle["deadline_exceeded"]:
        reason = "lifecycle_deadline_exceeded"
    elif not lifecycle["connected"]:
        reason = "lifecycle_callback_not_connected"
    elif not lifecycle["done"]:
        reason = "lifecycle_callback_missing_runner_done"
    elif inspect.get("status") != 200:
        reason = "exec_inspect_failed"
    elif inspect_body.get("Running") is not False:
        reason = "exec_still_running_after_lifecycle_eof"
    else:
        reason = "engine_api_exec_failed"
    print(json.dumps({
        "ok": ok,
        "reason": reason,
        "exec_id": exec_id,
        "create_status": create.get("status"),
        "start_status": start.get("status"),
        "start_body_len": start.get("body_len", 0),
        "start_body_text_prefix": (start.get("body_text") or "")[:4096],
        "start_read_errors": start.get("read_errors", []),
        "inspect_status": inspect.get("status"),
        "inspect_running": inspect_body.get("Running"),
        "inspect_exit_code": inspect_body.get("ExitCode"),
        "inspect_pid": inspect_body.get("Pid"),
        "lifecycle_channel": lifecycle,
        "execution_residual_state": execution_residual_state,
        "environment_recovery_required": environment_recovery_required,
        "duration_s": round(time.time() - started, 3),
        "start_duration_s": round(start_ended - start_started, 3),
        "create": {"status": create.get("status"), "body": create.get("body"), "body_text": create.get("body_text", "")[:4096]},
        "inspect": inspect_body,
    }, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"ok": False, "reason": "engine_api_exception", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
'@
    $oldPipe = $env:FRESH38_DOCKER_NPIPE
    $oldSpec = $env:FRESH38_ENGINE_EXEC_SPEC
    try {
        $env:FRESH38_DOCKER_NPIPE = $pipeName
        $env:FRESH38_ENGINE_EXEC_SPEC = $specJson
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = (Get-Command python -ErrorAction Stop).Source
        $psi.UseShellExecute = $false
        $psi.RedirectStandardInput = $true
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.Arguments = '-'
        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        [void]$proc.Start()
        $identityAtStart = Read-HostProcessIdentity $proc
        Log "EXEC_PROCESS $CaseId host_api_pid=$($proc.Id) parent_pid=$($identityAtStart.parent_pid) file=$($psi.FileName) start_time=$($identityAtStart.start_time)"
        $proc.StandardInput.Write($py)
        $proc.StandardInput.Close()
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()
        $proc.WaitForExit()
        $stdoutTask.Wait()
        $stderrTask.Wait()
        $identityAfterExit = Read-HostProcessIdentity $proc
        $endedAt = (Get-Date).ToString('o')
        $stdoutText = [string]$stdoutTask.Result
        $stderrText = [string]$stderrTask.Result
        $api = $null
        try { $api = $stdoutText | ConvertFrom-Json } catch { $api = $null }
        $exitCode = [int]$proc.ExitCode
        Set-Content -LiteralPath $StdoutPath -Value '' -Encoding UTF8
        Set-Content -LiteralPath $StderrPath -Value $stderrText -Encoding UTF8
        $exactExit = if ($api -and $null -ne $api.inspect_exit_code) { [string]$api.inspect_exit_code } else { '' }
        $exactRunning = if ($api -and $null -ne $api.inspect_running) { [string]$api.inspect_running } else { '' }
        Log "EXEC_DONE $CaseId process=docker_engine_api pid=$($proc.Id) host_exit=$exitCode exact_exec_exit=$exactExit exact_exec_running=$exactRunning exit_known=True ended_at=$endedAt exec_id=$([string]$api.exec_id)"
        return [pscustomobject]@{
            exit_code = $exitCode
            exit_known = $true
            pid = $proc.Id
            started_at = $startedAt
            ended_at = $endedAt
            file_name = $psi.FileName
            arguments = 'docker_engine_api_npipe ' + $specJson
            identity_at_start = $identityAtStart
            identity_after_exit = $identityAfterExit
            argv = $argvForLog
            remote_stdout_path = $RemoteStdoutPath
            remote_stderr_path = $RemoteStderrPath
            attach_stdout = ''
            attach_stderr = $stderrText
            attach_stdout_len = 0
            attach_stderr_len = $stderrText.Length
            execution_channel = 'docker_engine_api_npipe'
            exact_exec_id = if ($api) { [string]$api.exec_id } else { '' }
            engine_api = $api
            engine_api_stdout = $stdoutText
            engine_api_stderr = $stderrText
            api_client_exit_code = [int]$proc.ExitCode
        }
    } finally {
        if ($null -eq $oldPipe) { Remove-Item Env:FRESH38_DOCKER_NPIPE -ErrorAction SilentlyContinue } else { $env:FRESH38_DOCKER_NPIPE = $oldPipe }
        if ($null -eq $oldSpec) { Remove-Item Env:FRESH38_ENGINE_EXEC_SPEC -ErrorAction SilentlyContinue } else { $env:FRESH38_ENGINE_EXEC_SPEC = $oldSpec }
    }
}

function Invoke-CaseSubprocess(
    [string]$Container,
    [string]$Mode,
    [string]$RemoteOut,
    [string]$CaseId,
    [string]$StdoutPath,
    [string]$StderrPath,
    [string]$AttemptId,
    [string]$RemoteStdoutPath,
    [string]$RemoteStderrPath
) {
    if ($env:FRESH38_EXEC_CHANNEL -eq 'docker_cli') {
        return Invoke-CaseSubprocessViaDockerCli $Container $Mode $RemoteOut $CaseId $StdoutPath $StderrPath $AttemptId $RemoteStdoutPath $RemoteStderrPath
    }
    return Invoke-CaseSubprocessViaEngineApi $Container $Mode $RemoteOut $CaseId $StdoutPath $StderrPath $AttemptId $RemoteStdoutPath $RemoteStderrPath $LifecycleDeadlineSeconds
}

Log "START cases=$($CaseIds -join ',') attempt=$AttemptType#$AttemptNumber attempt_id=$AttemptId"
Log "runner=$PatchedRunner"
Log "corpus=$Corpus"

# docker must be usable before anything else. Without this check a missing docker on PATH
# still produced an experiment manifest and a "synced" log line for every product file, while
# nothing was actually copied into the container -- a capture that looks provisioned and is not.
$null = & docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -ne 0) {
    Log "ABORT docker is not available on PATH; cannot provision or run a capture"
    exit 2
}

$runnerSha = Get-Sha256 $PatchedRunner
if (-not $runnerSha) {
    Log "ABORT runner not found: $PatchedRunner"
    exit 2
}
if ($Provenance -and $Provenance.canonical_runner.sha256) {
    $expected = [string]$Provenance.canonical_runner.sha256
    if ($runnerSha -ne $expected) {
        Log "ABORT RUNNER_PROVENANCE_MISMATCH expected=$expected actual=$runnerSha path=$PatchedRunner"
        Log "      A capture must never run on an unverified harness. Update scripts/fresh38_runner_provenance.json"
        Log "      in the same commit as the harness change if this difference is intentional."
        exit 2
    }
    Log "runner_provenance=VERIFIED sha256=$runnerSha path=$PatchedRunner"
} else {
    Log "runner_provenance=UNPINNED sha256=$runnerSha"
}

# There must be exactly one canonical runner. A leftover copy that has drifted is reported
# rather than left to be picked up by some other tool that still points at the old location.
if ($Provenance -and $Provenance.deprecated_copies) {
    foreach ($stale in $Provenance.deprecated_copies) {
        $stalePath = [string]$stale.path
        if (-not [System.IO.Path]::IsPathRooted($stalePath)) {
            $stalePath = Join-Path $Workspace $stalePath
        }
        $staleSha = Get-Sha256 $stalePath
        if ($staleSha -and $staleSha -ne $runnerSha -and $stale.path -like '*run_recovery_pf*') {
            Log "WARN DEPRECATED_RUNNER_COPY_DIVERGED path=$($stale.path) sha256=$staleSha (canonical=$runnerSha)"
        }
    }
}

docker exec $Container sh -lc 'mkdir -p /tmp/fresh38-sentinel' | Out-Null
docker cp $PatchedRunner "${Container}:/tmp/fresh38-sentinel/run_recovery_pf.py"
docker cp (Join-Path $HarnessDir 'scoring.py') "${Container}:/tmp/fresh38-sentinel/scoring.py"
docker cp $Corpus "${Container}:/tmp/fresh38-sentinel/corpus-v2.json"

# ── SUT source set (CL-04) ──────────────────────────────────────────────────────────────
# Derived, never hand-curated. A hand-maintained hot-sync list has a structural blind spot: a
# product dependency that is not on the list can change the running code without changing the
# manifest hash, which is exactly how the 21/38 run was contaminated. Adding "a few more files"
# would not close the class -- only mechanical enumeration does.
#
# The set is every .py under the SUT source root, minus directories that are not executed
# product code. Enumeration is deterministic: ordinal-sorted, forward-slash relative paths,
# content hashes only -- no timestamps, no temp paths, no filesystem ordering.
if (-not $SutSourceRoot) { $SutSourceRoot = $AuditDir }
$SutSourceRoot = (Resolve-Path $SutSourceRoot).Path
$SutExcludedDirs = @('tests', '__pycache__', 'runs', 'data', '.pytest_cache', 'scripts', '.venv')

$sutFiles = Get-ChildItem -Path $SutSourceRoot -Recurse -File -Filter '*.py' |
    ForEach-Object {
        $rel = $_.FullName.Substring($SutSourceRoot.Length).TrimStart('\', '/') -replace '\\', '/'
        [pscustomobject]@{ Rel = $rel; Full = $_.FullName }
    } |
    Where-Object {
        $segments = $_.Rel.Split('/')
        $dirSegments = $segments[0..([Math]::Max(0, $segments.Count - 2))]
        if ($segments.Count -eq 1) { $dirSegments = @() }
        -not ($dirSegments | Where-Object { $SutExcludedDirs -contains $_ })
    } |
    Sort-Object -Property @{ Expression = { $_.Rel }; Ascending = $true }

$syncedHashes = [ordered]@{}
foreach ($f in $sutFiles) {
    $syncedHashes[$f.Rel] = Get-Sha256 $f.Full
}
Log "sut_source_files=$($syncedHashes.Count) root=tools/gmail_audit excluded=$($SutExcludedDirs -join ',')"

# Hotfix the whole SUT source set into the running container so the capture executes exactly the
# code that was fingerprinted. Staged and copied in one `docker cp` rather than per file: 361
# individual copies would be slow, and a partial failure mid-list is precisely the silent-drift
# failure this section exists to remove.
$stageDir = Join-Path ([System.IO.Path]::GetTempPath()) ("fresh38-sut-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
try {
    foreach ($f in $sutFiles) {
        $dest = Join-Path $stageDir ($f.Rel -replace '/', '\')
        $destParent = Split-Path $dest -Parent
        if (-not (Test-Path $destParent)) { New-Item -ItemType Directory -Force -Path $destParent | Out-Null }
        Copy-Item -LiteralPath $f.Full -Destination $dest -Force
    }
    docker cp "$stageDir\." "${Container}:/app/tools/gmail_audit/" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        # A silently failed hot-sync is the original contamination mechanism: the manifest would
        # record host hashes while the container still ran older code.
        Log "ABORT SUT hot-sync failed (docker cp exit=$LASTEXITCODE)"
        exit 2
    }
    Log "synced SUT source set ($($syncedHashes.Count) files) in one transfer"
} finally {
    Remove-Item -Recurse -Force $stageDir -ErrorAction SilentlyContinue
}

# ── Experiment manifest fingerprint (FIX-MEAS01) ────────────────────────────────────────
# The previous reuse gate checked only `parity_error`, with no proof that an existing artifact
# came from the same SUT. That silently mixed two different preclassifier states into one
# "clean" 21/38 result: 37 of 38 cases were reused from a cache captured before a hot-sync fix.
# Every artifact is now bound to the identity of the code that produced it, and reuse requires
# an exact match.
$imageId = (docker inspect --format '{{.Image}}' $Container 2>$null | Select-Object -First 1)
if (-not $imageId) {
    # The image id is part of the SUT identity; an 'unknown' placeholder would let two different
    # runtimes share one manifest hash, which is exactly what this fingerprint exists to prevent.
    Log "ABORT cannot resolve container image id for $Container"
    exit 2
}

$fingerprintParts = [ordered]@{
    wrapper_sha256  = Get-Sha256 $PSCommandPath
    runner_sha256   = $runnerSha
    scoring_sha256  = Get-Sha256 (Join-Path $HarnessDir 'scoring.py')
    corpus_sha256   = Get-Sha256 $Corpus
    container_image = [string]$imageId
    mode            = $Mode
    lifecycle_deadline_seconds = $LifecycleDeadlineSeconds
    sut_source_root = 'gmail-agent/tools/gmail_audit'
    sut_excluded    = $SutExcludedDirs
    product_files   = $syncedHashes
}
$fingerprintJson = $fingerprintParts | ConvertTo-Json -Depth 10 -Compress
$sha = [System.Security.Cryptography.SHA256]::Create()
try {
    $ExperimentManifestHash = -join (
        $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($fingerprintJson)) |
            ForEach-Object { $_.ToString('x2') }
    )
} finally {
    $sha.Dispose()
}

$experimentManifest = [ordered]@{
    experiment_manifest_hash = $ExperimentManifestHash
    attempt_id               = $AttemptId
    attempt_type             = $AttemptType
    attempt_number           = $AttemptNumber
    exec_instrumentation     = 'docker_events_exact_exec_id_v1'
    lifecycle_deadline_seconds = $LifecycleDeadlineSeconds
    out_dir                  = $OutDir
    container                = $Container
    created_at               = (Get-Date).ToString('o')
    components               = $fingerprintParts
    sut_source_file_count    = $syncedHashes.Count
}
($experimentManifest | ConvertTo-Json -Depth 12) |
    Set-Content (Join-Path $OutDir 'experiment-manifest.json') -Encoding UTF8

Log "experiment_manifest_hash=$ExperimentManifestHash"
Log "sut_source_files_fingerprinted=$($syncedHashes.Count)"

# RECOVERY_ATTEMPT artifacts live in their own subtree so a later retry can never overwrite,
# or be confused with, first-attempt reliability evidence.
$ArtifactDir = $OutDir
if ($AttemptType -eq 'RECOVERY_ATTEMPT') {
    $ArtifactDir = Join-Path $OutDir ("recovery-attempt-{0}" -f $AttemptNumber)
    New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null
    Log "recovery artifacts -> $ArtifactDir (first-attempt evidence untouched)"
}

$merged = @{
    mode = $Mode
    cases = @()
    capture_tool = 'scripts/run_fresh38_case_batch.ps1'
    started_at = (Get-Date).ToString('o')
    experiment_manifest_hash = $ExperimentManifestHash
    attempt_type = $AttemptType
    attempt_number = $AttemptNumber
    exec_instrumentation = 'docker_events_exact_exec_id_v1'
}
$failed = @()
$ok = @()
$measurementFailures = @()
$attemptedCases = @()
$runStatus = 'IN_PROGRESS'
$environmentRecoveryRequired = $false

foreach ($cid in $CaseIds) {
    $attemptedCases += $cid
    $stdout = Join-Path $ArtifactDir "one-$cid-stdout.txt"
    $stderr = Join-Path $ArtifactDir "one-$cid-stderr.txt"
    $local = Join-Path $ArtifactDir "one-$cid.json"
    $sidecar = Join-Path $ArtifactDir "one-$cid.manifest.json"
    $postExecProbe = Join-Path $ArtifactDir "one-$cid-post-exec-probe.json"
    $dockerEventsLive = Join-Path $ArtifactDir "one-$cid-docker-events-live.jsonl"
    $dockerEventsBackfill = Join-Path $ArtifactDir "one-$cid-docker-events-backfill.jsonl"
    $dockerExecEvidence = Join-Path $ArtifactDir "one-$cid-docker-exec-evidence.json"
    if ((Test-Path $local) -and -not $NoReuse) {
        try {
            # Provenance gate first: an artifact whose SUT identity is unknown or different is
            # not evidence about this SUT, no matter how valid it looks on its own.
            $artifactHash = ''
            $artifactAttempt = ''
            $artifactQualification = ''
            if (Test-Path $sidecar) {
                $sc = Get-Content $sidecar -Raw -Encoding UTF8 | ConvertFrom-Json
                $artifactHash = [string]$sc.experiment_manifest_hash
                $artifactAttempt = [string]$sc.attempt_type
                $artifactQualification = [string]$sc.measurement_qualification
            }
            if (-not $artifactHash) {
                Log "REUSE_REJECT_SUT_MISMATCH $cid reason=no_manifest_sidecar"
            } elseif ($artifactHash -ne $ExperimentManifestHash) {
                Log "REUSE_REJECT_SUT_MISMATCH $cid artifact=$artifactHash current=$ExperimentManifestHash"
            } elseif ($artifactAttempt -ne $AttemptType) {
                Log "REUSE_REJECT_ATTEMPT_MISMATCH $cid artifact=$artifactAttempt current=$AttemptType"
            } elseif ($artifactQualification -ne 'QUALIFIED') {
                Log "REUSE_REJECT_MEASUREMENT_NOT_QUALIFIED $cid qualification=$artifactQualification"
            } else {
                $validation = Test-CaseCaptureArtifact $local $cid
                if ($validation.ok) {
                    foreach ($nc in @($validation.parsed.cases)) {
                        $merged.cases += $nc
                    }
                    $ok += $cid
                    Log "REUSE $cid manifest=$artifactHash terminal=$($validation.terminal_state)"
                    continue
                } else {
                    Log "REUSE_SKIP $cid invalid_artifact=$($validation.reason)"
                }
            }
        } catch {
            Log "REUSE_SKIP $cid parse: $($_.Exception.Message)"
        }
    } elseif ((Test-Path $local) -and $NoReuse) {
        Log "REUSE_DISABLED $cid recapturing under -NoReuse"
    }
    Log "START $cid"
    $dockerHealthBefore = Get-DockerHealthSnapshot 'before_case'
    $remoteDir = "/tmp/fresh38-sentinel/$AttemptId/$cid"
    $remoteOut = "$remoteDir/one-$cid.json"
    $remoteStdout = "$remoteDir/one-$cid-stdout.txt"
    $remoteStderr = "$remoteDir/one-$cid-stderr.txt"
    docker exec $Container sh -lc "rm -rf '$remoteDir'; mkdir -p '$remoteDir'" | Out-Null
    $eventCollector = Start-DockerExecEventCollector $Container $dockerEventsLive
    $execResult = Invoke-CaseSubprocess $Container $Mode $remoteOut $cid $stdout $stderr $AttemptId $remoteStdout $remoteStderr
    $ec = [int]$execResult.exit_code
    $eventLive = @(Stop-DockerExecEventCollector $eventCollector)[-1]
    $eventBackfill = @(Get-DockerExecEventsBackfill $Container ([long]$eventCollector.since_epoch) $dockerEventsBackfill)[-1]
    $eventRecords = @()
    $eventRecords += ConvertFrom-DockerEventJsonLines ([string]$eventLive.stdout) 'live'
    $eventRecords += ConvertFrom-DockerEventJsonLines ([string]$eventBackfill.stdout) 'backfill'
    $execCorrelation = Resolve-ExactDockerExecCorrelation $eventRecords $AttemptId $remoteOut $cid
    if ($execResult.execution_channel -eq 'docker_engine_api_npipe') {
        $eventCorrelation = $execCorrelation
        $execCorrelation = New-EngineApiExecCorrelation $execResult
        $execCorrelation | Add-Member -NotePropertyName event_correlation -NotePropertyValue $eventCorrelation -Force
    }
    $execInspectAtBoundary = $null
    if ($execCorrelation.ok) {
        $execInspectAtBoundary = Invoke-DockerExecInspect ([string]$execCorrelation.exec_id)
    }
    $execInspectIdentityMatch = $false
    if ($execCorrelation.ok -and $execInspectAtBoundary -and $execInspectAtBoundary.ok -eq $true) {
        $execInspectIdentityMatch = Test-ExecInspectMatchesCase $execInspectAtBoundary $remoteOut $cid
        if ($execResult.execution_channel -eq 'docker_engine_api_npipe' -and -not $execInspectIdentityMatch) {
            $execCorrelation = [pscustomobject]@{
                ok = $false
                reason = 'exec_inspect_tokens_mismatch'
                exec_id = [string]$execCorrelation.exec_id
                all_exec_groups = $execCorrelation.all_exec_groups
                events = $execCorrelation.events
                exec_create = $execCorrelation.exec_create
                exec_start = $execCorrelation.exec_start
                exec_die = $execCorrelation.exec_die
                event_correlation = $execCorrelation.event_correlation
            }
        }
    }
    $dockerHealthAfterClient = Get-DockerHealthSnapshot 'after_docker_client_exit'
    $runnerLogCopy = [ordered]@{
        copied = $false
        reason = 'exec_not_closed'
        stdout = $null
        stderr = $null
    }
    if ($execInspectAtBoundary -and $execInspectAtBoundary.ok -eq $true -and $execInspectAtBoundary.Running -eq $false) {
        $runnerLogCopy.stdout = Copy-CaseRemoteLogFile $Container $remoteStdout $stdout
        $runnerLogCopy.stderr = Copy-CaseRemoteLogFile $Container $remoteStderr $stderr
        $runnerLogCopy.copied = [bool]($runnerLogCopy.stdout.ok -and $runnerLogCopy.stderr.ok)
        $runnerLogCopy.reason = if ($runnerLogCopy.copied) { 'exact_exec_closed' } else { 'log_copy_failed' }
    }
    $runnerIdentity = Read-RunnerIdentityFromStderr $stderr $AttemptId
    $execDieEvent = $null
    if ($execCorrelation.ok) {
        $execDieEvent = Find-DockerExecDieEvent $eventRecords ([string]$execCorrelation.exec_id)
    }
    $execDieExitCode = if ($execDieEvent) { [string]$execDieEvent.exit_code } else { '' }
    $inspectExitCodeAtBoundary = if ($execInspectAtBoundary) { $execInspectAtBoundary.ExitCode } else { $null }
    $exitParity = Get-ExecEventInspectExitCodeParity $execDieExitCode $inspectExitCodeAtBoundary
    $hostClientEarlyExit = [bool]($execResult.exit_known -and $ec -eq 0 -and $execInspectAtBoundary -and $execInspectAtBoundary.Running -eq $true)
    if ($hostClientEarlyExit) {
        Log "HOST_CLIENT_EARLY_EXIT $cid docker_exit=$ec exec_id=$($execCorrelation.exec_id) initial_running=True"
    }

    $ownershipProbe = $null
    $ownershipResult = $null
    if ([string]$runnerIdentity.pid) {
        Invoke-ContainerOwnershipProbe `
            $Container `
            $AttemptId `
            $remoteOut `
            ([string]$runnerIdentity.pid) `
            $runnerIdentity.proc_start_ticks `
            $postExecProbe | Out-Null
        $ownershipProbe = Read-JsonFileOrNull $postExecProbe
        $ownershipResult = Test-AttemptProcessOwnershipClosed $ownershipProbe $runnerIdentity
    }
    $dockerHealthAfterEvidence = Get-DockerHealthSnapshot 'after_evidence_collection'
    $dockerHealth = [ordered]@{
        before_case = $dockerHealthBefore
        after_docker_client_exit = $dockerHealthAfterClient
        after_evidence_collection = $dockerHealthAfterEvidence
        engine_health = Resolve-DockerEngineHealth @($dockerHealthBefore, $dockerHealthAfterClient, $dockerHealthAfterEvidence)
    }
    $baseExecEvidence = [ordered]@{
        attempt_id = $AttemptId
        case_id = $cid
        container = $Container
        remote_artifact_path = $remoteOut
        remote_stdout_path = $remoteStdout
        remote_stderr_path = $remoteStderr
        host_docker_process = $execResult
        runner_log_copy = $runnerLogCopy
        event_collection = [ordered]@{
            live = $eventLive
            backfill = [ordered]@{
                exit_code = $eventBackfill.exit_code
                pid = $eventBackfill.pid
                started_at = $eventBackfill.started_at
                ended_at = $eventBackfill.ended_at
                stderr = $eventBackfill.stderr
                argv = $eventBackfill.argv
            }
            live_path = $dockerEventsLive
            backfill_path = $dockerEventsBackfill
        }
        exact_exec_correlation = $execCorrelation
        exact_docker_exec_id_capture = if ($execCorrelation.ok) { 'PASS' } else { 'FAIL' }
        exec_inspect_identity_match = if ($execInspectIdentityMatch) { 'PASS' } else { 'FAIL' }
        exec_inspect_after_docker_client_exit = $execInspectAtBoundary
        exec_inspect_at_capture_boundary = $execInspectAtBoundary
        exec_die_at_capture_boundary = $execDieEvent
        exec_die_exit_code_at_capture_boundary = $execDieExitCode
        exec_event_inspect_exitcode_parity = $exitParity
        runner_identity_from_lifecycle = $runnerIdentity
        execution_residual_state = if ($execResult.engine_api) { [string]$execResult.engine_api.execution_residual_state } else { '' }
        environment_recovery_required = [bool]($execResult.engine_api -and $execResult.engine_api.environment_recovery_required -eq $true)
        docker_health = $dockerHealth
    }
    $preArtifactVerdict = Resolve-Fresh38MeasurementVerdict $execResult $execCorrelation $execInspectAtBoundary $execDieEvent $ownershipResult $null
    if ($preArtifactVerdict.execution_channel_integrity -ne 'PASS' -or $preArtifactVerdict.runner_ownership_integrity -ne 'PASS') {
        Write-CaseExecEvidence $dockerExecEvidence ([ordered]@{
            base = $baseExecEvidence
            host_client_early_exit = $hostClientEarlyExit
            final_exec_inspect = $execInspectAtBoundary
            exec_event_inspect_exitcode_parity = $exitParity
            post_exec_probe = $ownershipProbe
            attempt_process_ownership_closed = if ($ownershipResult) { $ownershipResult.status } else { 'NOT_EVALUATED' }
            artifact_at_wrapper_validation = $null
            measurement_verdict = $preArtifactVerdict
            result = if ($execResult.engine_api -and $execResult.engine_api.environment_recovery_required -eq $true) {
                'ABORTED_EXEC_MAY_STILL_BE_RUNNING'
            } else {
                'MEASUREMENT_NOT_QUALIFIED'
            }
        })
        Log "FAIL $cid measurement_qualification=$($preArtifactVerdict.measurement_qualification) failure_class=$($preArtifactVerdict.failure_class) failure_subclass=$($preArtifactVerdict.failure_subclass) docker_engine_health=$($dockerHealth.engine_health) evidence=$dockerExecEvidence"
        $measurementFailures += [pscustomobject][ordered]@{
            case_id = $cid
            failure_class = $preArtifactVerdict.failure_class
            failure_subclass = $preArtifactVerdict.failure_subclass
            measurement_qualification = $preArtifactVerdict.measurement_qualification
            evidence = (Split-Path $dockerExecEvidence -Leaf)
        }
        $failed += $cid
        if ($execResult.engine_api -and $execResult.engine_api.environment_recovery_required -eq $true) {
            $runStatus = 'ABORTED_EXEC_MAY_STILL_BE_RUNNING'
            $environmentRecoveryRequired = $true
            Log "ABORT $cid execution_residual_state=$([string]$execResult.engine_api.execution_residual_state) environment_recovery_required=True; remaining cases will not run"
            break
        }
        continue
    }

    $copyResult = Copy-CaseCaptureArtifact $Container $remoteOut $local $cid $AttemptId
    $artifactValidation = [pscustomobject][ordered]@{
        ok = [bool]$copyResult.ok
        reason = [string]$copyResult.reason
        copy_exit = $copyResult.copy_exit
        exists = Test-Path -LiteralPath $local
        size = if (Test-Path -LiteralPath $local) { (Get-Item -LiteralPath $local).Length } else { 0 }
        valid_json = [bool]($copyResult.ok)
        attempt_id = if ($copyResult.ok -and $copyResult.validation.parsed.measurement_attempt) { [string]$copyResult.validation.parsed.measurement_attempt.attempt_id } else { '' }
        case_id = if ($copyResult.ok) { [string]$copyResult.validation.actual_case_id } else { '' }
        terminal_stage = if ($copyResult.ok) { [string]$copyResult.validation.terminal_state } else { '' }
    }
    $measurementVerdict = Resolve-Fresh38MeasurementVerdict $execResult $execCorrelation $execInspectAtBoundary $execDieEvent $ownershipResult $artifactValidation
    Write-CaseExecEvidence $dockerExecEvidence ([ordered]@{
        base = $baseExecEvidence
        host_client_early_exit = $hostClientEarlyExit
        final_exec_inspect = $execInspectAtBoundary
        exec_event_inspect_exitcode_parity = $exitParity
        post_exec_probe = $ownershipProbe
        attempt_process_ownership_closed = if ($ownershipResult) { $ownershipResult.status } else { 'NOT_EVALUATED' }
        artifact_at_wrapper_validation = $artifactValidation
        measurement_verdict = $measurementVerdict
        result = if ($measurementVerdict.measurement_qualification -eq 'QUALIFIED') { 'VALID_CAPTURE' } else { 'MEASUREMENT_NOT_QUALIFIED' }
    })
    if ($measurementVerdict.measurement_qualification -ne 'QUALIFIED') {
        Log "FAIL $cid measurement_qualification=$($measurementVerdict.measurement_qualification) failure_class=$($measurementVerdict.failure_class) failure_subclass=$($measurementVerdict.failure_subclass) artifact=$($copyResult.reason) docker_engine_health=$($dockerHealth.engine_health) evidence=$dockerExecEvidence"
        $measurementFailures += [pscustomobject][ordered]@{
            case_id = $cid
            failure_class = $measurementVerdict.failure_class
            failure_subclass = $measurementVerdict.failure_subclass
            measurement_qualification = $measurementVerdict.measurement_qualification
            evidence = (Split-Path $dockerExecEvidence -Leaf)
        }
        $failed += $cid
        continue
    }

    # Bind the artifact to the SUT and exact Exec that produced it, before anything can consume it.
    ([ordered]@{
        case_id                  = $cid
        attempt_id               = $AttemptId
        docker_exec_id           = [string]$execCorrelation.exec_id
        docker_exec_evidence     = (Split-Path $dockerExecEvidence -Leaf)
        host_docker_exit_code    = $ec
        final_exec_exit_code     = $execInspectAtBoundary.ExitCode
        exec_die_exit_code       = $execDieExitCode
        exec_exitcode_parity     = $exitParity
        host_client_early_exit   = $hostClientEarlyExit
        measurement_qualification = $measurementVerdict.measurement_qualification
        measurement_verdict      = $measurementVerdict
        experiment_manifest_hash = $ExperimentManifestHash
        attempt_type             = $AttemptType
        attempt_number           = $AttemptNumber
        captured_at              = (Get-Date).ToString('o')
        artifact_sha256          = Get-Sha256 $local
        container                = $Container
        mode                     = $Mode
    } | ConvertTo-Json -Depth 8) | Set-Content $sidecar -Encoding UTF8

    try {
        $j = $copyResult.validation.parsed
        foreach ($nc in @($j.cases)) {
            $merged.cases += $nc
        }
        $ok += $cid
        Log "OK $cid terminal=$($copyResult.validation.terminal_state) product_outcome=$($copyResult.validation.product_outcome)"
    } catch {
        Log "FAIL $cid parse: $($_.Exception.Message)"
        $failed += $cid
    }
}

if ($runStatus -eq 'IN_PROGRESS') {
    $runStatus = if ($failed.Count -gt 0) { 'COMPLETED_NOT_QUALIFIED' } else { 'COMPLETED' }
}

$merged.completed_at = (Get-Date).ToString('o')
$merged.ok_cases = $ok
$merged.failed_cases = $failed
$merged.measurement_failures = $measurementFailures
$merged.run_status = $runStatus
$merged.requested_cases = @($CaseIds)
$merged.attempted_cases = @($attemptedCases)
$merged.remaining_cases = @($CaseIds | Where-Object { $attemptedCases -notcontains $_ })
$merged.environment_recovery_required = $environmentRecoveryRequired
$resultsName = if ($AttemptType -eq 'RECOVERY_ATTEMPT') {
    "fresh38-recovery-attempt-$AttemptNumber-results.json"
} else {
    'fresh38-partial-results.json'
}
($merged | ConvertTo-Json -Depth 40) | Set-Content (Join-Path $ArtifactDir $resultsName) -Encoding UTF8

Log "DONE status=$runStatus ok=$($ok.Count) failed=$($failed.Count) attempted=$($attemptedCases.Count)/$($CaseIds.Count) recovery_required=$environmentRecoveryRequired attempt=$AttemptType#$AttemptNumber out=$ArtifactDir"
if ($failed.Count -gt 0) { exit 1 }
exit 0
