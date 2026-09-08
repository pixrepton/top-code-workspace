"""Mediated command execution — sole runtime path for trusted proof-bearing runs."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_os_execution.execution_context import compile_execution_context
from ai_os_execution.lease import heartbeat_lease
from ai_os_execution.receipt import write_command_receipt
from ai_os_execution.tainted import assert_not_tainted_for_proof
from ai_os_task_errors import TaskError
from ai_os_task_git import run
from ai_os_task_paths import utc_now


@dataclass
class MediatedResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    receipt: dict[str, Any] | None
    context: dict[str, Any] | None
    timed_out: bool = False


def _repo_sha(worktree: Path) -> str:
    if not worktree.exists():
        return ""
    return run(["git", "rev-parse", "--verify", "HEAD"], worktree).stdout.strip()


def _terminate_owned_process_tree(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def run_mediated_command(
    *,
    execution_id: str,
    repo: str,
    operation_kind: str,
    command: list[str],
    generation: int | None = None,
    fencing_token_value: str | None = None,
    gate_timeout: int = 0,
    bundle: dict[str, Any] | None = None,
) -> MediatedResult:
    if not command:
        raise TaskError("mediated execution requires a command")
    context = compile_execution_context(
        execution_id=execution_id,
        repo=repo,
        operation_kind=operation_kind,
        generation=generation,
        fencing_token_value=fencing_token_value,
    )
    if bundle is not None:
        assert_not_tainted_for_proof(bundle, operation_kind=operation_kind)
        heartbeat_lease(execution_id)

    cwd = Path(context["cwd"])
    started_at = utc_now()
    sha_before = _repo_sha(cwd)
    artifact_dir = Path(context["artifact_root"]) / started_at.replace(":", "-")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = artifact_dir / "stdout.log"
    stderr_path = artifact_dir / "stderr.log"

    creationflags = 0
    start_new_session = False
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        start_new_session = True

    start = time.time()
    timed_out = False
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=context["synthesized_env"],
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
        stdout, stderr = proc.communicate(timeout=gate_timeout if gate_timeout else None)
    except subprocess.TimeoutExpired:
        _terminate_owned_process_tree(proc)
        stdout, stderr = proc.communicate()
        timed_out = True
        exit_code = proc.returncode
    else:
        exit_code = proc.returncode if proc.returncode is not None else 1

    duration = round(time.time() - start, 3)
    stdout_path.write_text(stdout or "", encoding="utf-8", newline="\n")
    stderr_path.write_text(stderr or "", encoding="utf-8", newline="\n")
    finished_at = utc_now()
    sha_after = _repo_sha(cwd)

    receipt = write_command_receipt(
        context=context,
        command=command,
        exit_code=1 if timed_out else int(exit_code or 0),
        repo_sha_before=sha_before,
        repo_sha_after=sha_after,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started_at=started_at,
        finished_at=finished_at,
    )

    return MediatedResult(
        exit_code=1 if timed_out else int(exit_code or 0),
        stdout=stdout or "",
        stderr=stderr or "",
        duration_seconds=duration,
        receipt=receipt,
        context=context,
        timed_out=timed_out,
    )
