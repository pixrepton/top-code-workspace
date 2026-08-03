import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TASK_SCRIPT = ROOT / "scripts" / "ai_os_task.py"
HOOK_SCRIPT = ROOT / "scripts" / "ai_os_claude_hook.py"


def run_task(args, *, cwd=ROOT, env=None, check=True):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        [sys.executable, str(TASK_SCRIPT), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=merged,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc


def run_hook(payload, *, cwd=ROOT, env=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        cwd=str(cwd),
        text=True,
        input=json.dumps(payload),
        capture_output=True,
        env=merged,
    )


def git(repo, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=str(repo), text=True, capture_output=True)
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
def claude_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "task.txt").write_text("initial\n", encoding="utf-8")
    git(source, "add", "task.txt")
    git(source, "commit", "-m", "init")
    name = f"tmp-ai-os-claude-hook-{tmp_path.name}"
    repo = ROOT / name
    if repo.exists():
        remove_tree(repo)
    git(ROOT, "clone", str(source), str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test User")
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "state")}
    run_task(
        [
            "task-start",
            "--task-id",
            "claude-hook",
            "--title",
            "Claude hook",
            "--class",
            "SMALL",
            "--repo",
            name,
            "--scope",
            f"{name}:task.txt",
        ],
        env=env,
    )
    try:
        yield name, repo, env
    finally:
        if repo.exists():
            remove_tree(repo)


def payload(event, repo, *, tool=None, tool_input=None):
    data = {
        "session_id": "session-test",
        "cwd": str(repo),
        "hook_event_name": event,
    }
    if tool:
        data["tool_name"] = tool
        data["tool_input"] = tool_input or {}
    return data


def test_edit_is_denied_on_protected_branch_then_allowed(claude_repo):
    name, repo, env = claude_repo
    denied = run_hook(
        payload("PreToolUse", repo, tool="Edit", tool_input={"file_path": str(repo / "task.txt")}),
        cwd=repo,
        env=env,
    )
    result = json.loads(denied.stdout)
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    run_task(["task-branch", "--repo", name, "--name", "fix/claude-hook"], env=env)
    allowed = run_hook(
        payload("PreToolUse", repo, tool="Edit", tool_input={"file_path": str(repo / "task.txt")}),
        cwd=repo,
        env=env,
    )
    assert allowed.returncode == 0
    assert allowed.stdout == ""


def test_raw_commit_and_local_only_push_are_denied(claude_repo):
    _name, repo, env = claude_repo
    for command, expected in [
        ("git commit -m test", "task-commit"),
        ("git push origin HEAD", "LOCAL_ONLY"),
        ("git push --force origin HEAD", "force push"),
    ]:
        proc = run_hook(payload("PreToolUse", repo, tool="Bash", tool_input={"command": command}), cwd=repo, env=env)
        result = json.loads(proc.stdout)
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert expected.lower() in reason.lower()


def test_task_completed_blocks_commit_ready_work(claude_repo):
    name, repo, env = claude_repo
    run_task(["task-branch", "--repo", name, "--name", "fix/claude-hook"], env=env)
    (repo / "task.txt").write_text("changed\n", encoding="utf-8")
    run_task(
        [
            "task-gate",
            "--gate-id",
            "unit-proof",
            "--repo",
            name,
            "--scope",
            "task.txt",
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ],
        env=env,
    )
    run_task(["task-checkpoint", "--status", "READY_TO_CLOSE", "--next="], env=env)
    proc = run_hook(payload("TaskCompleted", repo), cwd=repo, env=env)
    assert proc.returncode == 2
    assert "commit-ready" in proc.stderr
    assert "task-commit" in proc.stderr


def test_session_start_injects_shared_task_context(claude_repo):
    _name, repo, env = claude_repo
    proc = run_hook(payload("SessionStart", repo), cwd=repo, env=env)
    result = json.loads(proc.stdout)
    context = result["hookSpecificOutput"]["additionalContext"]
    assert "AI-OS task claude-hook" in context
    assert "publication=LOCAL_ONLY" in context


def test_edit_denied_without_active_task(tmp_path):
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "empty-state")}
    proc = run_hook(
        payload("PreToolUse", ROOT, tool="Edit", tool_input={"file_path": str(ROOT / "CLAUDE.md")}),
        cwd=ROOT,
        env=env,
    )
    result = json.loads(proc.stdout)
    reason = result["hookSpecificOutput"]["permissionDecisionReason"]
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "no active" in reason.lower() or "task-start" in reason.lower()


def test_session_start_is_soft_when_no_task(tmp_path):
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "empty-state")}
    proc = run_hook(payload("SessionStart", ROOT), cwd=ROOT, env=env)
    assert proc.returncode == 0
    assert proc.stdout == ""
