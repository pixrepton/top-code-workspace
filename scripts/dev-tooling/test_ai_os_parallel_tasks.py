import json
import os
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ai_os_task.py"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plane_harness import child_env, parse_json_stdout, plane_start_args, worktree_path  # noqa: E402

from ai_os_task import (
    normalize_scope_path,
    scope_entries_overlap,
    scopes_conflict,
)


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


def active_checkpoint(state_dir: str, task_id: str) -> Path:
    return Path(state_dir) / "tasks" / "active" / f"{task_id}.json"


def archive_checkpoint(state_dir: str, task_id: str) -> Path:
    return Path(state_dir) / "tasks" / "archive" / f"{task_id}.json"


def clone_repo(tmp_path, suffix: str):
    source = tmp_path / f"source-{suffix}"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "alpha.txt").write_text("alpha\n", encoding="utf-8")
    (source / "beta.txt").write_text("beta\n", encoding="utf-8")
    (source / "tools").mkdir()
    (source / "tools" / "gmail_audit").mkdir(parents=True)
    (source / "tools" / "gmail_audit" / "runtime.py").write_text("runtime\n", encoding="utf-8")
    git(source, "add", ".")
    git(source, "commit", "-m", "init")

    name = f"tmp-ai-os-parallel-{suffix}-{tmp_path.name}"
    repo = ROOT / name
    if repo.exists():
        remove_tree(repo)
    git(ROOT, "clone", str(source), str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test User")
    return name, repo


@pytest.fixture
def dual_repo_env(tmp_path):
    name_a, repo_a = clone_repo(tmp_path, "a")
    name_b, repo_b = clone_repo(tmp_path, "b")
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "state")}
    try:
        yield {
            "env": env,
            "name_a": name_a,
            "repo_a": repo_a,
            "name_b": name_b,
            "repo_b": repo_b,
        }
    finally:
        for repo in (repo_a, repo_b):
            if repo.exists():
                remove_tree(repo)


def start_task(env, task_id, repo_name, scope_path, *, check=True):
    return run_cmd(
        plane_start_args(
            task_id=task_id,
            title=task_id,
            repo=repo_name,
            scope=f"{repo_name}:{scope_path}",
        ),
        env=env,
        check=check,
    )


def test_scope_normalization_and_overlap_rules():
    assert normalize_scope_path(".") == "*"
    assert normalize_scope_path("tools\\gmail_audit") == "tools/gmail_audit"
    assert normalize_scope_path("tools/gmail_audit/../gmail_audit/runtime.py") == "tools/gmail_audit/runtime.py"

    parent = {"repo": "gmail-agent", "path": "tools/gmail_audit"}
    child = {"repo": "gmail-agent", "path": "tools/gmail_audit/runtime.py"}
    sibling_a = {"repo": "gmail-agent", "path": "alpha.txt"}
    sibling_b = {"repo": "gmail-agent", "path": "beta.txt"}
    other_repo = {"repo": "daszek", "path": "tools/gmail_audit/runtime.py"}

    assert scope_entries_overlap(parent, child)
    assert scope_entries_overlap(child, parent)
    assert not scope_entries_overlap(sibling_a, sibling_b)
    assert not scope_entries_overlap(parent, other_repo)
    assert scopes_conflict([parent], [child])


def test_parallel_tasks_in_different_repos(dual_repo_env):
    env = dual_repo_env["env"]
    start_task(env, "task-a", dual_repo_env["name_a"], ".")
    start_task(env, "task-b", dual_repo_env["name_b"], ".")
    listed = parse_json_stdout(run_cmd(["task-list", "--json"], env=env).stdout)
    assert set(listed["active"]) == {"task-a", "task-b"}


def test_parallel_disjoint_scopes_in_same_repo(dual_repo_env):
    env = dual_repo_env["env"]
    repo = dual_repo_env["name_a"]
    start_task(env, "task-a", repo, "alpha.txt")
    start_task(env, "task-b", repo, "beta.txt")
    listed = parse_json_stdout(run_cmd(["task-list", "--json"], env=env).stdout)
    assert set(listed["active"]) == {"task-a", "task-b"}


def test_parent_child_scope_conflict(dual_repo_env):
    env = dual_repo_env["env"]
    repo = dual_repo_env["name_a"]
    start_task(env, "task-parent", repo, "tools/gmail_audit")
    proc = start_task(env, "task-child", repo, "tools/gmail_audit/runtime.py", check=False)
    assert proc.returncode == 2
    assert "scope conflict" in proc.stderr


def test_identical_scope_conflict(dual_repo_env):
    env = dual_repo_env["env"]
    repo = dual_repo_env["name_a"]
    start_task(env, "task-a", repo, "alpha.txt")
    proc = start_task(env, "task-b", repo, "alpha.txt", check=False)
    assert proc.returncode == 2
    assert "scope conflict" in proc.stderr


