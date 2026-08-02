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
TASK_SCRIPT = ROOT / "scripts" / "ai_os_task.py"
HOOK_SCRIPT = ROOT / "scripts" / "ai_os_codex_hook.py"


def run_task(args, *, cwd=ROOT, env=None, check=True):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        [sys.executable, str(TASK_SCRIPT), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=merged_env,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc


def run_hook(payload, *, cwd=ROOT, env=None, check=True):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        cwd=str(cwd),
        text=True,
        input=json.dumps(payload),
        capture_output=True,
        env=merged_env,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    data = json.loads(proc.stdout or "{}")
    return proc, data


def git(repo, *args, check=True, input_text=None):
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        text=True,
        input=input_text,
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


@pytest.fixture
def hook_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(source, "add", "--", "tracked.txt")
    git(source, "commit", "-m", "init")

    name = f"tmp-ai-os-hook-test-{tmp_path.name}"
    workspace_repo = ROOT / name
    if workspace_repo.exists():
        remove_tree(workspace_repo)
    git(ROOT, "clone", str(source), str(workspace_repo))
    git(workspace_repo, "config", "user.email", "test@example.invalid")
    git(workspace_repo, "config", "user.name", "Test User")
    nested = workspace_repo / "nested"
    nested.mkdir()
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "state")}
    try:
        yield name, workspace_repo, nested, env
    finally:
        if workspace_repo.exists():
            remove_tree(workspace_repo)


def start_task(hook_repo, *, next_action="Do the next thing."):
    name, _repo, _nested, env = hook_repo
    run_task(
        [
            "task-start",
            "--task-id",
            "hook-unit",
            "--title",
            "Hook unit",
            "--class",
            "MEDIUM",
            "--repo",
            name,
            "--scope",
            f"{name}:tracked.txt",
            "--next",
            next_action,
        ],
        env=env,
    )
    return env


def update_checkpoint(env, *args):
    run_task(["task-checkpoint", *args], env=env)


def checkpoint_json(env):
    path = Path(env["AI_OS_TASK_STATE_DIR"]) / "current-task.json"
    return json.loads(path.read_text(encoding="utf-8"))


def hook_payload(event, cwd):
    payload = {
        "session_id": "thr_test",
        "transcript_path": None,
        "cwd": str(cwd),
        "hook_event_name": event,
        "model": "gpt-test",
    }
    if event == "SessionStart":
        payload["source"] = "resume"
        payload["permission_mode"] = "default"
    elif event == "PreCompact":
        payload["trigger"] = "manual"
        payload["turn_id"] = "turn_123"
        payload["permission_mode"] = "default"
    elif event == "SessionEnd":
        payload["reason"] = "other"
    return payload


def set_status(env, status, phase):
    path = Path(env["AI_OS_TASK_STATE_DIR"]) / "current-task.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    data["current_phase"] = phase
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_session_start_without_checkpoint_is_noop(hook_repo):
    _name, repo, _nested, env = hook_repo
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data == {"continue": True}


def test_session_start_active_checkpoint_returns_compact_summary(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo, next_action="Implement lifecycle automation.")
    update_checkpoint(env, "--status", "IN_PROGRESS", "--phase", "implement-hooks")
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data["continue"] is True
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "task: hook-unit" in summary
    assert "status: IN_PROGRESS" in summary
    assert "phase: implement-hooks" in summary
    assert "next: Implement lifecycle automation." in summary


@pytest.mark.parametrize(
    ("status", "phase"),
    [
        ("CLOSED", "closed"),
        ("ABORTED_WITH_EVIDENCE", "aborted"),
    ],
)
def test_session_start_closed_or_aborted_is_noop(hook_repo, status, phase):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    set_status(env, status, phase)
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data == {"continue": True}


def test_precompact_blocks_corrupt_checkpoint(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    path = Path(env["AI_OS_TASK_STATE_DIR"]) / "current-task.json"
    path.write_text("{broken", encoding="utf-8")
    _proc, data = run_hook(hook_payload("PreCompact", repo), env=env)
    assert data["continue"] is False
    assert "corrupt" in data["stopReason"].lower()


def test_precompact_refresh_preserves_status_and_phase(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    update_checkpoint(env, "--status", "IN_PROGRESS", "--phase", "before-compact")
    before = checkpoint_json(env)
    time.sleep(1.1)
    _proc, data = run_hook(hook_payload("PreCompact", repo), env=env)
    after = checkpoint_json(env)
    assert data == {"continue": True}
    assert after["status"] == "IN_PROGRESS"
    assert after["current_phase"] == "before-compact"
    assert after["updated_at_utc"] != before["updated_at_utc"]


def test_session_end_best_effort_refreshes_active_checkpoint(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    update_checkpoint(env, "--status", "IN_PROGRESS", "--phase", "finishing")
    before = checkpoint_json(env)
    time.sleep(1.1)
    _proc, data = run_hook(hook_payload("SessionEnd", repo), env=env)
    after = checkpoint_json(env)
    assert data == {"continue": True}
    assert after["updated_at_utc"] != before["updated_at_utc"]


def test_nested_cwd_still_refreshes_and_summarizes(hook_repo):
    _name, _repo, nested, env = hook_repo
    start_task(hook_repo)
    update_checkpoint(env, "--status", "IN_PROGRESS", "--phase", "nested-run")
    _proc, data = run_hook(hook_payload("SessionStart", nested), cwd=nested, env=env)
    assert data["continue"] is True
    assert "phase: nested-run" in data["hookSpecificOutput"]["additionalContext"]


def test_summary_is_capped_and_does_not_echo_blocker_text(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo, next_action="X" * 600)
    update_checkpoint(env, "--status", "BLOCKED", "--phase", "waiting", "--blocker", "SECRET=token-value")
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert len(summary) <= 700
    assert "SECRET=token-value" not in summary
    assert "blockers_open: 1" in summary
