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


def run_cmd(args, *, env=None, check=True):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        env=merged,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc


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
def task_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (source / "beta.txt").write_text("beta\n", encoding="utf-8")
    git(source, "add", ".")
    git(source, "commit", "-m", "init")

    repo_name = f"tmp-ai-os-scope-update-{tmp_path.name}"
    repo = ROOT / repo_name
    if repo.exists():
        remove_tree(repo)
    git(ROOT, "clone", str(source), str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test User")
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "state")}
    try:
        yield repo_name, repo, env
    finally:
        if repo.exists():
            remove_tree(repo)


def active_checkpoint(state_dir: str, task_id: str = "unit") -> Path:
    return Path(state_dir) / "tasks" / "active" / f"{task_id}.json"


def start_task(repo_name: str, env: dict[str, str], *, next_action: str = ""):
    args = [
        "task-start",
        "--task-id",
        "unit",
        "--title",
        "Unit",
        "--class",
        "SMALL",
        "--repo",
        repo_name,
        "--scope",
        f"{repo_name}:alpha.txt",
    ]
    if next_action:
        args.extend(["--next", next_action])
    run_cmd(args, env=env)


def load_checkpoint(env: dict[str, str]) -> dict:
    return json.loads(active_checkpoint(env["AI_OS_TASK_STATE_DIR"]).read_text(encoding="utf-8"))


def test_scope_add_rejects_dirty_scope_unless_adopted(task_repo):
    repo_name, repo, env = task_repo
    start_task(repo_name, env)
    (repo / "beta.txt").write_text("dirty\n", encoding="utf-8")

    rejected = run_cmd(
        ["task-scope-add", "--scope", f"{repo_name}:beta.txt"],
        env=env,
        check=False,
    )
    assert rejected.returncode == 2
    assert "pre-existing dirty paths" in rejected.stderr

    run_cmd(
        [
            "task-scope-add",
            "--scope",
            f"{repo_name}:beta.txt",
            "--adopt-existing",
            "--reason",
            "unit adoption",
        ],
        env=env,
    )
    data = load_checkpoint(env)
    assert {"repo": repo_name, "path": "beta.txt"} in data["declared_write_scope"]
    assert {"repo": repo_name, "path": "beta.txt"} in data["adopted_baseline_scope"]
    assert f"{repo_name}:beta.txt" in data["own_unstaged_files"]


def test_adopt_path_requires_existing_declared_scope(task_repo):
    repo_name, _repo, env = task_repo
    start_task(repo_name, env)

    proc = run_cmd(
        ["task-adopt-path", "--path", f"{repo_name}:beta.txt"],
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "adopted baseline path must be inside declared scope" in proc.stderr


def test_next_clear_has_explicit_command(task_repo):
    repo_name, _repo, env = task_repo
    start_task(repo_name, env, next_action="manual JSON should not be needed")

    run_cmd(["task-next-clear"], env=env)
    assert load_checkpoint(env)["next_action"] == ""
