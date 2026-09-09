"""F5 acceptance test: historical replay enters and closes through Execution Plane."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from scripts.test_ai_os_execution_plane import (
    add_named_repo,
    bundle_for,
    git,
    plane_workspace,
    run_cmd,
)


REPLAY_AS_OF = "2026-08-27T07:42:45+00:00"
FIXTURE_HASH = "2abf6018da3e7e4661802731dd1534e7c5f9177e3346d457e660271cc55e5a40"


def test_f5_historical_replay_session_start_full_lifecycle(plane_workspace, monkeypatch) -> None:
    for key in ("AI_OS_TASK_ID", "AI_OS_EXECUTION_ID", "AI_OS_REPO_PATH"):
        monkeypatch.delenv(key, raising=False)
    repo_name, canonical = add_named_repo(plane_workspace, "f5-history")
    git(canonical, "branch", "-m", "fixture-base")
    _names, env, _tmp_path = plane_workspace
    task_id = "f5-history"
    next_action = "Run bounded three-trajectory historical replay"

    run_cmd(
        [
            "start",
            "--task-id",
            task_id,
            "--title",
            "F5 historical replay dogfood",
            "--class",
            "SMALL",
            "--repo",
            repo_name,
            "--scope",
            f"{repo_name}:tracked.txt",
            "--next",
            next_action,
            "--publication-mode",
            "LOCAL_ONLY",
            "--execution-mode",
            "BENCHMARK",
            "--campaign-id",
            "F5_HISTORY_DOGFOOD",
            "--seed-origin",
            "HISTORICAL_REPLAY",
            "--capability-profile",
            "NO_EXTERNAL",
            "--replay-as-of",
            REPLAY_AS_OF,
            "--replay-timezone",
            "Europe/Warsaw",
            "--schema-revision",
            "historical_mailbox.v1",
            "--evaluator-version",
            "p3-dogfood.v1",
            "--fixture-hash",
            FIXTURE_HASH,
            "--scoring-paths-proven",
            "--no-db-isolation",
        ],
        env=env,
    )

    bundle, bundle_path = bundle_for(env, task_id)
    before_session_start = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    session = run_cmd(["session-start", "--task-id", task_id, "--json"], env=env)
    payload = json.loads(session.stdout)
    after_session_start = hashlib.sha256(bundle_path.read_bytes()).hexdigest()

    assert before_session_start == after_session_start
    assert payload["current_task"] == task_id
    assert payload["execution_id"] == bundle["execution_id"]
    assert payload["execution_generation"] == 1
    assert payload["next_action"] == next_action
    assert payload["final_head_status"] in {"INVALID", "STALE"}
    assert str(Path(bundle["repos"][repo_name]["worktree_path"])) in payload["inject"]
    assert next_action in payload["inject"]
    assert bundle["semantic_clock"]["status"] == "CONTROLLED"
    assert bundle["semantic_clock"]["pins"]["replay_as_of"] == REPLAY_AS_OF
    assert bundle["semantic_clock"]["pins"]["fixture_hash"] == FIXTURE_HASH
    assert set(bundle["capabilities"]["effective"].values()) == {"DENY"}
    assert "postgresql://" not in payload["inject"].lower()
    assert "password" not in payload["inject"].lower()

    worktree = Path(bundle["repos"][repo_name]["worktree_path"])
    (worktree / "tracked.txt").write_text("historical replay proven\n", encoding="utf-8")
    git(worktree, "add", "--", "tracked.txt")
    proof_command = [
        sys.executable,
        "-c",
        (
            "import os; "
            "assert os.environ['AI_OS_EXECUTION_MODE'] == 'BENCHMARK'; "
            f"assert os.environ['AI_OS_TASK_ID'] == '{task_id}'; "
            "print('F5_HISTORICAL_REPLAY_MEDIATED_PASS')"
        ),
    ]
    run_cmd(
        [
            "task-gate",
            "--task-id",
            task_id,
            "--gate-id",
            "F5_HISTORICAL_REPLAY",
            "--repo",
            repo_name,
            "--",
            *proof_command,
        ],
        env=env,
    )
    run_cmd(["task-checkpoint", "--task-id", task_id, "--next", ""], env=env)
    run_cmd(
        [
            "task-commit",
            "--task-id",
            task_id,
            "--repo",
            repo_name,
            "--message",
            "test(f5): prove historical replay lifecycle",
        ],
        env=env,
    )

    session_after_commit = json.loads(
        run_cmd(["session-start", "--task-id", task_id, "--json"], env=env).stdout
    )
    assert session_after_commit["final_head_status"] == "VALID"
    assert session_after_commit["latest_command_receipt"]["operation"] == "FINAL_HEAD"
    run_cmd(
        [
            "task-checkpoint",
            "--task-id",
            task_id,
            "--status",
            "READY_TO_CLOSE",
            "--phase",
            "closeout",
            "--next",
            "",
        ],
        env=env,
    )
    validation = json.loads(
        run_cmd(["task-close", "--task-id", task_id, "--validate-only", "--json"], env=env).stdout
    )
    assert validation["verdict"] == "PASS"
    run_cmd(["task-close", "--task-id", task_id, "--summary", "F5 replay lifecycle PASS"], env=env)
