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
    args = plane_start_args(
        task_id="unit",
        title="Unit test",
        repo=name,
        scope=f"{name}:.",
    )
    for path in adopt or []:
        args.extend(["--adopt-baseline", f"{name}:{path}"])
    run_cmd(args, env=env)
    worktree = worktree_path(run_cmd, env, name, "unit")
    return name, worktree, env


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
            "task-gate",
            "--gate-id",
            "FINAL_HEAD_GATE",
            "--repo",
            name,
            "--final-head",
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
    return proc, parse_json_stdout(proc.stdout)


def test_checkpoint_gate_dedupe_and_stale(task_repo):
    name, repo, env = start_task(task_repo)
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
    data = json.loads(active_checkpoint(env["AI_OS_TASK_STATE_DIR"], "unit").read_text(encoding="utf-8"))
    assert [entry["verdict"] for entry in data["gates"]] == ["PASS", "DEDUPLICATED", "PASS"]


def test_own_uncommitted_change_blocks_closure(task_repo):
    started = start_task(task_repo)
    _, repo, _ = started
    sha = commit_task_file(started)
    set_lines(repo, {1: "own residue"})
    proc, result = close_result(started, sha)
    assert proc.returncode == 1
    assert any("own unstaged files remain" in issue for issue in result["issues"])


def test_preexisting_change_untouched_does_not_block(task_repo):
    _, canonical, _ = task_repo
    set_lines(canonical, {25: "foreign baseline"})
    started = start_task(task_repo)
    sha = commit_task_file(started)
    proc, result = close_result(started, sha)
    assert proc.returncode == 0, result
    assert result["verdict"] == "PASS"


def test_partial_index_commit_leaves_owned_unstaged_residue(task_repo):
    started = start_task(task_repo)
    _, repo, _ = started
    combined = set_lines(repo, {1: "owned commit", 25: "foreign baseline"})
    own_only = list(BASE_LINES)
    own_only[0] = "owned commit\n"
    sha = commit_only_tracked_content(repo, "".join(own_only))
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == combined
    proc, result = close_result(started, sha)
    assert proc.returncode == 1
    assert any("tracked.txt" in issue for issue in result["issues"])


def test_preexisting_and_uncommitted_owned_hunk_in_same_file_blocks(task_repo):
    started = start_task(task_repo)
    _, repo, _ = started
    sha = commit_task_file(started)
    set_lines(repo, {1: "own residue", 25: "foreign baseline"})
    proc, result = close_result(started, sha)
    assert proc.returncode == 1
    assert any("tracked.txt" in issue for issue in result["issues"])


def test_canonical_preexisting_is_isolated_from_worktree_close(task_repo):
    _, canonical, _ = task_repo
    set_lines(canonical, {25: "foreign baseline"})
    started = start_task(task_repo)
    sha = commit_task_file(started)
    set_lines(canonical, {})
    proc, result = close_result(started, sha)
    assert proc.returncode == 0, result
    assert result["verdict"] == "PASS"


def test_canonical_preexisting_cannot_be_absorbed_into_worktree_commit(task_repo):
    _, canonical, _ = task_repo
    set_lines(canonical, {25: "foreign baseline"})
    started = start_task(task_repo)
    sha = commit_task_file(started)
    _, worktree, _ = started
    assert "foreign baseline" not in (worktree / "tracked.txt").read_text(encoding="utf-8")
    assert "foreign baseline" in (canonical / "tracked.txt").read_text(encoding="utf-8")
    proc, result = close_result(started, sha)
    assert proc.returncode == 0, result
    assert result["verdict"] == "PASS"


def test_preexisting_untracked_file_untouched_does_not_block(task_repo):
    _, canonical, _ = task_repo
    (canonical / "foreign.tmp").write_text("foreign\n", encoding="utf-8")
    started = start_task(task_repo)
    sha = commit_task_file(started)
    proc, result = close_result(started, sha)
    assert proc.returncode == 0
    assert result["verdict"] == "PASS"


def test_new_owned_untracked_file_blocks(task_repo):
    started = start_task(task_repo)
    _, repo, _ = started
    sha = commit_task_file(started)
    (repo / "owned.tmp").write_text("owned\n", encoding="utf-8")
    proc, result = close_result(started, sha)
    assert proc.returncode == 1
    assert any("own untracked files remain" in issue for issue in result["issues"])


