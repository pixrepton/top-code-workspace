import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ai_os_task.py"
BASE_LINES = [f"line {number}\n" for number in range(1, 31)]


def run_cmd(args, *, cwd=ROOT, env=None, check=True):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=merged,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc


def git(repo, *args, check=True, input_text=None):
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), text=True, input=input_text, capture_output=True
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
def git_control_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "tracked.txt").write_text("".join(BASE_LINES), encoding="utf-8")
    (source / "task.txt").write_text("initial\n", encoding="utf-8")
    git(source, "add", "--", "tracked.txt", "task.txt")
    git(source, "commit", "-m", "init")

    name = f"tmp-ai-os-git-control-{tmp_path.name}"
    repo = ROOT / name
    if repo.exists():
        remove_tree(repo)
    git(ROOT, "clone", str(source), str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test User")
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "state")}
    try:
        yield name, repo, env
    finally:
        if repo.exists():
            remove_tree(repo)


def active_checkpoint(state_dir: str, task_id: str) -> Path:
    return Path(state_dir) / "tasks" / "active" / f"{task_id}.json"


def start(git_control_repo):
    name, _repo, env = git_control_repo
    run_cmd(
        [
            "task-start",
            "--task-id",
            "git-control",
            "--title",
            "Git control test",
            "--class",
            "SMALL",
            "--repo",
            name,
            "--scope",
            f"{name}:.",
        ],
        env=env,
    )


def branch(git_control_repo):
    name, _repo, env = git_control_repo
    run_cmd(["task-branch", "--repo", name, "--name", "fix/git-control"], env=env)


def gate(git_control_repo):
    name, _repo, env = git_control_repo
    run_cmd(
        [
            "task-gate",
            "--gate-id",
            "unit-proof",
            "--repo",
            name,
            "--scope",
            ".",
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ],
        env=env,
    )


def commit(git_control_repo, message="fix(test): create scoped local commit"):
    name, _repo, env = git_control_repo
    proc = run_cmd(
        ["task-commit", "--repo", name, "--message", message, "--json"], env=env
    )
    return json.loads(proc.stdout)


def test_plan_blocks_protected_branch(git_control_repo):
    name, repo, env = git_control_repo
    start(git_control_repo)
    (repo / "task.txt").write_text("changed\n", encoding="utf-8")
    gate(git_control_repo)
    proc = run_cmd(["task-commit-plan", "--repo", name, "--json"], env=env, check=False)
    result = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert result["verdict"] == "BLOCKED"
    assert any("protected/default" in reason for reason in result["reasons"])


def test_scoped_commit_is_created_and_recorded(git_control_repo):
    name, repo, env = git_control_repo
    start(git_control_repo)
    branch(git_control_repo)
    (repo / "task.txt").write_text("changed\n", encoding="utf-8")
    gate(git_control_repo)
    result = commit(git_control_repo)
    assert result["verdict"] == "COMMITTED"
    assert result["paths"] == ["task.txt"]
    assert git(repo, "status", "--short").stdout == ""
    checkpoint = json.loads(active_checkpoint(env["AI_OS_TASK_STATE_DIR"], "git-control").read_text())
    assert f"{name}:{result['sha']}" in checkpoint["commits"]
    assert checkpoint["publication_mode"] == "LOCAL_ONLY"


def test_foreign_staged_file_is_not_absorbed(git_control_repo):
    name, repo, _env = git_control_repo
    (repo / "tracked.txt").write_text("foreign\n" + "".join(BASE_LINES[1:]), encoding="utf-8")
    git(repo, "add", "--", "tracked.txt")
    start(git_control_repo)
    branch(git_control_repo)
    (repo / "task.txt").write_text("owned\n", encoding="utf-8")
    gate(git_control_repo)
    result = commit(git_control_repo)
    assert result["paths"] == ["task.txt"]
    assert git(repo, "diff", "--cached", "--name-only").stdout.strip() == "tracked.txt"
    assert git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.strip() == "task.txt"


def test_foreign_staged_hunk_in_same_file_is_preserved(git_control_repo):
    _name, repo, _env = git_control_repo
    lines = list(BASE_LINES)
    lines[24] = "foreign 25\n"
    (repo / "tracked.txt").write_text("".join(lines), encoding="utf-8")
    git(repo, "add", "--", "tracked.txt")
    start(git_control_repo)
    branch(git_control_repo)
    lines[0] = "owned 1\n"
    (repo / "tracked.txt").write_text("".join(lines), encoding="utf-8")
    gate(git_control_repo)
    result = commit(git_control_repo, "fix(test): preserve same-file foreign hunk")
    assert result["paths"] == ["tracked.txt"]
    committed = git(repo, "show", "HEAD:tracked.txt").stdout.splitlines()
    staged = git(repo, "show", ":tracked.txt").stdout.splitlines()
    worktree = (repo / "tracked.txt").read_text(encoding="utf-8").splitlines()
    assert committed[0] == "owned 1"
    assert committed[24] == "line 25"
    assert staged[0] == "owned 1"
    assert staged[24] == "foreign 25"
    assert worktree == staged
    assert git(repo, "status", "--short").stdout.strip() == "M  tracked.txt"


def test_secret_pattern_blocks_commit(git_control_repo):
    name, repo, env = git_control_repo
    start(git_control_repo)
    branch(git_control_repo)
    (repo / "task.txt").write_text("token=ghp_abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    gate(git_control_repo)
    proc = run_cmd(["task-commit-plan", "--repo", name, "--json"], env=env, check=False)
    result = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert result["verdict"] == "BLOCKED"
    assert any("GitHub token" in reason for reason in result["reasons"])


def test_write_guard_requires_scope_and_task_branch(git_control_repo):
    name, repo, env = git_control_repo
    start(git_control_repo)
    proc = run_cmd(["task-guard-write", "--path", str(repo / "task.txt")], env=env, check=False)
    assert proc.returncode == 2
    assert "protected/default" in proc.stderr
    branch(git_control_repo)
    allowed = run_cmd(["task-guard-write", "--path", str(repo / "task.txt")], env=env)
    assert json.loads(allowed.stdout)["ok"] is True
    outside = run_cmd(["task-guard-write", "--path", str(ROOT / "AGENTS.md")], env=env, check=False)
    assert outside.returncode == 2
    assert "outside checkpoint target" in outside.stderr
