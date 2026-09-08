import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
TASK_SCRIPT = ROOT / "scripts" / "ai_os_task.py"
HOOK_SCRIPT = ROOT / "scripts" / "ai_os_codex_hook.py"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plane_harness import child_env, plane_start_args  # noqa: E402


def run_task(args, *, cwd=ROOT, env=None, check=True):
    merged_env = child_env(env)
    proc = subprocess.run(
        [sys.executable, str(TASK_SCRIPT), *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=merged_env,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    return proc


def run_hook(payload, *, cwd=ROOT, env=None, check=True):
    merged_env = child_env(env)
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        cwd=str(cwd),
        text=True,
        input=json.dumps(payload),
        capture_output=True,
        env=merged_env,
    )
    if check and proc.returncode != 0:
        raise AssertionError(proc.stdout + proc.stderr)
    data = json.loads(proc.stdout or "{}")
    return proc, data


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
def hook_repo(tmp_path):
    # Keep git common-dir + plane worktrees on a short absolute path. Nested
    # hermetic TMP under the Execution Plane worktree makes relative GIT_DIR
    # explode ("$GIT_DIR too big") on Windows.
    short_root = Path("C:/aios-hk")
    short_root.mkdir(parents=True, exist_ok=True)
    name = f"h{abs(hash(tmp_path.name)) % 10**8:08d}"
    sandbox = short_root / name
    if sandbox.exists():
        remove_tree(sandbox)
    sandbox.mkdir(parents=True)

    source = sandbox / "src"
    source.mkdir()
    git(source, "init")
    git(source, "config", "user.email", "test@example.invalid")
    git(source, "config", "user.name", "Test User")
    (source / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    git(source, "add", "--", "tracked.txt")
    git(source, "commit", "-m", "init")

    workspace_repo = sandbox / "repo"
    git(sandbox, "clone", str(source), str(workspace_repo))
    git(workspace_repo, "config", "user.email", "test@example.invalid")
    git(workspace_repo, "config", "user.name", "Test User")
    nested = workspace_repo / "nested"
    nested.mkdir()

    # Workspace discovery requires WORKSPACE/<repo>; junction keeps paths short.
    link = ROOT / name
    if link.exists() or link.is_symlink():
        if link.is_dir() and not link.is_symlink():
            remove_tree(link)
        else:
            link.unlink()
    try:
        os.symlink(str(workspace_repo), str(link), target_is_directory=True)
    except OSError:
        # Fallback for unprivileged Windows: directory junction.
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(workspace_repo)],
            check=True,
            capture_output=True,
            text=True,
        )

    env = {"AI_OS_TASK_STATE_DIR": str(sandbox / "state")}
    try:
        yield name, workspace_repo, nested, env
    finally:
        if link.exists() or link.is_symlink():
            try:
                link.unlink()
            except OSError:
                subprocess.run(["cmd", "/c", "rmdir", str(link)], check=False, capture_output=True)
        if sandbox.exists():
            remove_tree(sandbox)


def start_task(hook_repo, *, next_action="Do the next thing.", task_id=None):
    name, _repo, _nested, env = hook_repo
    tid = task_id or TASK_ID
    extra = ["--next", next_action] if next_action else None
    run_task(
        plane_start_args(
            task_id=tid,
            title="Hook unit",
            repo=name,
            scope=f"{name}:tracked.txt",
            task_class="MEDIUM",
            extra=extra,
        ),
        env=env,
    )
    env["AI_OS_TASK_ID"] = tid
    return env


def update_checkpoint(env, *args):
    run_task(["task-checkpoint", *args], env=env)


TASK_ID = "hu"


def active_checkpoint_path(env) -> Path:
    return Path(env["AI_OS_TASK_STATE_DIR"]) / "tasks" / "active" / f"{TASK_ID}.json"


def checkpoint_json(env):
    return json.loads(active_checkpoint_path(env).read_text(encoding="utf-8"))


