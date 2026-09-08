"""P2: task-finalize - deterministic commit/close orchestration, no safety loss."""

from __future__ import annotations

import argparse
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plane_harness import child_env, plane_start_args, worktree_path  # noqa: E402


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


@pytest.fixture
def task_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "tracked.txt").write_text("line\n", encoding="utf-8")
    (source / "task.txt").write_text("initial\n", encoding="utf-8")
    git(source, "add", "--", "tracked.txt", "task.txt")
    git(source, "commit", "-m", "init")

    name = f"tmp-finalize-{tmp_path.name}"
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


def start_task(task_repo, scope: str | None = None):
    name, _, env = task_repo
    args = plane_start_args(
        task_id="unit",
        title="Unit test",
        repo=name,
        scope=scope or f"{name}:.",
    )
    run_cmd(args, env=env)
    return worktree_path(run_cmd, env, name, "unit")


def run_gate(task_repo, gate_id="G1", *, code="print('ok')", expect_fail=False):
    name, _, env = task_repo
    args = [
        "task-gate",
        "--task-id",
        "unit",
        "--gate-id",
        gate_id,
        "--repo",
        name,
        "--",
        sys.executable,
        "-c",
        code,
    ]
    return run_cmd(args, env=env, check=not expect_fail)


def finalize(task_repo, **extra):
    name, _, env = task_repo
    args = [
        "task-finalize",
        "--task-id",
        "unit",
        "--message",
        extra.pop("message", "test(harness): finalize unit"),
        "--summary",
        extra.pop("summary", "closed by finalize"),
    ]
    if extra:
        raise ValueError(f"unhandled finalize options {sorted(extra)}")
    return run_cmd(args, env=env, check=False)


def test_finalize_commits_refreshes_gate_and_closes(task_repo) -> None:
    name, _canonical, env = task_repo
    repo = start_task(task_repo)
    (repo / "task.txt").write_text("task change\n", encoding="utf-8")
    run_gate(task_repo)
    proc = finalize(task_repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "COMMITTED:" in proc.stdout
    assert "archived:" in proc.stdout
    # Commit exists and task archive moved the checkpoint.
    assert git(repo, "log", "-1", "--format=%s").stdout.strip() == "test(harness): finalize unit"
    state_root = Path(env["AI_OS_TASK_STATE_DIR"])
    archived = state_root / "tasks" / "archive" / "unit.json"
    assert archived.exists()
    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data["status"] == "CLOSED"
    assert data["commits"]
    # Post-commit gate entry is fresh (fingerprint matches current HEAD).
    gate = data["gates"][-1]
    assert gate["verdict"] in {"PASS", "DEDUPLICATED"}


def test_finalize_refuses_when_gate_failed(task_repo) -> None:
    name, _canonical, _ = task_repo
    repo = start_task(task_repo)
    run_gate(task_repo, code="import sys; sys.exit(1)", expect_fail=True)
    (repo / "task.txt").write_text("task change\n", encoding="utf-8")
    proc = finalize(task_repo)
    assert proc.returncode != 0
    assert "commit plan not ready" in proc.stdout + proc.stderr
    # Nothing committed.
    head = git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert head != "test(harness): finalize unit"


def test_finalize_refuses_when_next_action_pending(task_repo) -> None:
    name, _, env = task_repo
    run_cmd(
        [
            *plane_start_args(
                task_id="unit",
                title="Unit test",
                repo=name,
                scope=f"{name}:.",
                extra=["--next", "still working"],
            ),
        ],
        env=env,
    )
    proc = finalize(task_repo)
    assert proc.returncode != 0
    assert "next_action" in proc.stdout + proc.stderr


def test_finalize_preserves_foreign_dirty_paths(task_repo) -> None:
    name, canonical, _ = task_repo
    repo = start_task(task_repo, scope=f"{name}:task.txt")
    (repo / "task.txt").write_text("task change\n", encoding="utf-8")
    (canonical / "tracked.txt").write_text("foreign change\n", encoding="utf-8")
    run_gate(task_repo)
    proc = finalize(task_repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    # Owned path committed; foreign path still dirty and not committed.
    committed = git(repo, "show", "--name-only", "--format=", "HEAD").stdout.strip()
    assert "task.txt" in committed
    assert "tracked.txt" not in committed
    status = git(canonical, "status", "--porcelain").stdout
    assert " M tracked.txt" in status
    assert (canonical / "tracked.txt").read_text(encoding="utf-8") == "foreign change\n"


def test_failed_close_validation_does_not_revert_newer_checkpoint(task_repo, monkeypatch) -> None:
    name, _repo, env = task_repo
    run_cmd(
        plane_start_args(
            task_id="unit",
            title="Unit test",
            repo=name,
            scope=f"{name}:.",
        ),
        env=env,
    )

    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    os.environ["AI_OS_TASK_STATE_DIR"] = env["AI_OS_TASK_STATE_DIR"]

    import ai_os_task_lifecycle as lifecycle_mod
    from ai_os_task_state import load_checkpoint

    injected = {"done": False}

    def stale_issues(data):
        if not injected["done"]:
            injected["done"] = True
            lifecycle_mod.update_checkpoint(
                argparse.Namespace(
                    task_id="unit",
                    status="READY_TO_CLOSE",
                    phase="ready-to-close",
                    next_action="",
                    summary="newer checkpoint",
                    publication_mode=None,
                    decision=[],
                    step=[],
                    blocker=[],
                    resolve_blocker=[],
                    commit=[],
                )
            )
        return [f"status must be READY_TO_CLOSE, got {data['status']}"]

    monkeypatch.setattr(lifecycle_mod, "closure_issues", stale_issues)
    result = lifecycle_mod.close_task(
        argparse.Namespace(
            task_id="unit",
            validate_only=True,
            json=True,
            summary="",
            summary_file=None,
        )
    )

    assert result == 1
    latest = load_checkpoint("unit")
    assert latest["status"] == "READY_TO_CLOSE"
    assert latest["current_phase"] == "ready-to-close"
