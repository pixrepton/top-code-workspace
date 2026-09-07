"""Acceptance tests for AI-OS Reproducible Execution Plane V1."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ai_os_task.py"
sys.path.insert(0, str(ROOT / "scripts"))

STORE_KEYS = (
    "MAILBOX_MEMORY_DATABASE_URL",
    "MAILBOX_MEMORY_ASOF_DATABASE_URL",
    "DATABASE_URL",
    "AI_OS_EXECUTION_ID",
    "AI_OS_TASK_ID",
    "AI_OS_REPO_PATH",
    "AI_OS_GRAPH_INDEX_SHA",
    "AI_OS_DB_HOST",
    "AI_OS_DB_CONTAINER_HOST",
)


def run_cmd(args, env, check=True):
    merged = os.environ.copy()
    for key in STORE_KEYS:
        merged.pop(key, None)
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


def init_repo(path: Path, name: str) -> None:
    path.mkdir(parents=True)
    git(path, "init")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "user.name", "Test User")
    (path / "tracked.txt").write_text(f"{name} initial\n", encoding="utf-8")
    git(path, "add", "--", "tracked.txt")
    git(path, "commit", "-m", f"init {name}")


@pytest.fixture
def plane_workspace(tmp_path):
    names = []
    env = {"AI_OS_TASK_STATE_DIR": str(tmp_path / "state")}
    try:
        yield names, env, tmp_path
    finally:
        for name in names:
            target = ROOT / name
            if target.exists():
                remove_tree(target)


def add_named_repo(plane_workspace, label: str) -> tuple[str, Path]:
    names, env, tmp_path = plane_workspace
    source = tmp_path / f"src-{label}"
    init_repo(source, label)
    name = f"tmp-exec-plane-{label}-{tmp_path.name}"
    dest = ROOT / name
    if dest.exists():
        remove_tree(dest)
    git(ROOT, "clone", str(source), str(dest))
    git(dest, "config", "user.email", "test@example.invalid")
    git(dest, "config", "user.name", "Test User")
    names.append(name)
    return name, dest


def start_plane(env, repo_name, task_id="plane-unit", extra=None):
    args = [
        "start",
        "--task-id",
        task_id,
        "--title",
        "Execution plane unit",
        "--class",
        "SMALL",
        "--repo",
        repo_name,
        "--scope",
        f"{repo_name}:.",
        "--no-db-isolation",
        "--execution-mode",
        "TEST",
    ]
    if extra:
        args.extend(extra)
    return run_cmd(args, env=env)


def bundle_for(env, task_id="plane-unit"):
    index = Path(env["AI_OS_TASK_STATE_DIR"]) / "executions" / "index.json"
    mapping = json.loads(index.read_text(encoding="utf-8"))
    execution_id = mapping[task_id]
    path = Path(env["AI_OS_TASK_STATE_DIR"]) / "executions" / execution_id / "TASK_EXECUTION_BUNDLE.json"
    return json.loads(path.read_text(encoding="utf-8")), path


def test_a_worktree_native_ignores_canonical_dirty(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, canonical = add_named_repo(plane_workspace, "a")
    (canonical / "dirty-canonical.txt").write_text("shared dirty\n", encoding="utf-8")
    start_plane(env, repo_name)
    bundle, _ = bundle_for(env)
    worktree = Path(bundle["repos"][repo_name]["worktree_path"])
    assert worktree.exists()
    assert worktree.resolve() != canonical.resolve()
    assert not (worktree / "dirty-canonical.txt").exists()
    (worktree / "tracked.txt").write_text("worktree change\n", encoding="utf-8")
    git(worktree, "add", "--", "tracked.txt")
    run_cmd(
        [
            "task-gate",
            "--task-id",
            "plane-unit",
            "--gate-id",
            "unit-clean",
            "--repo",
            repo_name,
            "--",
            sys.executable,
            "-c",
            "import pathlib; assert not pathlib.Path('dirty-canonical.txt').exists(); print('ok')",
        ],
        env=env,
    )
    run_cmd(["task-commit", "--task-id", "plane-unit", "--repo", repo_name, "--message", "plane worktree commit"], env=env)
    canonical_head = git(canonical, "rev-parse", "HEAD").stdout.strip()
    worktree_head = git(worktree, "rev-parse", "HEAD").stdout.strip()
    assert canonical_head != worktree_head
    assert (canonical / "dirty-canonical.txt").exists()
    assert git(canonical, "status", "--porcelain").stdout.strip()


def test_b_multi_repo_distinct_base_sha(plane_workspace):
    names, env, _ = plane_workspace
    repo_a, path_a = add_named_repo(plane_workspace, "b1")
    repo_b, path_b = add_named_repo(plane_workspace, "b2")
    (path_b / "tracked.txt").write_text("second repo unique\n", encoding="utf-8")
    git(path_b, "add", "--", "tracked.txt")
    git(path_b, "commit", "-m", "diverge b")
    sha_a = git(path_a, "rev-parse", "HEAD").stdout.strip()
    sha_b = git(path_b, "rev-parse", "HEAD").stdout.strip()
    assert sha_a != sha_b
    run_cmd(
        [
            "start",
            "--task-id",
            "plane-multi",
            "--title",
            "multi",
            "--class",
            "SMALL",
            "--repo",
            repo_a,
            "--repo",
            repo_b,
            "--scope",
            f"{repo_a}:.",
            "--scope",
            f"{repo_b}:.",
            "--no-db-isolation",
        ],
        env=env,
    )
    bundle, _ = bundle_for(env, "plane-multi")
    assert bundle["repos"][repo_a]["base_sha"] == sha_a
    assert bundle["repos"][repo_b]["base_sha"] == sha_b
    assert bundle["repos"][repo_a]["worktree_path"] != bundle["repos"][repo_b]["worktree_path"]


def test_d_store_leak_fail_closed(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "d")
    leak_env = dict(env)
    leak_env["MAILBOX_MEMORY_DATABASE_URL"] = "postgresql://writer:secret@127.0.0.1:54129/mailbox_memory"
    proc = run_cmd(
        [
            "start",
            "--task-id",
            "plane-leak",
            "--title",
            "leak",
            "--class",
            "SMALL",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
            "--no-db-isolation",
            "--execution-mode",
            "TEST",
        ],
        env=leak_env,
        check=False,
    )
    assert proc.returncode == 2
    assert "FAIL CLOSED" in (proc.stderr + proc.stdout)


def test_e_ownership_lease_conflict_and_shared_read(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, canonical = add_named_repo(plane_workspace, "e")
    (canonical / "other.txt").write_text("other\n", encoding="utf-8")
    git(canonical, "add", "--", "other.txt")
    git(canonical, "commit", "-m", "add other")
    run_cmd(
        [
            "start",
            "--task-id",
            "plane-a",
            "--title",
            "first",
            "--class",
            "SMALL",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:tracked.txt",
            "--no-db-isolation",
        ],
        env=env,
    )
    run_cmd(
        [
            "start",
            "--task-id",
            "plane-b",
            "--title",
            "second",
            "--class",
            "SMALL",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:other.txt",
            "--no-db-isolation",
        ],
        env=env,
    )
    proc = run_cmd(
        [
            "task-owner-add",
            "--task-id",
            "plane-b",
            "--scope",
            f"{repo_name}:tracked.txt",
        ],
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "lease conflict" in (proc.stderr + proc.stdout).lower()
    assert (canonical / "tracked.txt").exists()
    bundle, _ = bundle_for(env, "plane-a")
    assert Path(bundle["repos"][repo_name]["worktree_path"], "tracked.txt").exists()


def test_f_expired_lease_recovery_keeps_audit(plane_workspace):
    from ai_os_execution.lease import acquire_lease, load_leases, recover_stale_leases

    previous = os.environ.get("AI_OS_TASK_STATE_DIR")
    os.environ["AI_OS_TASK_STATE_DIR"] = str(plane_workspace[2] / "state")
    try:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        past = (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
        acquire_lease(
            task_id="old",
            execution_id="exec_oldlease_abc123",
            repo="demo",
            owned_paths=["demo:tracked.txt"],
            now=past,
            ttl_seconds=1,
        )
        recovered = recover_stale_leases(now=now.isoformat().replace("+00:00", "Z"))
        assert recovered
        assert recovered[0]["status"] == "STALE_LEASE"
        second = acquire_lease(
            task_id="new",
            execution_id="exec_newlease_def456",
            repo="demo",
            owned_paths=["demo:tracked.txt"],
            now=now.isoformat().replace("+00:00", "Z"),
        )
        assert second["status"] == "ACTIVE"
        statuses = {item["lease_id"]: item["status"] for item in load_leases()}
        assert "STALE_LEASE" in statuses.values()
        assert "ACTIVE" in statuses.values()
    finally:
        if previous is None:
            os.environ.pop("AI_OS_TASK_STATE_DIR", None)
        else:
            os.environ["AI_OS_TASK_STATE_DIR"] = previous


def test_g_final_head_gate_after_commit(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "g")
    start_plane(env, repo_name)
    bundle, _ = bundle_for(env)
    worktree = Path(bundle["repos"][repo_name]["worktree_path"])
    run_cmd(
        [
            "task-gate",
            "--task-id",
            "plane-unit",
            "--gate-id",
            "dev-proof",
            "--repo",
            repo_name,
            "--",
            sys.executable,
            "-c",
            "print('dev')",
        ],
        env=env,
    )
    (worktree / "tracked.txt").write_text("after gate\n", encoding="utf-8")
    git(worktree, "add", "--", "tracked.txt")
    run_cmd(
        [
            "task-gate",
            "--task-id",
            "plane-unit",
            "--gate-id",
            "dev-proof",
            "--repo",
            repo_name,
            "--",
            sys.executable,
            "-c",
            "print('dev-after-edit')",
        ],
        env=env,
    )
    run_cmd(["task-commit", "--task-id", "plane-unit", "--repo", repo_name, "--message", "final head"], env=env)
    checkpoint = json.loads((Path(env["AI_OS_TASK_STATE_DIR"]) / "tasks" / "active" / "plane-unit.json").read_text(encoding="utf-8"))
    gate_ids = [gate["gate_id"] for gate in checkpoint["gates"]]
    assert "dev-proof" in gate_ids
    assert "FINAL_HEAD_GATE" in gate_ids
    run_cmd(["task-checkpoint", "--task-id", "plane-unit", "--status", "READY_TO_CLOSE", "--next", ""], env=env)
    close = run_cmd(["task-close", "--task-id", "plane-unit"], env=env)
    assert close.returncode == 0


def test_h_stale_proof_fingerprint(plane_workspace):
    from ai_os_execution.proof import build_fingerprint_v2

    os.environ["AI_OS_TASK_STATE_DIR"] = str(plane_workspace[2] / "state")
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "h")
    start_plane(env, repo_name, task_id="plane-h")
    bundle, _ = bundle_for(env, "plane-h")
    env = dict(env)
    env["AI_OS_TASK_ID"] = "plane-h"
    env["AI_OS_EXECUTION_ID"] = bundle["execution_id"]
    proc = run_cmd(
        [
            "task-gate",
            "--task-id",
            "plane-h",
            "--gate-id",
            "proof-h",
            "--repo",
            repo_name,
            "--",
            sys.executable,
            "-c",
            "print('h')",
        ],
        env=env,
    )
    checkpoint = json.loads((Path(env["AI_OS_TASK_STATE_DIR"]) / "tasks" / "active" / "plane-h.json").read_text(encoding="utf-8"))
    fp = checkpoint["gates"][-1]["fingerprint"]
    assert fp["fingerprint_version"] == 2
    changed = dict(fp)
    changed["repo_sha_set"] = {repo_name: "0" * 40}
    assert changed != fp
    changed_digest = dict(fp)
    changed_digest["image_digest"] = "sha256:other"
    assert changed_digest != fp
    changed_bench = dict(fp)
    changed_bench["benchmark_manifest_hash"] = "abc"
    changed_bench["scorer_hash"] = "def"
    assert changed_bench != fp


def test_i_image_source_sha_mismatch_rejected(plane_workspace):
    from ai_os_execution.proof import validate_image_provenance
    from ai_os_task_errors import TaskError

    bundle = {
        "repos": {"gmail-agent": {"current_sha": "aaa"}},
        "runtime": {"image_digests": {"gmail-agent": {"digest": "sha256:abc", "source_sha": "bbb"}}},
    }
    with pytest.raises(TaskError):
        validate_image_provenance(bundle, "gmail-agent", "sha256:abc")


def test_k_resume_returns_bundle_without_transcript(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "k")
    start_plane(env, repo_name, task_id="plane-k")
    proc = run_cmd(["resume", "--task-id", "plane-k"], env=env)
    # resume prints summary then JSON
    payload = json.loads(proc.stdout[proc.stdout.find("{") :])
    assert payload["execution_id"]
    assert payload["worktrees"][repo_name]
    assert "owned_paths" in payload
    assert "task_entry" in payload
    dumped = json.dumps(payload)
    assert "host_dsn" not in dumped
    assert "container_dsn" not in dumped
    assert "postgresql://" not in dumped


def test_l_graph_freshness_stale_advisory(tmp_path):
    from ai_os_execution.preflight import graph_freshness_for_repo

    previous = os.environ.get("AI_OS_GRAPH_INDEX_SHA")
    try:
        os.environ["AI_OS_GRAPH_INDEX_SHA"] = "stale" * 8
        result = graph_freshness_for_repo(tmp_path, "current" * 8)
        assert result["status"] == "STALE_ADVISORY"
        os.environ["AI_OS_GRAPH_INDEX_SHA"] = "current" * 8
        assert graph_freshness_for_repo(tmp_path, "current" * 8)["status"] == "CURRENT"
    finally:
        if previous is None:
            os.environ.pop("AI_OS_GRAPH_INDEX_SHA", None)
        else:
            os.environ["AI_OS_GRAPH_INDEX_SHA"] = previous


def test_m_wrong_container_hostname_fail_closed(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "m")
    proc = run_cmd(
        [
            "start",
            "--task-id",
            "plane-m",
            "--title",
            "hostcheck",
            "--class",
            "SMALL",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
            "--no-db-isolation",
            "--db-container-host",
            "127.0.0.1",
        ],
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "HOST/CONTAINER" in (proc.stderr + proc.stdout)


def docker_available() -> bool:
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def test_c_and_j_live_write_denied_and_db_isolation(plane_workspace):
    if not docker_available():
        pytest.fail("Docker is required for live-write permission and DB isolation proofs")
    names, env, tmp_path = plane_workspace
    name = f"aios-ep-pg-{tmp_path.name[-8:]}"
    port = "55432"
    run = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=test",
            "-p",
            f"127.0.0.1:{port}:5432",
            "postgres:16",
        ],
        capture_output=True,
        text=True,
    )
    if run.returncode != 0:
        pytest.fail(run.stderr or run.stdout)
    try:
        for _ in range(30):
            ready = subprocess.run(
                ["docker", "exec", name, "pg_isready", "-U", "postgres"],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            pytest.fail("postgres did not become ready")
        subprocess.run(
            ["docker", "exec", name, "psql", "-U", "postgres", "-c", "CREATE DATABASE mailbox_memory;"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "docker",
                "exec",
                name,
                "psql",
                "-U",
                "postgres",
                "-d",
                "mailbox_memory",
                "-c",
                "CREATE TABLE IF NOT EXISTS mailbox_memory_cases (id text PRIMARY KEY);",
            ],
            check=True,
            capture_output=True,
        )
        from ai_os_execution.database import provision_isolated_database

        first = provision_isolated_database(
            execution_id="exec_dbone_aaa111",
            execution_mode="TEST",
            docker_container=name,
            host_side_host="127.0.0.1",
            container_side_host="mailbox-memory-db",
            port=port,
        )
        second = provision_isolated_database(
            execution_id="exec_dbtwo_bbb222",
            execution_mode="TEST",
            docker_container=name,
            host_side_host="127.0.0.1",
            container_side_host="mailbox-memory-db",
            port=port,
        )
        assert first["database_name"] != second["database_name"]
        assert first["principal"] != second["principal"]
        denied = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={first['password']}",
                name,
                "psql",
                "-U",
                first["principal"],
                "-d",
                "mailbox_memory",
                "-c",
                "INSERT INTO mailbox_memory_cases(id) VALUES ('aios-exec-plane-probe');",
            ],
            capture_output=True,
            text=True,
        )
        assert denied.returncode != 0, denied.stdout + denied.stderr
        assert "permission denied" in (denied.stderr + denied.stdout).lower() or "connect" in (denied.stderr + denied.stdout).lower()
        subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={first['password']}",
                name,
                "psql",
                "-U",
                first["principal"],
                "-d",
                first["database_name"],
                "-c",
                "CREATE TABLE t(v int); INSERT INTO t VALUES (1);",
            ],
            check=True,
        )
        subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={second['password']}",
                name,
                "psql",
                "-U",
                second["principal"],
                "-d",
                second["database_name"],
                "-c",
                "CREATE TABLE t(v int); INSERT INTO t VALUES (2);",
            ],
            check=True,
        )
        count = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={first['password']}",
                name,
                "psql",
                "-U",
                first["principal"],
                "-d",
                first["database_name"],
                "-tAc",
                "SELECT v FROM t;",
            ],
            capture_output=True,
            text=True,
        )
        other = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={second['password']}",
                name,
                "psql",
                "-U",
                second["principal"],
                "-d",
                second["database_name"],
                "-tAc",
                "SELECT v FROM t;",
            ],
            capture_output=True,
            text=True,
        )
        assert "1" in (count.stdout or "")
        assert "2" in (other.stdout or "")
        cross = subprocess.run(
            [
                "docker",
                "exec",
                "-e",
                f"PGPASSWORD={first['password']}",
                name,
                "psql",
                "-U",
                first["principal"],
                "-d",
                second["database_name"],
                "-c",
                "SELECT 1;",
            ],
            capture_output=True,
            text=True,
        )
        assert cross.returncode != 0
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def test_n_hermetic_userprofile_differs_from_host(tmp_path, monkeypatch):
    from ai_os_execution.bundle import execution_dir, new_bundle, save_bundle
    from ai_os_execution.child_env import build_effective_child_env, provision_hermetic_profile, write_public_env_file

    state = tmp_path / "state"
    monkeypatch.setenv("AI_OS_TASK_STATE_DIR", str(state))
    host_home = tmp_path / "host-home"
    host_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(host_home))
    monkeypatch.setenv("HOME", str(host_home))

    execution_id = "exec_20250101T120000Z_aabbcc"
    root = execution_dir(execution_id)
    root.mkdir(parents=True)
    hermetic = provision_hermetic_profile(root)
    write_public_env_file(execution_id, {"AI_OS_EXECUTION_MODE": "TEST"})
    bundle = new_bundle(
        execution_id=execution_id,
        task_id="hermetic-userprofile",
        campaign_id="hermetic-userprofile",
        repos={
            "tmp": {
                "canonical_repo": str(tmp_path / "repo"),
                "worktree_path": str(tmp_path / "wt"),
                "base_sha": "abc",
                "current_sha": "abc",
                "branch": "task/hermetic",
                "mutation_mode": "MUTATE",
            }
        },
    )
    save_bundle(bundle)

    env = build_effective_child_env(bundle)
    assert env["USERPROFILE"] != str(host_home)
    assert env["USERPROFILE"] == hermetic["USERPROFILE"]
    assert env.get("PYTHONNOUSERSITE") == "1"


def test_o_host_poison_tokens_absent_from_child_env(tmp_path, monkeypatch):
    from ai_os_execution.bundle import execution_dir, new_bundle, save_bundle
    from ai_os_execution.child_env import build_effective_child_env, provision_hermetic_profile, write_public_env_file

    state = tmp_path / "state"
    monkeypatch.setenv("AI_OS_TASK_STATE_DIR", str(state))
    monkeypatch.setenv("GMAIL_ACCESS_TOKEN", "host-live-token")
    monkeypatch.setenv("MAILBOX_MEMORY_CANONICAL_DATABASE_URL", "postgresql://canonical:secret@127.0.0.1/mailbox_memory")
    monkeypatch.setenv("PYTHONPATH", "/host/site-packages")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/ssh-agent")

    execution_id = "exec_20250101T120001Z_aabbcc"
    root = execution_dir(execution_id)
    root.mkdir(parents=True)
    provision_hermetic_profile(root)
    write_public_env_file(execution_id, {"AI_OS_EXECUTION_MODE": "TEST"})
    bundle = new_bundle(
        execution_id=execution_id,
        task_id="poison-env",
        campaign_id="poison-env",
        repos={
            "tmp": {
                "canonical_repo": str(tmp_path / "repo"),
                "worktree_path": str(tmp_path / "wt"),
                "base_sha": "abc",
                "current_sha": "abc",
                "branch": "task/poison",
                "mutation_mode": "MUTATE",
            }
        },
    )
    save_bundle(bundle)

    env = build_effective_child_env(bundle)
    for key in ("GMAIL_ACCESS_TOKEN", "MAILBOX_MEMORY_CANONICAL_DATABASE_URL", "PYTHONPATH", "SSH_AUTH_SOCK"):
        assert key not in env


def test_p_public_bundle_whitelist_excludes_secrets(plane_workspace):
    from ai_os_execution.public_bundle import public_bundle

    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "public-bundle")
    start_plane(env, repo_name, task_id="public-bundle")
    bundle, _ = bundle_for(env, "public-bundle")
    payload = public_bundle(bundle)
    blob = json.dumps(payload).lower()
    assert "postgresql://" not in blob
    assert "host_dsn" not in blob
    assert "container_dsn" not in blob
    assert "password" not in blob
    assert payload.get("hermetic")


def test_q_gate_subprocess_uses_hermetic_profile_paths(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "gate-hermetic")
    start_plane(env, repo_name, task_id="gate-hermetic")
    run_cmd(
        [
            "task-gate",
            "--task-id",
            "gate-hermetic",
            "--gate-id",
            "hermetic-profile",
            "--repo",
            repo_name,
            "--",
            sys.executable,
            "-c",
            (
                "import os; "
                "up = os.environ['USERPROFILE'].replace('\\\\', '/'); "
                "dc = os.environ['DOCKER_CONFIG'].replace('\\\\', '/'); "
                "gc = os.environ['GIT_CONFIG_GLOBAL'].replace('\\\\', '/'); "
                "assert '/scratch/profile/' in up; "
                "assert '/scratch/profile/' in dc; "
                "assert '/scratch/profile/' in gc; "
                "assert 'PYTHONPATH' not in os.environ; "
                "assert os.environ.get('PYTHONNOUSERSITE') == '1'; "
                "print('ok')"
            ),
        ],
        env=env,
    )


def _active_checkpoint(env, task_id: str) -> dict:
    path = Path(env["AI_OS_TASK_STATE_DIR"]) / "tasks" / "active" / f"{task_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_r_task_start_default_provisions_plane(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "f0-default")
    proc = run_cmd(
        [
            "task-start",
            "--task-id",
            "f0-default",
            "--title",
            "F0 default plane",
            "--class",
            "SMALL",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
            "--no-db-isolation",
            "--execution-mode",
            "TEST",
        ],
        env=env,
    )
    assert "TASK READY" in proc.stdout
    checkpoint = _active_checkpoint(env, "f0-default")
    assert checkpoint.get("execution_id")
    assert checkpoint.get("execution_mode") == "TEST"
    assert not checkpoint.get("execution_legacy")


def test_s_legacy_small_docs_checkpoint_only(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "f0-legacy")
    run_cmd(
        [
            "task-start",
            "--task-id",
            "f0-legacy",
            "--title",
            "F0 legacy docs",
            "--class",
            "SMALL",
            "--legacy",
            "--execution-mode",
            "DOCS",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
        ],
        env=env,
    )
    checkpoint = _active_checkpoint(env, "f0-legacy")
    assert checkpoint.get("execution_legacy") is True
    assert checkpoint.get("execution_mode") == "DOCS"
    assert not checkpoint.get("execution_id")
    index = Path(env["AI_OS_TASK_STATE_DIR"]) / "executions" / "index.json"
    if index.exists():
        mapping = json.loads(index.read_text(encoding="utf-8"))
        assert "f0-legacy" not in mapping


def test_t_legacy_small_mutate_rejected(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "f0-mutate")
    proc = run_cmd(
        [
            "task-start",
            "--task-id",
            "f0-mutate",
            "--title",
            "F0 legacy mutate",
            "--class",
            "SMALL",
            "--legacy",
            "--execution-mode",
            "MUTATE",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
        ],
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "LEGACY_EXECUTION_MODES" in proc.stderr or "DOCS" in proc.stderr


def test_u_legacy_medium_rejected(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "f0-medium")
    proc = run_cmd(
        [
            "task-start",
            "--task-id",
            "f0-medium",
            "--title",
            "F0 legacy medium",
            "--class",
            "MEDIUM",
            "--legacy",
            "--execution-mode",
            "DOCS",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
        ],
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "SMALL" in proc.stderr


def test_v_start_rejects_legacy_flag(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "f0-start-legacy")
    proc = run_cmd(
        [
            "start",
            "--task-id",
            "f0-start-legacy",
            "--title",
            "F0 start legacy",
            "--class",
            "SMALL",
            "--legacy",
            "--execution-mode",
            "TEST",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
            "--no-db-isolation",
        ],
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "legacy" in proc.stderr.lower()


def test_w_mutate_gmail_send_request_fail_closed(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "f2-gmail")
    leak_env = dict(env)
    leak_env["GMAIL_PRODUCTION_SEND"] = "1"
    proc = run_cmd(
        [
            "start",
            "--task-id",
            "f2-gmail",
            "--title",
            "gmail send deny",
            "--class",
            "SMALL",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
            "--no-db-isolation",
            "--execution-mode",
            "MUTATE",
        ],
        env=leak_env,
        check=False,
    )
    assert proc.returncode == 2
    assert "gmail_send" in (proc.stderr + proc.stdout).lower()


def test_x_semantic_clock_sentinel_uses_replay_as_of():
    from ai_os_execution.semantic_clock import build_semantic_clock, scoring_temporal_instant

    clock = build_semantic_clock(
        seed_origin="HISTORICAL_REPLAY",
        execution_mode="REPLAY",
        seed_identity="seed-abc",
        replay_as_of="2024-06-15T12:00:00+02:00",
        timezone_name="Europe/Warsaw",
        schema_revision="rev1",
        evaluator_version="eval1",
        fixture_hash="fix1",
        scoring_paths_proven=True,
    )
    instant = scoring_temporal_instant(clock)
    assert instant.year == 2024
    assert instant.month == 6
    assert instant.day == 15


def test_y_proof_bundle_records_wall_executed_at(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "f2-proof")
    start_plane(env, repo_name, task_id="f2-proof")
    run_cmd(
        [
            "task-gate",
            "--task-id",
            "f2-proof",
            "--gate-id",
            "proof-clock",
            "--repo",
            repo_name,
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ],
        env=env,
    )
    bundle, _ = bundle_for(env, "f2-proof")
    proof_path = (
        Path(env["AI_OS_TASK_STATE_DIR"]) / "executions" / bundle["execution_id"] / "PROOF_BUNDLE.json"
    )
    assert proof_path.exists()
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof.get("executed_at")
    assert proof.get("timestamp") == proof.get("executed_at")
    replay_pin = (proof.get("semantic_clock") or {}).get("pins", {}).get("replay_as_of")
    if replay_pin:
        assert replay_pin != proof.get("executed_at")


def test_z_historical_replay_without_pins_blocked(plane_workspace):
    names, env, _ = plane_workspace
    repo_name, _ = add_named_repo(plane_workspace, "f2-blocked")
    proc = run_cmd(
        [
            "start",
            "--task-id",
            "f2-blocked",
            "--title",
            "blocked replay",
            "--class",
            "SMALL",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:.",
            "--no-db-isolation",
            "--execution-mode",
            "REPLAY",
            "--seed-origin",
            "HISTORICAL_REPLAY",
        ],
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "BLOCKED_TIME_NOT_CONTROLLED" in (proc.stderr + proc.stdout)
