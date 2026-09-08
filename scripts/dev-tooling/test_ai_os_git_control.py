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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plane_harness import child_env, parse_json_stdout, plane_start_args, worktree_path  # noqa: E402


def run_cmd(args, *, cwd=ROOT, env=None, check=True):
    merged = child_env(env)
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
    name, _canonical, env = git_control_repo
    run_cmd(
        plane_start_args(
            task_id="git-control",
            title="Git control test",
            repo=name,
            scope=f"{name}:.",
        ),
        env=env,
    )
    env["AI_OS_TASK_ID"] = "git-control"
    return worktree_path(run_cmd, env, name, "git-control")


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
    return parse_json_stdout(proc.stdout)


def test_plan_blocks_canonical_protected_checkout(git_control_repo):
    name, canonical, env = git_control_repo
    start(git_control_repo)
    proc = run_cmd(
        ["task-guard-write", "--path", str(canonical / "task.txt")],
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "outside checkpoint target" in proc.stderr
    worktree = worktree_path(run_cmd, env, name, "git-control")
    allowed = run_cmd(["task-guard-write", "--path", str(worktree / "task.txt")], env=env)
    assert parse_json_stdout(allowed.stdout)["ok"] is True


def test_scoped_commit_is_created_and_recorded(git_control_repo):
    name, _canonical, env = git_control_repo
    repo = start(git_control_repo)
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
    name, canonical, env = git_control_repo
    (canonical / "tracked.txt").write_text("foreign\n" + "".join(BASE_LINES[1:]), encoding="utf-8")
    git(canonical, "add", "--", "tracked.txt")
    repo = start(git_control_repo)
    (repo / "task.txt").write_text("owned\n", encoding="utf-8")
    gate(git_control_repo)
    result = commit(git_control_repo)
    assert result["paths"] == ["task.txt"]
    assert git(canonical, "diff", "--cached", "--name-only").stdout.strip() == "tracked.txt"
    assert git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").stdout.strip() == "task.txt"


def test_foreign_staged_hunk_in_same_file_is_blocked(git_control_repo):
    name, _canonical, env = git_control_repo
    repo = start(git_control_repo)
    lines = list(BASE_LINES)
    lines[24] = "foreign 25\n"
    (repo / "tracked.txt").write_text("".join(lines), encoding="utf-8")
    git(repo, "add", "--", "tracked.txt")
    lines[0] = "owned 1\n"
    (repo / "tracked.txt").write_text("".join(lines), encoding="utf-8")
    gate(git_control_repo)
    proc = run_cmd(
        ["task-commit", "--repo", name, "--message", "fix(test): mixed index and worktree", "--json"],
        env=env,
        check=False,
    )
    result = parse_json_stdout(proc.stdout)
    assert result["verdict"] == "BLOCKED"
    assert any("index differs from worktree" in reason for reason in result["reasons"])


def test_secret_pattern_blocks_commit(git_control_repo):
    name, _canonical, env = git_control_repo
    repo = start(git_control_repo)
    fake_token = "ghp_" + "a" * 30
    (repo / "task.txt").write_text(f"token={fake_token}\n", encoding="utf-8")
    gate(git_control_repo)
    proc = run_cmd(["task-commit-plan", "--repo", name, "--json"], env=env, check=False)
    result = parse_json_stdout(proc.stdout)
    assert proc.returncode == 1
    assert result["verdict"] == "BLOCKED"
    assert any("GitHub token" in reason for reason in result["reasons"])


def test_env_example_suffix_is_allowed_but_real_env_is_blocked(git_control_repo):
    name, _canonical, env = git_control_repo
    repo = start(git_control_repo)

    example_path = repo / ".env.local-vps.example"
    example_path.write_text("DEEPSEEK_API_KEY=<set in local env>\n", encoding="utf-8")
    run_cmd(["task-checkpoint", "--status", "IN_PROGRESS"], env=env)
    gate(git_control_repo)
    proc = run_cmd(["task-commit-plan", "--repo", name, "--json"], env=env)
    assert parse_json_stdout(proc.stdout)["verdict"] == "COMMIT_READY"

    real_env_path = repo / ".env.local-vps"
    real_env_path.write_text("DEEPSEEK_API_KEY=<set in local env>\n", encoding="utf-8")
    proc = run_cmd(["task-commit-plan", "--repo", name, "--json"], env=env, check=False)
    result = parse_json_stdout(proc.stdout)
    assert proc.returncode == 1
    assert result["verdict"] == "BLOCKED"
    assert any("sensitive path: .env.local-vps" in reason for reason in result["reasons"])


def test_write_guard_allows_worktree_and_rejects_canonical(git_control_repo):
    name, canonical, env = git_control_repo
    worktree = start(git_control_repo)
    denied = run_cmd(["task-guard-write", "--path", str(canonical / "task.txt")], env=env, check=False)
    assert denied.returncode == 2
    assert "outside checkpoint target" in denied.stderr
    allowed = run_cmd(["task-guard-write", "--path", str(worktree / "task.txt")], env=env)
    assert parse_json_stdout(allowed.stdout)["ok"] is True
    outside = run_cmd(["task-guard-write", "--path", str(ROOT / "AGENTS.md")], env=env, check=False)
    assert outside.returncode == 2
    assert "outside checkpoint target" in outside.stderr
