from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_os_task_constants import (
    REGISTRY_LOCK_NAME, REGISTRY_LOCK_TIMEOUT_SECONDS,
    REPO_COMMIT_LOCK_TIMEOUT_SECONDS, TASK_CHECKPOINT_LOCK_TIMEOUT_SECONDS, _HELD_FILE_LOCKS,
)
from ai_os_task_errors import TaskError
from ai_os_task_git import repo_path
from ai_os_task_paths import state_dir, utc_now

def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
                return False
            return int(exit_code.value) == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

def _read_lock_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("pid="):
            raw = line.split("=", 1)[1].strip().split()[0]
            try:
                return int(raw)
            except ValueError:
                return None
    return None

class FilePidLock:
    """Exclusive file lock with PID liveness checks (reentrant in-process)."""

    def __init__(
        self,
        path: Path,
        *,
        label: str,
        timeout_seconds: float,
        allow_wait: bool = True,
    ) -> None:
        self.path = path
        self.label = label
        self.timeout_seconds = timeout_seconds
        self.allow_wait = allow_wait
        self.fd: int | None = None
        self._nested = False
        self._key = ""

    def __enter__(self) -> FilePidLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._key = str(self.path.resolve())
        if self._key in _HELD_FILE_LOCKS:
            self._nested = True
            return self
        deadline = time.time() + self.timeout_seconds
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"pid={os.getpid()} time={utc_now()}\n".encode())
                _HELD_FILE_LOCKS.add(self._key)
                return self
            except FileExistsError as exc:
                owner_pid = _read_lock_pid(self.path)
                if owner_pid is not None and not _pid_is_alive(owner_pid):
                    try:
                        self.path.unlink()
                        continue
                    except FileNotFoundError:
                        continue
                if not self.allow_wait:
                    age = time.time() - self.path.stat().st_mtime if self.path.exists() else 0.0
                    raise TaskError(
                        f"{self.label} already exists: {self.path} "
                        f"(pid={owner_pid if owner_pid is not None else '?'} age {age:.0f}s)"
                    ) from exc
                if time.time() >= deadline:
                    raise TaskError(f"{self.label} timeout: {self.path}") from exc
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._nested:
            return
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        _HELD_FILE_LOCKS.discard(self._key)

class RegistryLock(FilePidLock):
    def __init__(self) -> None:
        super().__init__(
            state_dir() / "locks" / REGISTRY_LOCK_NAME,
            label="registry lock",
            timeout_seconds=REGISTRY_LOCK_TIMEOUT_SECONDS,
            allow_wait=True,
        )

class TaskCheckpointLock(FilePidLock):
    def __init__(self, task_id: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)
        super().__init__(
            state_dir() / "locks" / f"task-{safe}.lock",
            label="task checkpoint lock",
            timeout_seconds=TASK_CHECKPOINT_LOCK_TIMEOUT_SECONDS,
            allow_wait=True,
        )

class RepoCommitLock(FilePidLock):
    def __init__(self, repo: str):
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", repo)
        super().__init__(
            state_dir() / "locks" / f"git-{safe}.lock",
            label="git commit lock",
            timeout_seconds=REPO_COMMIT_LOCK_TIMEOUT_SECONDS,
            # Live owner: fail fast. Dead PID: steal inside FilePidLock.
            allow_wait=False,
        )
