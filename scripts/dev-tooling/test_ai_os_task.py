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
def task_repo(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "tracked.txt").write_text("".join(BASE_LINES), encoding="utf-8")
    (source / "task.txt").write_text("initial\n", encoding="utf-8")
    git(source, "add", "--", "tracked.txt", "task.txt")
    git(source, "commit", "-m", "init")

    name = f"tmp-ai-os-task-test-{tmp_path.name}"
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


def start_task(task_repo, *, adopt=None):
    name, _, env = task_repo
    args = [
        "task-start",
        "--task-id",
        "unit",
        "--title",
        "Unit test",
        "--class",
        "SMALL",
        "--repo",
        name,
        "--scope",
        f"{name}:.",
    ]
    for path in adopt or []:
        args.extend(["--adopt-baseline", f"{name}:{path}"])
    run_cmd(args, env=env)


def commit_task_file(task_repo, text="task change\n"):
    _, repo, _ = task_repo
    (repo / "task.txt").write_text(text, encoding="utf-8")
    git(repo, "add", "--", "task.txt")
    git(repo, "commit", "-m", "task commit")
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def set_lines(repo, replacements):
    lines = list(BASE_LINES)
    for index, value in replacements.items():
        lines[index - 1] = value + "\n"
    content = "".join(lines)
    (repo / "tracked.txt").write_text(content, encoding="utf-8")
    return content


def commit_only_tracked_content(repo, content):
    oid = git(repo, "hash-object", "-w", "--path=tracked.txt", "--stdin", input_text=content).stdout.strip()
    git(repo, "update-index", "--cacheinfo", "100644", oid, "tracked.txt")
    git(repo, "commit", "-m", "owned hunk")
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def close_result(task_repo, commit_sha):
    name, _, env = task_repo
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
    run_cmd(
        [
            "task-checkpoint",
            "--status",
            "READY_TO_CLOSE",
            "--next=",
            "--commit",
            f"{name}:{commit_sha}",
        ],
        env=env,
    )
    proc = run_cmd(["task-close", "--validate-only", "--json"], env=env, check=False)
    return proc, json.loads(proc.stdout)


def test_checkpoint_gate_dedupe_and_stale(task_repo):
    name, repo, env = task_repo
    start_task(task_repo)
    gate = [
        "task-gate",
        "--gate-id",
        "syntax",
        "--repo",
        name,
        "--scope",
        "tracked.txt",
        "--",
        sys.executable,
        "-c",
        "print('ok')",
    ]
    assert "PASS" in run_cmd(gate, env=env).stdout
    assert "DEDUPLICATED" in run_cmd(gate, env=env).stdout
    set_lines(repo, {1: "changed"})
    assert "RUN" in run_cmd(gate, env=env).stdout
    data = json.loads((Path(env["AI_OS_TASK_STATE_DIR"]) / "current-task.json").read_text(encoding="utf-8"))
    assert [entry["verdict"] for entry in data["gates"]] == ["PASS", "DEDUPLICATED", "PASS"]


def test_own_uncommitted_change_blocks_closure(task_repo):
    _, repo, _ = task_repo
    start_task(task_repo)
    sha = commit_task_file(task_repo)
    set_lines(repo, {1: "own residue"})
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 1
    assert any("own unstaged files remain" in issue for issue in result["issues"])


def test_preexisting_change_untouched_does_not_block(task_repo):
    _, repo, _ = task_repo
    set_lines(repo, {25: "foreign baseline"})
    start_task(task_repo)
    sha = commit_task_file(task_repo)
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 0, result
    assert result["verdict"] == "PASS"


def test_preexisting_and_committed_owned_hunk_in_same_file_passes(task_repo):
    _, repo, _ = task_repo
    set_lines(repo, {25: "foreign baseline"})
    start_task(task_repo)
    combined = set_lines(repo, {1: "owned commit", 25: "foreign baseline"})
    own_only = list(BASE_LINES)
    own_only[0] = "owned commit\n"
    sha = commit_only_tracked_content(repo, "".join(own_only))
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == combined
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 0, result
    assert result["verdict"] == "PASS"


def test_preexisting_and_uncommitted_owned_hunk_in_same_file_blocks(task_repo):
    _, repo, _ = task_repo
    set_lines(repo, {25: "foreign baseline"})
    start_task(task_repo)
    sha = commit_task_file(task_repo)
    set_lines(repo, {1: "own residue", 25: "foreign baseline"})
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 1
    assert any("tracked.txt" in issue for issue in result["issues"])


def test_preexisting_change_violation_is_detected(task_repo):
    _, repo, _ = task_repo
    set_lines(repo, {25: "foreign baseline"})
    start_task(task_repo)
    sha = commit_task_file(task_repo)
    set_lines(repo, {})
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 1
    assert any("OWNERSHIP_CONFLICT" in issue for issue in result["issues"])


def test_preexisting_change_cannot_be_absorbed_by_task_commit(task_repo):
    _, repo, _ = task_repo
    foreign = set_lines(repo, {25: "foreign baseline"})
    start_task(task_repo)
    sha = commit_only_tracked_content(repo, foreign)
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 1
    assert any("absorbed" in issue for issue in result["issues"])


def test_preexisting_untracked_file_untouched_does_not_block(task_repo):
    _, repo, _ = task_repo
    (repo / "foreign.tmp").write_text("foreign\n", encoding="utf-8")
    start_task(task_repo)
    sha = commit_task_file(task_repo)
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 0
    assert result["verdict"] == "PASS"


def test_new_owned_untracked_file_blocks(task_repo):
    _, repo, _ = task_repo
    start_task(task_repo)
    sha = commit_task_file(task_repo)
    (repo / "owned.tmp").write_text("owned\n", encoding="utf-8")
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 1
    assert any("own untracked files remain" in issue for issue in result["issues"])


def test_new_owned_change_after_owned_commit_blocks(task_repo):
    _, repo, _ = task_repo
    start_task(task_repo)
    committed = set_lines(repo, {1: "owned commit"})
    sha = commit_only_tracked_content(repo, committed)
    set_lines(repo, {1: "owned commit", 2: "post-commit residue"})
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 1
    assert any("own unstaged files remain" in issue for issue in result["issues"])


def test_explicitly_adopted_baseline_must_be_resolved(task_repo):
    _, repo, _ = task_repo
    (repo / "adopted.tmp").write_text("adopted\n", encoding="utf-8")
    start_task(task_repo, adopt=["adopted.tmp"])
    sha = commit_task_file(task_repo)
    proc, result = close_result(task_repo, sha)
    assert proc.returncode == 1
    assert any("own untracked files remain" in issue for issue in result["issues"])


def test_nonpristine_legacy_checkpoint_is_not_synthesized(task_repo):
    _, _, env = task_repo
    start_task(task_repo)
    checkpoint = Path(env["AI_OS_TASK_STATE_DIR"]) / "current-task.json"
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    data["schema_version"] = 1
    data["status"] = "ABORTED_WITH_EVIDENCE"
    data.pop("ownership_baseline")
    data.pop("adopted_baseline_scope")
    data.pop("ownership_conflicts")
    checkpoint.write_text(json.dumps(data), encoding="utf-8")
    proc = run_cmd(["task-status"], env=env, check=False)
    assert proc.returncode == 2
    assert "has no ownership baseline" in proc.stderr
    assert json.loads(checkpoint.read_text(encoding="utf-8"))["schema_version"] == 1
