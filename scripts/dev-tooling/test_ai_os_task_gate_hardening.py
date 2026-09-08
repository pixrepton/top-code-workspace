"""P0: task-gate hardening - timeout, owned-process cleanup, structured logs."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ai_os_task.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plane_harness import child_env, plane_start_args  # noqa: E402


def run_cmd(args, cwd=ROOT, env=None, check=True):
    merged_env = child_env(env)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=merged_env,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc


def git(repo, *args, check=True):
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        text=True,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc


def remove_tree(path: Path):
    def onexc(func, item, exc):
        try:
            os.chmod(item, stat.S_IWRITE)
            func(item)
        except Exception:
            raise exc

    shutil.rmtree(path, onexc=onexc)


def pid_alive(pid: int) -> bool:
    """Windows-reliable liveness via tasklist (os.kill(pid,0) sees zombies)."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    proc = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}"],
        capture_output=True,
        text=True,
    )
    return str(pid) in (proc.stdout or "")


@pytest.fixture
def task_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "tracked.txt").write_text("line\n", encoding="utf-8")
    git(source, "add", "--", "tracked.txt")
    git(source, "commit", "-m", "init")

    name = f"tmp-gate-harden-{tmp_path.name}"
    workspace_repo = ROOT / name
    if workspace_repo.exists():
        remove_tree(workspace_repo)
    git(ROOT, "clone", str(source), str(workspace_repo))
    git(workspace_repo, "config", "user.email", "test@example.invalid")
    git(workspace_repo, "config", "user.name", "Test User")
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "state")}
    try:
        yield name, workspace_repo, env
    finally:
        if workspace_repo.exists():
            remove_tree(workspace_repo)


def start_task(task_repo):
    name, _, env = task_repo
    run_cmd(
        plane_start_args(
            task_id="unit",
            title="Unit test",
            repo=name,
            scope=f"{name}:.",
        ),
        env=env,
    )


def load_state(task_repo):
    _, _, env = task_repo
    state_dir = Path(env["AI_OS_TASK_STATE_DIR"])
    return json.loads((state_dir / "tasks" / "active" / "unit.json").read_text(encoding="utf-8"))


def gate_cmd(task_repo, code: str, *flags):
    name, _, env = task_repo
    args = [
        "task-gate",
        "--task-id",
        "unit",
        "--gate-id",
        "G1",
        "--repo",
        name,
        *flags,
        "--",
        sys.executable,
        "-c",
        code,
    ]
    return run_cmd(args, env=env, check=False)


def test_gate_pass_records_log_and_command_argv(task_repo) -> None:
    start_task(task_repo)
    proc = gate_cmd(task_repo, "print('ok')")
    assert proc.returncode == 0
    assert "GATE G1: PASS" in proc.stdout
    data = load_state(task_repo)
    entry = data["gates"][-1]
    assert entry["verdict"] == "PASS"
    assert entry["command_argv"] == [sys.executable, "-c", "print('ok')"]
    assert entry["log_path"]
    assert Path(entry["log_path"]).exists()


def test_gate_fail_records_log_and_nonzero(task_repo) -> None:
    start_task(task_repo)
    proc = gate_cmd(task_repo, "import sys; sys.exit(3)")
    assert proc.returncode == 1
    data = load_state(task_repo)
    entry = data["gates"][-1]
    assert entry["verdict"] == "FAIL"
    assert entry["exit_code"] == 3
    assert entry["log_path"] and Path(entry["log_path"]).exists()


def test_gate_timeout_terminates_owned_tree(task_repo, tmp_path) -> None:
    start_task(task_repo)
    pidfile = tmp_path / "child.pid"
    code = (
        "import os, time; "
        f"open(r'{pidfile}', 'w').write(str(os.getpid())); "
        "time.sleep(60)"
    )
    proc = gate_cmd(task_repo, code, "--timeout", "2")
    assert proc.returncode == 1
    assert "TIMEOUT" in proc.stdout
    assert "HUNG_TEST" in proc.stdout
    data = load_state(task_repo)
    entry = data["gates"][-1]
    assert entry["verdict"] == "TIMEOUT"
    assert entry["diagnostics"]["failure_kind"] == "TIMEOUT"
    child = int(pidfile.read_text(encoding="utf-8").strip())
    deadline = time.time() + 8
    while time.time() < deadline and pid_alive(child):
        time.sleep(0.2)
    assert not pid_alive(child), "owned child process survived gate termination"


def test_gate_timeout_does_not_kill_unrelated_process(task_repo, tmp_path) -> None:
    start_task(task_repo)
    other_pidfile = tmp_path / "other.pid"
    other = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os, time; "
            f"open(r'{other_pidfile}', 'w').write(str(os.getpid())); "
            "time.sleep(60)",
        ]
    )
    try:
        deadline = time.time() + 10
        while not other_pidfile.exists() and time.time() < deadline:
            time.sleep(0.2)
        other_pid = int(other_pidfile.read_text(encoding="utf-8").strip())
        pidfile = tmp_path / "gated.pid"
        code = (
            "import os, time; "
            f"open(r'{pidfile}', 'w').write(str(os.getpid())); "
            "time.sleep(60)"
        )
        proc = gate_cmd(task_repo, code, "--timeout", "2")
        assert proc.returncode == 1
        assert "TIMEOUT" in proc.stdout
        time.sleep(1)
        assert pid_alive(other_pid), "unrelated user process was killed by gate cleanup"
    finally:
        other.kill()
        other.wait(timeout=10)


def test_gate_log_is_utf8(task_repo) -> None:
    start_task(task_repo)
    code = (
        "import sys; "
        "print(sys.stdout.encoding); "
        "print('draft: prosimy o dok\u0142adny opis objaw\u00f3w')"
    )
    proc = gate_cmd(task_repo, code)
    assert proc.returncode == 0
    data = load_state(task_repo)
    log = Path(data["gates"][-1]["log_path"]).read_text(encoding="utf-8")
    assert "utf-8" in log
    assert "dok\u0142adny opis objaw\u00f3w" in log


def test_gate_profile_and_raw_command_are_mutually_exclusive(task_repo) -> None:
    start_task(task_repo)
    name, _, env = task_repo
    proc = run_cmd(
        [
            "task-gate",
            "--task-id",
            "unit",
            "--gate-id",
            "GX",
            "--repo",
            name,
            "--profile",
            "P1_MULTI_INTENT",
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ],
        env=env,
        check=False,
    )
    assert proc.returncode != 0
    assert "mutually exclusive" in proc.stdout + proc.stderr


def test_gate_unknown_profile_fails_closed(task_repo) -> None:
    start_task(task_repo)
    name, _, env = task_repo
    proc = run_cmd(
        [
            "task-gate",
            "--task-id",
            "unit",
            "--gate-id",
            "GX",
            "--repo",
            name,
            "--profile",
            "NOT_A_PROFILE",
        ],
        env=env,
        check=False,
    )
    assert proc.returncode != 0
    assert "unknown test profile" in proc.stdout + proc.stderr
