# Fresh38 Engine API lifecycle-channel regression. Uses a local Engine API shim;
# no live container, provider, judge, scoring, or product code is executed here.

$ErrorActionPreference = 'Stop'
$Workspace = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Wrapper = Join-Path $Workspace 'scripts\run_fresh38_case_batch.ps1'
$source = Get-Content -LiteralPath $Wrapper -Raw -Encoding UTF8

$failures = @()
function Check([bool]$condition, [string]$label) {
    if ($condition) { Write-Host "  PASS  $label" }
    else { Write-Host "  FAIL  $label" -ForegroundColor Red; $script:failures += $label }
}

Write-Host "`n[1/6] Engine channel uses callback EOF, not attached stream EOF"
Check ($source -match 'FRESH38_LIFECYCLE_CALLBACK_HOST=host\.docker\.internal') 'exact Exec receives host callback endpoint'
Check ($source -match 'callback_sock = socket\.create_connection') 'runner process opens the lifecycle socket itself'
Check ($source -match 'os\._exit\(exit_code\)') 'socket EOF is owned by exact process exit'

Write-Host "`n[2/6] Engine API ExecStart is not attached as lifecycle completion"
Check ($source -match '"AttachStdout": False') 'Engine API exec create does not attach stdout'
Check ($source -match '"AttachStderr": False') 'Engine API exec create does not attach stderr'
Check ($source -match 'request\("POST", f"/exec/\{exec_id\}/start", \{"Detach": True, "Tty": False\}\)') 'Engine API exec start is detached'
Check ($source -notmatch 'request\("POST", f"/exec/\{exec_id\}/start", \{"Detach": False, "Tty": False\}\)') 'attached Engine API start is not used'

Write-Host "`n[3/6] Host client exit remains separate from exact Exec exit"
Check ($source -match '\$exitCode = \[int\]\$proc\.ExitCode') 'host exit_code is the host API client exit'
Check ($source -notmatch '\$exitCode = \[int\]\$api\.inspect_exit_code') 'exact Exec exit does not overwrite host client exit'
Check ($source -match 'exact_exec_exit=\$exactExit') 'exact Exec exit is logged separately'

Write-Host "`n[4/6] Exact Exec must be closed after callback EOF"
Check ($source -match 'inspect_body\.get\("Running"\) is False') 'callback EOF still requires ExecInspect Running=false'
Check ($source -match 'inspect_body\.get\("ExitCode"\) is not None') 'callback EOF still requires an exact Exec exit code'
Check ($source -match 'exec_still_running_after_lifecycle_eof') 'running exact Exec after callback EOF is an explicit failure'

Write-Host "`n[5/6] The repair is not an unbounded wait for completion"
Check ($source -notmatch 'ExecCompletionTimeoutSeconds\s*=\s*[1-9]') 'no post-client completion timeout is introduced'
Check ($source -match 'inspect_confirm_window_s = 5\.0') 'terminal-state confirmation uses a small bounded window'
Check ($source -match 'lifecycle\["done"\] and lifecycle\["status"\] == "EOF"') 'confirm window is gated on the callback EOF process-exit edge'
Check ($source -notmatch 'inspect_confirm_window_s = .*lifecycle_deadline_seconds') 'confirm window is not derived from the lifecycle deadline'
Check ($source -match 'exec_still_running_after_lifecycle_eof') 'persistent Running=true after the window still fails closed'
Check ($source -match 'win32pipe\.WaitNamedPipe\(pipe, 1000\)') 'npipe connect retries transient ERROR_PIPE_BUSY via WaitNamedPipe'
Check ($source -match 'if getattr\(exc, "winerror", None\) != 231:') 'only ERROR_PIPE_BUSY (231) triggers the retry'
Check ($source -match 'except pywintypes\.error:\s*\r?\n\s+pass') 'WaitNamedPipe transient raises stay inside the bounded 231 retry'
Check ($source -match 'def connect_pipe\(timeout_s=5\.0\):') 'npipe connect retry is bounded'
Check ($source -match 'Find-DockerExecDieEvent') 'exec_die remains evidence/parity only'
Check ($source -match 'ABORTED_EXEC_MAY_STILL_BE_RUNNING') 'a non-terminal aborted Exec has an explicit residual state'
Check ($source -match 'remaining cases will not run') 'batch does not continue after an abort with uncertain Exec ownership'