def set_status(env, status, phase):
    path = active_checkpoint_path(env)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = status
    data["current_phase"] = phase
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hook_payload(event, cwd):
    payload = {
        "session_id": "thr_test",
        "transcript_path": None,
        "cwd": str(cwd),
        "hook_event_name": event,
        "model": "gpt-test",
    }
    if event == "SessionStart":
        payload["source"] = "resume"
        payload["permission_mode"] = "default"
    elif event == "PreCompact":
        payload["trigger"] = "manual"
        payload["turn_id"] = "turn_123"
        payload["permission_mode"] = "default"
    elif event == "SessionEnd":
        payload["reason"] = "other"
    return payload


def test_session_start_without_checkpoint_projects_none(hook_repo):
    _name, repo, _nested, env = hook_repo
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data.get("continue") is True
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert "CURRENT TASK: none" in summary
    assert "Do not invent" in summary


def test_session_start_active_checkpoint_returns_plane_summary(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo, next_action="Implement lifecycle automation.")
    update_checkpoint(env, "--status", "IN_PROGRESS", "--phase", "implement-hooks")
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data["continue"] is True
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert data["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "CURRENT TASK: hu" in summary
    assert "EXECUTION: exec_" in summary
    assert "PROTOCOL: 1.1" in summary
    assert "GENERATION: 1" in summary
    assert "NEXT: Implement lifecycle automation." in summary
    assert "RULE: Use Execution Plane" in summary


@pytest.mark.parametrize(
    ("status", "phase"),
    [
        ("CLOSED", "closed"),
        ("ABORTED_WITH_EVIDENCE", "aborted"),
    ],
)
def test_session_start_closed_or_aborted_is_noop(hook_repo, status, phase):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    if status == "CLOSED":
        data = checkpoint_json(env)
        data["status"] = status
        data["current_phase"] = phase
        archive = Path(env["AI_OS_TASK_STATE_DIR"]) / "tasks" / "archive" / f"{TASK_ID}.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        active_checkpoint_path(env).unlink()
    else:
        set_status(env, status, phase)
        active_checkpoint_path(env).unlink()
    env.pop("AI_OS_TASK_ID", None)
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data.get("continue") is True
    summary = data.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "CURRENT TASK: none" in summary or "KIND: NONE" in summary


def test_precompact_blocks_corrupt_checkpoint(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    path = active_checkpoint_path(env)
    path.write_text("{broken", encoding="utf-8")
    _proc, data = run_hook(hook_payload("PreCompact", repo), env=env)
    assert data["continue"] is False
    assert "corrupt" in data["stopReason"].lower()


def test_session_start_blocks_corrupt_checkpoint(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    path = active_checkpoint_path(env)
    path.write_text("{broken", encoding="utf-8")
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data["continue"] is False
    assert "corrupt" in data["stopReason"].lower()


def test_precompact_refresh_preserves_status_and_phase(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    update_checkpoint(env, "--status", "IN_PROGRESS", "--phase", "before-compact")
    before = checkpoint_json(env)
    time.sleep(1.1)
    _proc, data = run_hook(hook_payload("PreCompact", repo), env=env)
    after = checkpoint_json(env)
    assert data == {"continue": True}
    assert after["status"] == "IN_PROGRESS"
    assert after["current_phase"] == "before-compact"
    assert after["updated_at_utc"] != before["updated_at_utc"]


def test_session_end_best_effort_refreshes_active_checkpoint(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    update_checkpoint(env, "--status", "IN_PROGRESS", "--phase", "finishing")
    before = checkpoint_json(env)
    time.sleep(1.1)
    _proc, data = run_hook(hook_payload("SessionEnd", repo), env=env)
    after = checkpoint_json(env)
    assert data == {"continue": True}
    assert after["updated_at_utc"] != before["updated_at_utc"]


def test_nested_cwd_still_refreshes_and_summarizes(hook_repo):
    _name, _repo, nested, env = hook_repo
    start_task(hook_repo)
    update_checkpoint(env, "--status", "IN_PROGRESS", "--phase", "nested-run")
    _proc, data = run_hook(hook_payload("SessionStart", nested), cwd=nested, env=env)
    assert data["continue"] is True
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert "CURRENT TASK: hu" in summary
    assert "EXECUTION: exec_" in summary


def test_summary_does_not_echo_blocker_secrets(hook_repo):
    _name, repo, _nested, env = hook_repo
    start_task(hook_repo, next_action="X" * 600)
    update_checkpoint(env, "--status", "BLOCKED", "--phase", "waiting", "--blocker", "SECRET=token-value")
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert len(summary) <= 2200
    assert "SECRET=token-value" not in summary
    assert "CURRENT TASK: hu" in summary


def _bundle_for(env, task_id=TASK_ID):
    checkpoint = checkpoint_json(env)
    execution_id = checkpoint["execution_id"]
    path = Path(env["AI_OS_TASK_STATE_DIR"]) / "executions" / execution_id / "TASK_EXECUTION_BUNDLE.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_session_start_points_at_bundle_worktree_not_canonical(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    bundle = _bundle_for(env)
    worktree = Path(bundle["repos"][name]["worktree_path"])
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert str(worktree) in summary
    assert "REPOS:" in summary
    # Canonical shared checkout must not be advertised as the task worktree.
    assert f"{name} -> {repo} @" not in summary.replace("\\", "/")


def test_session_start_after_takeover_shows_generation_two(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    bundle = _bundle_for(env)
    g1 = Path(bundle["repos"][name]["worktree_path"]).resolve()
    run_task(["execution-takeover", "--task-id", TASK_ID], env=env)
    bundle2 = _bundle_for(env)
    g2 = Path(bundle2["repos"][name]["worktree_path"]).resolve()
    assert g2 != g1
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert "GENERATION: 2" in summary
    assert str(g2) in summary
    # Current worktree line must name g2, not the revoked g1 path as the target.
    assert f"-> {g2}" in summary or f"-> {str(g2)}" in summary
    assert f"-> {g1} @" not in summary


def test_session_start_shows_tainted_not_healthy(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    os.environ["AI_OS_TASK_STATE_DIR"] = env["AI_OS_TASK_STATE_DIR"]
    sys.path.insert(0, str(ROOT / "scripts"))
    from ai_os_execution.bundle import load_bundle_for_task, save_bundle
    from ai_os_execution.tainted import mark_tainted

    bundle = load_bundle_for_task(TASK_ID)
    mark_tainted(bundle, "UNTRUSTED_PROOF_EXECUTION", detail="raw pytest")
    save_bundle(bundle)
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert "TAINTED" in summary
    assert "UNTRUSTED_PROOF_EXECUTION" in summary
    assert "not PASS" in summary
    assert "ACTIVE_CLEAN" not in summary


def test_session_start_stale_lease_does_not_takeover(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    before = _bundle_for(env)
    generation_before = int(before.get("lease_generation") or 1)
    leases_path = Path(env["AI_OS_TASK_STATE_DIR"]) / "write-leases.json"
    payload = json.loads(leases_path.read_text(encoding="utf-8")) if leases_path.exists() else {"leases": []}
    leases = list(payload.get("leases") or [])
    for lease in leases:
        if lease.get("execution_id") == before["execution_id"]:
            lease["expires_at"] = "2000-01-01T00:00:00Z"
    leases_path.write_text(json.dumps({"leases": leases}, indent=2) + "\n", encoding="utf-8")
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    after = _bundle_for(env)
    assert int(after.get("lease_generation") or 1) == generation_before
    assert Path(after["repos"][name]["worktree_path"]) == Path(before["repos"][name]["worktree_path"])
    assert "STALE_LEASE" in summary
    assert "takeover" in summary.lower()


def test_session_start_legacy_task_no_fake_bundle(hook_repo):
    name, repo, _nested, env = hook_repo
    run_task(
        [
            "task-start",
            "--task-id",
            "lg",
            "--title",
            "legacy",
            "--class",
            "SMALL",
            "--legacy",
            "--execution-mode",
            "DOCS",
            "--repo",
            name,
            "--scope",
            f"{name}:tracked.txt",
        ],
        env=env,
    )
    env = dict(env)
    env["AI_OS_TASK_ID"] = "lg"
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert "KIND: LEGACY" in summary or "LEGACY" in summary
    assert "EXECUTION: none" in summary or "execution_id" not in summary.lower()
    assert "GENERATION:" not in summary or "GENERATION: 0" not in summary
    assert "Do not fabricate" in summary or "not a plane" in summary.lower() or "Legacy" in summary


def test_session_start_is_read_only_on_execution_bundle(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    before = _bundle_for(env)
    before_text = json.dumps(before, sort_keys=True)
    owned_before = list((before.get("ownership") or {}).get("owned_paths") or [])
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data["continue"] is True
    after = _bundle_for(env)
    assert int(after.get("lease_generation") or 1) == int(before.get("lease_generation") or 1)
    assert list((after.get("ownership") or {}).get("owned_paths") or []) == owned_before
    # Allow head refresh noise only if present; generation/ownership/status must not flip via SessionStart.
    assert after.get("status") == before.get("status")
    assert after["execution_id"] == before["execution_id"]
    assert before_text  # sanity


def test_session_start_secret_leak_guard(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    bundle = _bundle_for(env)
    secrets_dir = Path(env["AI_OS_TASK_STATE_DIR"]) / "executions" / bundle["execution_id"] / "scratch" / "secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)
    (secrets_dir / "workload_secrets.json").write_text(
        json.dumps(
            {
                "MAILBOX_MEMORY_DATABASE_URL": "postgresql://task:s3cret@127.0.0.1/taskdb",
                "GMAIL_TOKEN": "ya29.secret-token",
                "OPENAI_API_KEY": "sk-live-secret-key",
            }
        ),
        encoding="utf-8",
    )
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"].lower()
    assert "postgresql://" not in summary
    assert "s3cret" not in summary
    assert "ya29." not in summary
    assert "sk-live" not in summary
    assert "gmail_token" not in summary


def test_session_start_receipt_from_current_generation(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    run_task(
        ["exec", "--task-id", TASK_ID, "--repo", name, "--", sys.executable, "-c", "print('g1')"],
        env=env,
    )
    run_task(["execution-takeover", "--task-id", TASK_ID], env=env)
    run_task(
        ["exec", "--task-id", TASK_ID, "--repo", name, "--", sys.executable, "-c", "print('g2')"],
        env=env,
    )
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert "GENERATION: 2" in summary
    assert "LATEST TRUSTED RECEIPT:" in summary
    assert "gen=2" in summary or "gen=2" in summary.replace(" ", "")


def test_session_start_final_head_status_visible(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    summary = data["hookSpecificOutput"]["additionalContext"]
    assert "FINAL_HEAD:" in summary
    assert any(token in summary for token in ("VALID", "INVALID", "STALE", "NONE", "N/A"))


def test_session_start_refreshes_generated_projections(hook_repo):
    name, repo, _nested, env = hook_repo
    start_task(hook_repo)
    campaign = Path(env["AI_OS_TASK_STATE_DIR"]) / "CAMPAIGN_STATE.generated.json"
    if campaign.exists():
        campaign.unlink()
    _proc, data = run_hook(hook_payload("SessionStart", repo), env=env)
    assert data["continue"] is True
    assert campaign.exists()
    payload = json.loads(campaign.read_text(encoding="utf-8"))
    bundle = _bundle_for(env)
    assert payload["execution_id"] == bundle["execution_id"]
    assert payload["execution_generation"] == 1
    entry = Path(env["AI_OS_TASK_STATE_DIR"]) / "executions" / bundle["execution_id"] / "TASK_ENTRY.md"
    assert entry.exists()
    text = entry.read_text(encoding="utf-8")
    assert bundle["repos"][name]["worktree_path"] in text
    assert "postgresql://" not in text.lower()
