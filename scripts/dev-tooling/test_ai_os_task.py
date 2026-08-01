import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ai_os_task.py"


def run_cmd(args, cwd=ROOT, env=None, check=True):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
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


def remove_tree(path: Path):
    def onexc(func, item, exc):
        try:
            os.chmod(item, stat.S_IWRITE)
            func(item)
        except Exception:
            raise exc

    shutil.rmtree(path, onexc=onexc)


def test_checkpoint_gate_dedupe_and_stale(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    workspace_repo = ROOT / "tmp-ai-os-task-test-repo"
    if workspace_repo.exists():
        remove_tree(workspace_repo)
    try:
        subprocess.run(["git", "clone", str(repo), str(workspace_repo)], cwd=ROOT, check=True, capture_output=True)
        env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "state")}
        run_cmd(
            [
                "task-start",
                "--task-id",
                "unit",
                "--title",
                "Unit test",
                "--class",
                "SMALL",
                "--repo",
                "tmp-ai-os-task-test-repo",
                "--scope",
                "tmp-ai-os-task-test-repo:tracked.txt",
            ],
            env=env,
        )
        gate = [
            "task-gate",
            "--gate-id",
            "syntax",
            "--repo",
            "tmp-ai-os-task-test-repo",
            "--scope",
            "tracked.txt",
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ]
        first = run_cmd(gate, env=env)
        assert "PASS" in first.stdout
        second = run_cmd(gate, env=env)
        assert "DEDUPLICATED" in second.stdout
        (workspace_repo / "tracked.txt").write_text("two\n", encoding="utf-8")
        third = run_cmd(gate, env=env)
        assert "RUN" in third.stdout
        data = json.loads((tmp_path / "state" / "current-task.json").read_text(encoding="utf-8"))
        assert [gate["verdict"] for gate in data["gates"]] == ["PASS", "DEDUPLICATED", "PASS"]
    finally:
        if workspace_repo.exists():
            remove_tree(workspace_repo)