Write-Host "`n[6/6] Product runner semantics stay in the canonical runner"
Check ($source -match 'runpy\.run_path\("run_recovery_pf\.py", run_name="__main__"\)') 'canonical runner is still executed'
Check ($source -notmatch 'judge_run\s*=\s*''YES''') 'wrapper does not enable judge'
Check ($source -notmatch 'scoring_run\s*=\s*''YES''') 'wrapper does not enable scoring'

Write-Host "`n[behavior] Engine lifecycle callback is part of the qualification contract"
$root = Join-Path ([System.IO.Path]::GetTempPath()) ("f38-engine-channel-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Force -Path $root | Out-Null
$oldDockerHost = $env:DOCKER_HOST
$oldPythonPath = $env:PYTHONPATH
$oldScenario = $env:F38_ENGINE_TEST_SCENARIO
$oldState = $env:F38_ENGINE_TEST_STATE
$oldCounter = $env:F38_ENGINE_TEST_COUNTER
$oldPath = $env:PATH

try {
    @'
import json
import os
import socket
import threading
import time
from pathlib import Path

GENERIC_READ = 1
GENERIC_WRITE = 2
OPEN_EXISTING = 3
_exec_env = []
_exec_cmd = []
_connect_count = [0]


def _write_state():
    state_path = os.environ.get("F38_ENGINE_TEST_STATE", "")
    if state_path:
        Path(state_path).write_text(json.dumps({"env": _exec_env, "cmd": _exec_cmd}), encoding="utf-8")


def _read_state():
    state_path = os.environ.get("F38_ENGINE_TEST_STATE", "")
    if not state_path or not Path(state_path).exists():
        return {"env": _exec_env, "cmd": _exec_cmd}
    return json.loads(Path(state_path).read_text(encoding="utf-8"))


class _Handle:
    def __init__(self):
        self.response = b""
        self.offset = 0


def _response(status, payload=None):
    body = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    reason = {200: "OK", 201: "Created"}.get(status, "Error")
    return (
        f"HTTP/1.1 {status} {reason}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
        + body
    )


def _callback(env):
    scenario = os.environ.get("F38_ENGINE_TEST_SCENARIO", "normal")
    if scenario == "deadline":
        return
    values = {}
    for item in env:
        if "=" in item:
            key, value = item.split("=", 1)
            values[key] = value
    host = "127.0.0.1"
    port = int(values["FRESH38_LIFECYCLE_CALLBACK_PORT"])
    token = values["FRESH38_LIFECYCLE_CALLBACK_TOKEN"]

    def send():
        time.sleep(0.05)
        with socket.create_connection((host, port), timeout=2) as conn:
            if scenario == "bad_token":
                conn.sendall(b"untrusted-token {\"event\":\"connected\"}\n")
                return
            connected = {"event": "connected", "attempt_id": "attempt", "artifact_path": "/tmp/out.json"}
            done = {"event": "runner_done", "attempt_id": "attempt", "artifact_path": "/tmp/out.json", "exit_code": 0}
            conn.sendall((token + " " + json.dumps(connected, separators=(",", ":")) + "\n").encode("utf-8"))
            conn.sendall((token + " " + json.dumps(done, separators=(",", ":")) + "\n").encode("utf-8"))

    threading.Thread(target=send, daemon=True).start()


def CreateFile(*_args):
    scenario = os.environ.get("F38_ENGINE_TEST_SCENARIO", "normal")
    _connect_count[0] += 1
    if scenario == "pipe_busy_persistent" or (scenario == "pipe_busy_once" and _connect_count[0] == 1):
        import pywintypes
        raise pywintypes.error(231, "CreateFile", "All pipe instances are busy")
    return _Handle()


def WriteFile(handle, raw):
    global _exec_env, _exec_cmd
    head, _, body = raw.partition(b"\r\n\r\n")
    first = head.split(b"\r\n", 1)[0].decode("ascii")
    _method, path, _version = first.split(" ", 2)
    request_body = json.loads(body.decode("utf-8")) if body else {}
    if path.endswith("/exec"):
        _exec_env = list(request_body.get("Env", []))
        _exec_cmd = list(request_body.get("Cmd", []))
        _write_state()
        handle.response = _response(201, {"Id": "engine-test-exec"})
    elif path.endswith("/start"):
        _callback(_read_state().get("env", []))
        handle.response = _response(200)
    elif path.endswith("/json"):
        scenario = os.environ.get("F38_ENGINE_TEST_SCENARIO", "normal")
        counter_path = os.environ.get("F38_ENGINE_TEST_COUNTER", "")
        json_calls = 0
        if counter_path:
            json_calls = int(Path(counter_path).read_text(encoding="utf-8")) if Path(counter_path).exists() else 0
            json_calls += 1
            Path(counter_path).write_text(str(json_calls), encoding="utf-8")
        running = scenario in ("deadline", "running_after_eof")
        if scenario == "running_then_terminal":
            running = json_calls <= 2
        state = _read_state()
        cmd = state.get("cmd", []) or ["python", "run_recovery_pf.py", "/tmp/out.json", "STUB-01"]
        handle.response = _response(200, {
            "ID": "engine-test-exec",
            "Running": running,
            "ExitCode": None if running else 0,
            "Pid": 4242,
            "ProcessConfig": {
                "entrypoint": cmd[0],
                "arguments": cmd[1:],
            },
            "ContainerID": "stub-container-id",
        })
    else:
        handle.response = _response(404, {"message": "not found"})
    return 0, len(raw)


def ReadFile(handle, size):
    if handle.offset >= len(handle.response):
        return 0, b""
    data = handle.response[handle.offset:handle.offset + size]
    handle.offset += len(data)
    return 0, data
'@ | Set-Content -LiteralPath (Join-Path $root 'win32file.py') -Encoding ASCII

    $tokens = $null
    $parseErrors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Wrapper, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        throw "wrapper parse failed: $($parseErrors[0].Message)"
    }
    $requiredFunctions = @(
        'Log',
        'Get-DockerNpipeName',
        'Read-HostProcessIdentity',
        'New-RunnerBootstrapCode',
        'Get-JsonPropertyValue',
        'Get-ExecEventInspectExitCodeParity',
        'New-Fresh38MeasurementVerdict',
        'Get-ArtifactFailureSubclass',
        'Get-OwnershipFailureSubclass',
        'Get-EngineApiLifecycleFailureSubclass',
        'Resolve-Fresh38MeasurementVerdict',
        'Invoke-CaseSubprocessViaEngineApi'
    )
    foreach ($name in $requiredFunctions) {
        $definition = $ast.FindAll({
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
        }, $true) | Select-Object -First 1
        if (-not $definition) { throw "missing wrapper function: $name" }
        Invoke-Expression $definition.Extent.Text
    }

    $script:log = Join-Path $root 'engine-test.log'
    $env:DOCKER_HOST = 'npipe:////./pipe/fresh38-engine-test'
    $env:PYTHONPATH = if ($oldPythonPath) { "$root;$oldPythonPath" } else { $root }
    $env:F38_ENGINE_TEST_STATE = Join-Path $root 'engine-state.json'
    $env:F38_ENGINE_TEST_COUNTER = Join-Path $root 'engine-counter.txt'

    function Invoke-EngineScenario([string]$scenario) {
        $env:F38_ENGINE_TEST_SCENARIO = $scenario
        Remove-Item -LiteralPath $env:F38_ENGINE_TEST_COUNTER -ErrorAction SilentlyContinue
        $stdout = Join-Path $root "$scenario-stdout.txt"
        $stderr = Join-Path $root "$scenario-stderr.txt"
        return Invoke-CaseSubprocessViaEngineApi `
            'stub-container' `
            'production_faithful' `
            '/tmp/out.json' `
            'STUB-01' `
            $stdout `
            $stderr `
            'attempt' `
            '/tmp/stdout.txt' `
            '/tmp/stderr.txt' `
            $(if ($scenario -eq 'deadline') { 1 } else { 5 })
    }

    $normal = Invoke-EngineScenario 'normal'
    Check ($normal.engine_api.ok -eq $true) 'valid callback plus terminal Exec is accepted by the Engine channel'

    $runningThenTerminal = Invoke-EngineScenario 'running_then_terminal'
    Check ($runningThenTerminal.engine_api.ok -eq $true) 'daemon state flip shortly after callback EOF is confirmed and accepted'
    Check ($runningThenTerminal.engine_api.inspect_confirm_attempts -ge 2) 'confirmation re-inspects when the first ExecInspect races the flip'
    Check ($runningThenTerminal.engine_api.inspect_confirm_duration_s -ge 0.4) 'confirmation window duration is recorded'

    $pipeBusyOnce = Invoke-EngineScenario 'pipe_busy_once'
    Check ($pipeBusyOnce.engine_api.ok -eq $true) 'npipe 231 once is retried (WaitNamedPipe) and the case is accepted'
    Check ($pipeBusyOnce.engine_api.inspect_confirm_attempts -eq 1) 'busy-once case still confirms the terminal Exec'

    $pipeBusyPersistent = Invoke-EngineScenario 'pipe_busy_persistent'
    Check ($pipeBusyPersistent.engine_api.ok -eq $false) 'persistent npipe 231 fails closed'
    Check ($pipeBusyPersistent.engine_api.reason -eq 'engine_api_exception') 'persistent 231 surfaces as engine_api_exception'

    $badToken = Invoke-EngineScenario 'bad_token'
    Check ($badToken.engine_api.ok -eq $false) 'untrusted callback is rejected by the Engine channel'
    Check ($badToken.engine_api.reason -eq 'lifecycle_callback_not_connected') 'untrusted callback receives an explicit reason'

    $correlation = [pscustomobject]@{ ok = $true; exec_id = 'engine-test-exec' }
    $inspect = [pscustomobject]@{ ok = $true; Running = $false; ExitCode = 0 }
    $ownership = [pscustomobject]@{ ok = $true }
    $artifact = [pscustomobject]@{ ok = $true }
    $badVerdict = Resolve-Fresh38MeasurementVerdict $badToken $correlation $inspect $null $ownership $artifact
    Check ($badVerdict.measurement_qualification -eq 'NOT_QUALIFIED') 'invalid callback cannot qualify even when Exec and artifact are terminal'
    Check ($badVerdict.failure_subclass -eq 'LIFECYCLE_CALLBACK_INVALID') 'invalid callback has a dedicated fail-closed subclass'

    $runningAfterEof = Invoke-EngineScenario 'running_after_eof'
    Check ($runningAfterEof.engine_api.ok -eq $false) 'callback EOF cannot qualify while the exact Exec is still running'
    Check ($runningAfterEof.engine_api.reason -eq 'exec_still_running_after_lifecycle_eof') 'running-after-EOF reason is explicit'
    Check ($runningAfterEof.engine_api.execution_residual_state -eq 'ABORTED_EXEC_MAY_STILL_BE_RUNNING') 'running-after-EOF requires environment recovery'
    $runningInspect = [pscustomobject]@{ ok = $true; Running = $true; ExitCode = $null }
    $runningVerdict = Resolve-Fresh38MeasurementVerdict $runningAfterEof $correlation $runningInspect $null $null $null
    Check ($runningVerdict.measurement_qualification -eq 'NOT_QUALIFIED') 'Running=true can never qualify on the callback channel'
    Check ($runningVerdict.failure_subclass -eq 'EXEC_STILL_RUNNING_AFTER_LIFECYCLE_EOF') 'running-after-EOF has a dedicated fail-closed subclass'

    $deadlineStarted = [DateTimeOffset]::UtcNow
    $deadline = Invoke-EngineScenario 'deadline'
    $deadlineElapsed = ([DateTimeOffset]::UtcNow - $deadlineStarted).TotalSeconds
    Check ($deadlineElapsed -lt 5) 'missing callback returns at the declared test deadline'
    Check ($deadline.engine_api.ok -eq $false) 'lifecycle deadline cannot produce success'
    Check ($deadline.engine_api.reason -eq 'lifecycle_deadline_exceeded') 'deadline failure reason is explicit'
    Check ($deadline.engine_api.execution_residual_state -eq 'ABORTED_EXEC_MAY_STILL_BE_RUNNING') 'deadline records that the exact Exec may still run'
    Check ($deadline.engine_api.environment_recovery_required -eq $true) 'deadline requires environment recovery before another measurement'
    $deadlineVerdict = Resolve-Fresh38MeasurementVerdict $deadline $correlation $runningInspect $null $null $null
    Check ($deadlineVerdict.measurement_qualification -eq 'NOT_QUALIFIED') 'deadline is fail-closed at the measurement gate'
    Check ($deadlineVerdict.failure_subclass -eq 'LIFECYCLE_DEADLINE_EXCEEDED') 'deadline has a dedicated fail-closed subclass'

    Write-Host "`n[behavior] Batch stops when an aborted exact Exec may still be running"
    $shimDir = Join-Path $root 'docker-shim'
    New-Item -ItemType Directory -Force -Path $shimDir | Out-Null
    @'
@echo off
if "%~1"=="version" (echo 29.5.3& exit /b 0)
if "%~1"=="inspect" (echo sha256:engine-test-image& exit /b 0)
if "%~1"=="events" exit /b 0
if "%~1"=="exec" exit /b 0
if "%~1"=="cp" exit /b 0
exit /b 0
'@ | Set-Content -LiteralPath (Join-Path $shimDir 'docker.bat') -Encoding ASCII
    $env:PATH = "$shimDir;$oldPath"
    $env:F38_ENGINE_TEST_SCENARIO = 'deadline'
    Remove-Item -LiteralPath $env:F38_ENGINE_TEST_STATE -ErrorAction SilentlyContinue

    $sutRoot = Join-Path $root 'sut'
    New-Item -ItemType Directory -Force -Path $sutRoot | Out-Null
    Set-Content -LiteralPath (Join-Path $sutRoot 'stub.py') -Value 'VALUE = 1' -Encoding ASCII
    $corpus = Join-Path $root 'corpus-v2.json'
    Set-Content -LiteralPath $corpus -Value '{"cases":[{"id":"STUB-01"},{"id":"STUB-02"}]}' -Encoding ASCII
    $batchOut = Join-Path $root 'batch-abort'
    $batchOutput = & powershell -NoProfile -ExecutionPolicy Bypass -File $Wrapper `
        -CaseIds 'STUB-01,STUB-02' `
        -OutDir $batchOut `
        -Corpus $corpus `
        -HarnessDir (Join-Path $Workspace 'scripts\fresh38') `
        -Container 'stub-container' `
        -AttemptId 'behavioral_deadline_abort' `
        -SutSourceRoot $sutRoot `
        -LifecycleDeadlineSeconds 1 `
        -NoReuse 2>&1 | Out-String
    $batchExit = $LASTEXITCODE
    $batchResult = Get-Content -LiteralPath (Join-Path $batchOut 'fresh38-partial-results.json') -Raw | ConvertFrom-Json
    Check ($batchExit -ne 0) 'batch with lifecycle deadline exits non-zero'
    Check ($batchResult.run_status -eq 'ABORTED_EXEC_MAY_STILL_BE_RUNNING') 'batch result records the residual Exec state'
    Check ($batchResult.environment_recovery_required -eq $true) 'batch result requires environment recovery'
    Check (@($batchResult.attempted_cases).Count -eq 1 -and $batchResult.attempted_cases[0] -eq 'STUB-01') 'only the first case is attempted'
    Check (@($batchResult.remaining_cases) -contains 'STUB-02') 'remaining case is recorded but not executed'
    Check ($batchOutput -notmatch 'START STUB-02') 'wrapper does not automatically continue qualification'
} finally {
    if ($null -eq $oldDockerHost) { Remove-Item Env:DOCKER_HOST -ErrorAction SilentlyContinue } else { $env:DOCKER_HOST = $oldDockerHost }
    if ($null -eq $oldPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue } else { $env:PYTHONPATH = $oldPythonPath }
    if ($null -eq $oldScenario) { Remove-Item Env:F38_ENGINE_TEST_SCENARIO -ErrorAction SilentlyContinue } else { $env:F38_ENGINE_TEST_SCENARIO = $oldScenario }
    if ($null -eq $oldState) { Remove-Item Env:F38_ENGINE_TEST_STATE -ErrorAction SilentlyContinue } else { $env:F38_ENGINE_TEST_STATE = $oldState }
    if ($null -eq $oldCounter) { Remove-Item Env:F38_ENGINE_TEST_COUNTER -ErrorAction SilentlyContinue } else { $env:F38_ENGINE_TEST_COUNTER = $oldCounter }
    $env:PATH = $oldPath
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "FRESH38 ENGINE LIFECYCLE CHANNEL: FAIL ($($failures.Count))" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" }
    exit 1
}
Write-Host 'FRESH38 ENGINE LIFECYCLE CHANNEL: PASS' -ForegroundColor Green
exit 0