def test_new_owned_change_after_owned_commit_blocks(task_repo):
    started = start_task(task_repo)
    _, repo, _ = started
    committed = set_lines(repo, {1: "owned commit"})
    sha = commit_only_tracked_content(repo, committed)
    set_lines(repo, {1: "owned commit", 2: "post-commit residue"})
    proc, result = close_result(started, sha)
    assert proc.returncode == 1
    assert any("own unstaged files remain" in issue for issue in result["issues"])


def test_canonical_untracked_is_not_imported_into_worktree(task_repo):
    _, canonical, _ = task_repo
    (canonical / "adopted.tmp").write_text("adopted\n", encoding="utf-8")
    started = start_task(task_repo, adopt=["adopted.tmp"])
    sha = commit_task_file(started)
    _, worktree, _ = started
    assert not (worktree / "adopted.tmp").exists()
    proc, result = close_result(started, sha)
    assert proc.returncode == 0, result
    assert result["verdict"] == "PASS"


def active_checkpoint(state_dir: str, task_id: str) -> Path:
    return Path(state_dir) / "tasks" / "active" / f"{task_id}.json"


def test_nonpristine_legacy_checkpoint_is_not_synthesized(task_repo):
    _, _, env = task_repo
    start_task(task_repo)
    checkpoint = active_checkpoint(env["AI_OS_TASK_STATE_DIR"], "unit")
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


def test_stale_commit_evaluation_does_not_resurrect_cleared_next_action(task_repo):
    name, _repo, env = task_repo
    start_task(task_repo)
    run_cmd(["task-checkpoint", "--next", "stale-next"], env=env)
    run_cmd(["task-next-clear"], env=env)

    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    os.environ["AI_OS_TASK_STATE_DIR"] = env["AI_OS_TASK_STATE_DIR"]
    from ai_os_task_commit import _record_commit_evaluation
    from ai_os_task_state import load_checkpoint

    stale = load_checkpoint("unit")
    stale["next_action"] = "stale-next"
    stale["current_phase"] = "task-start"
    _record_commit_evaluation(
        stale,
        {
            "task_id": "unit",
            "repo": name,
            "branch": "branch",
            "publication_mode": "LOCAL_ONLY",
            "owned_paths": [],
            "reasons": [],
            "warnings": [],
            "verdict": "NO_COMMIT",
            "suggested_message": "noop",
            "decision": {"decision": "NO_COMMIT", "blockers": []},
        },
    )

    latest = load_checkpoint("unit")
    assert latest["next_action"] == ""
    assert latest["current_phase"] == "next-cleared"


def test_create_task_branch_does_not_resurrect_stale_next_action(task_repo, monkeypatch):
    name, _, env = task_repo
    run_cmd(
        [
            "task-start",
            "--task-id",
            "unit",
            "--title",
            "Unit test",
            "--class",
            "SMALL",
            "--legacy",
            "--execution-mode",
            "DOCS",
            "--repo",
            name,
            "--scope",
            f"{name}:.",
        ],
        env=env,
    )
    run_cmd(["task-checkpoint", "--next", "stale-next"], env=env)

    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    os.environ["AI_OS_TASK_STATE_DIR"] = env["AI_OS_TASK_STATE_DIR"]

    import argparse

    import ai_os_task_commit as commit_mod
    from ai_os_task_lifecycle import clear_next
    from ai_os_task_state import load_checkpoint

    original_run = commit_mod.run
    injected = {"done": False}

    def wrapped_run(args, cwd, check=True):
        if args[:3] == ["git", "switch", "-c"] and not injected["done"]:
            injected["done"] = True
            clear_next(argparse.Namespace(task_id="unit"))
        return original_run(args, cwd, check=check)

    monkeypatch.setattr(commit_mod, "run", wrapped_run)
    commit_mod.create_task_branch(argparse.Namespace(task_id="unit", repo=name, name="fix/rmw-branch"))

    latest = load_checkpoint("unit")
    assert latest["next_action"] == ""
    assert latest["current_phase"] == "task-branch"