def test_concurrent_task_start_respects_registry_lock(dual_repo_env):
    env = dual_repo_env["env"]
    repo = dual_repo_env["name_a"]
    barrier = threading.Barrier(2)
    results: list[subprocess.CompletedProcess[str]] = []

    def worker(task_id: str, scope: str):
        barrier.wait()
        proc = run_cmd(
            plane_start_args(
                task_id=task_id,
                title=task_id,
                repo=repo,
                scope=f"{repo}:{scope}",
            ),
            env=env,
            check=False,
        )
        results.append(proc)

    threads = [
        threading.Thread(target=worker, args=("task-a", "alpha.txt")),
        threading.Thread(target=worker, args=("task-b", "beta.txt")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    assert sum(proc.returncode == 0 for proc in results) == 2
    listed = parse_json_stdout(run_cmd(["task-list", "--json"], env=env).stdout)
    assert set(listed["active"]) == {"task-a", "task-b"}


def test_failed_close_does_not_release_active_task(dual_repo_env):
    env = dual_repo_env["env"]
    repo_name = dual_repo_env["name_a"]
    start_task(env, "task-fail", repo_name, ".")
    proc = run_cmd(["task-close", "--task-id", "task-fail", "--validate-only", "--json"], env=env, check=False)
    result = parse_json_stdout(proc.stdout)
    assert proc.returncode == 1
    assert result["verdict"] == "FAIL"
    assert active_checkpoint(env["AI_OS_TASK_STATE_DIR"], "task-fail").exists()
    assert not archive_checkpoint(env["AI_OS_TASK_STATE_DIR"], "task-fail").exists()


def test_successful_close_archives_and_releases(dual_repo_env):
    env = dual_repo_env["env"]
    repo_name = dual_repo_env["name_a"]
    start_task(env, "task-close", repo_name, "alpha.txt")
    repo = worktree_path(run_cmd, env, repo_name, "task-close")
    (repo / "alpha.txt").write_text("changed\n", encoding="utf-8")
    run_cmd(
        [
            "task-gate",
            "--task-id",
            "task-close",
            "--gate-id",
            "proof",
            "--repo",
            repo_name,
            "--scope",
            "alpha.txt",
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ],
        env=env,
    )
    commit = parse_json_stdout(
        run_cmd(
            ["task-commit", "--task-id", "task-close", "--repo", repo_name, "--message", "fix(test): close", "--json"],
            env=env,
        ).stdout
    )
    run_cmd(
        [
            "task-checkpoint",
            "--task-id",
            "task-close",
            "--status",
            "READY_TO_CLOSE",
            "--next=",
            "--commit",
            f"{repo_name}:{commit['sha']}",
        ],
        env=env,
    )
    proc = run_cmd(["task-close", "--task-id", "task-close", "--json"], env=env)
    result = parse_json_stdout(proc.stdout)
    assert result["verdict"] == "PASS"
    assert not active_checkpoint(env["AI_OS_TASK_STATE_DIR"], "task-close").exists()
    archived = json.loads(archive_checkpoint(env["AI_OS_TASK_STATE_DIR"], "task-close").read_text(encoding="utf-8"))
    assert archived["status"] == "CLOSED"
    assert archived["commits"]


def test_legacy_current_task_json_is_migrated(dual_repo_env):
    env = dual_repo_env["env"]
    state = Path(env["AI_OS_TASK_STATE_DIR"])
    start_task(env, "seed", dual_repo_env["name_a"], ".")
    seed = json.loads(active_checkpoint(env["AI_OS_TASK_STATE_DIR"], "seed").read_text(encoding="utf-8"))
    seed["task_id"] = "legacy-task"
    seed["status"] = "IN_PROGRESS"
    run_cmd(["task-cleanup", "--task-id", "seed"], env=env)
    (state / "current-task.json").write_text(json.dumps(seed), encoding="utf-8")

    run_cmd(["task-status", "--task-id", "legacy-task", "--json"], env=env)
    assert active_checkpoint(env["AI_OS_TASK_STATE_DIR"], "legacy-task").exists()
    assert not (state / "current-task.json").exists()


def test_modifying_commands_require_task_id_when_multiple_active(dual_repo_env):
    env = dual_repo_env["env"]
    start_task(env, "task-a", dual_repo_env["name_a"], "alpha.txt")
    start_task(env, "task-b", dual_repo_env["name_a"], "beta.txt")
    proc = run_cmd(["task-status", "--json"], env=env, check=False)
    assert proc.returncode == 2
    assert "multiple active tasks" in proc.stderr


def test_task_commit_respects_task_id_and_foreign_scope(dual_repo_env):
    env = dual_repo_env["env"]
    repo_name = dual_repo_env["name_a"]
    repo = dual_repo_env["repo_a"]
    start_task(env, "task-a", repo_name, "alpha.txt")
    start_task(env, "task-b", repo_name, "beta.txt")
    wt_a = worktree_path(run_cmd, env, repo_name, "task-a")
    wt_b = worktree_path(run_cmd, env, repo_name, "task-b")
    (wt_a / "alpha.txt").write_text("a\n", encoding="utf-8")
    (wt_b / "beta.txt").write_text("b\n", encoding="utf-8")
    for task_id, scope in (("task-a", "alpha.txt"), ("task-b", "beta.txt")):
        run_cmd(
            [
                "task-gate",
                "--task-id",
                task_id,
                "--gate-id",
                f"gate-{task_id}",
                "--repo",
                repo_name,
                "--scope",
                scope,
                "--",
                sys.executable,
                "-c",
                "print('ok')",
            ],
            env=env,
        )
    commit_a = parse_json_stdout(
        run_cmd(
            ["task-commit", "--task-id", "task-a", "--repo", repo_name, "--message", "fix(a): alpha", "--json"],
            env=env,
        ).stdout
    )
    assert commit_a["paths"] == ["alpha.txt"]
    run_cmd(
        [
            "task-gate",
            "--task-id",
            "task-b",
            "--gate-id",
            "gate-task-b",
            "--repo",
            repo_name,
            "--scope",
            "beta.txt",
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ],
        env=env,
    )
    plan_b = parse_json_stdout(
        run_cmd(["task-commit-plan", "--task-id", "task-b", "--repo", repo_name, "--json"], env=env).stdout
    )
    assert plan_b["owned_paths"] == ["beta.txt"]
    assert "alpha.txt" not in plan_b["owned_paths"]
