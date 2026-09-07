"""Provision, resume, and destroy a Task Execution Bundle using the existing task engine."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ai_os_execution.bundle import (
    configured_worktree_path,
    docker_namespace,
    empty_repo_entry,
    execution_dir,
    load_active_bundle,
    load_bundle,
    load_bundle_for_task,
    new_bundle,
    new_execution_id,
    save_bundle,
)
from ai_os_execution.campaign import generate_campaign_state, write_task_entry
from ai_os_execution.database import admin_url_from_env, provision_isolated_database
from ai_os_execution.lease import acquire_lease, assert_scope_leases_free, heartbeat_lease, release_leases
from ai_os_execution.preflight import (
    collect_tool_capabilities,
    graph_freshness_for_repo,
    precheck_host_container_topology,
    require_preflight_pass,
    write_preflight,
)
from ai_os_execution.stores import fail_closed_if_canonical_writable, inspect_env_stores
from ai_os_execution.worktree import add_repo_worktree, remove_repo_worktree, task_branch_name, worktree_head
from ai_os_task_errors import TaskError
from ai_os_task_git import canonical_repo_path, run
from ai_os_task_paths import utc_now
from ai_os_task_scope import scopes_for_repo


def _source_tree_hash(worktree: Path) -> str:
    proc = run(["git", "rev-parse", "HEAD"], worktree)
    return hashlib.sha256(proc.stdout.strip().encode()).hexdigest()


def _write_env_layers(root: Path, host_env: dict[str, str], container_env: dict[str, str]) -> dict[str, str]:
    host_path = root / "HOST_ENV.json"
    container_path = root / "CONTAINER_ENV.json"
    host_path.write_text(json.dumps(host_env, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    container_path.write_text(json.dumps(container_env, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "host_env": host_env,
        "container_env": container_env,
        "created_at": utc_now(),
    }
    manifest_path = root / "ENVIRONMENT_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "host_env": str(host_path),
        "container_env": str(container_path),
        "manifest": str(manifest_path),
        "hash": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }


def provision_execution(data: dict[str, Any], args: Any) -> dict[str, Any]:
    execution_mode = str(getattr(args, "execution_mode", None) or "TEST")
    seed_origin = str(getattr(args, "seed_origin", None) or "EMPTY")
    mutation_mode = "READ_ONLY" if execution_mode == "LIVE_READ_ONLY" else "MUTATE"
    raw_db = getattr(args, "db_isolation", None)
    isolate_db = True if raw_db is None else bool(raw_db)
    now = utc_now()
    execution_id = new_execution_id(now)
    os.environ["AI_OS_EXECUTION_ID"] = execution_id
    os.environ["AI_OS_TASK_ID"] = data["task_id"]
    root = execution_dir(execution_id)
    root.mkdir(parents=True, exist_ok=True)
    scratch = root / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    assert_scope_leases_free(data["declared_write_scope"])

    repos: dict[str, dict[str, Any]] = {}
    graph: dict[str, Any] = {}
    created_worktrees: list[tuple[str, Path]] = []
    try:
        for repo in data["target_repositories"]:
            canonical = canonical_repo_path(repo)
            base_sha = run(["git", "rev-parse", "--verify", "HEAD"], canonical).stdout.strip()
            branch = task_branch_name(data["task_id"], execution_id, repo)
            dest = root / "worktrees" / repo
            created = add_repo_worktree(repo=repo, dest=dest, branch=branch, base_sha=base_sha)
            created_worktrees.append((repo, dest))
            repos[repo] = empty_repo_entry(
                canonical_repo=str(canonical),
                worktree_path=created["worktree_path"],
                base_sha=base_sha,
                current_sha=created["current_sha"],
                branch=created["branch"],
                mutation_mode=mutation_mode,
            )
            graph[repo] = graph_freshness_for_repo(canonical, base_sha)
    except Exception:
        for repo, dest in created_worktrees:
            try:
                remove_repo_worktree(repo, dest, force=True)
            except TaskError:
                pass
        raise

    bundle = new_bundle(
        execution_id=execution_id,
        task_id=data["task_id"],
        campaign_id=str(getattr(args, "campaign_id", None) or data["task_id"]),
        repos=repos,
        execution_mode=execution_mode,
        now=now,
    )
    bundle["scratch_path"] = str(scratch)

    host_db = str(getattr(args, "db_host", None) or os.environ.get("AI_OS_DB_HOST", "") or "127.0.0.1")
    container_db = str(
        getattr(args, "db_container_host", None) or os.environ.get("AI_OS_DB_CONTAINER_HOST", "") or "mailbox-memory-db"
    )
    topology = precheck_host_container_topology(host_side_host=host_db, container_side_host=container_db)
    if not topology["ok"]:
        raise TaskError("HOST/CONTAINER precheck failed: " + "; ".join(topology["errors"]))

    host_env: dict[str, str] = {
        "AI_OS_EXECUTION_ID": execution_id,
        "AI_OS_TASK_ID": data["task_id"],
        "AI_OS_EXECUTION_MODE": execution_mode,
        "COMPOSE_PROJECT_NAME": docker_namespace(execution_id),
    }
    container_env = dict(host_env)
    db_info: dict[str, Any] = {
        "isolation_mode": "NONE",
        "database_name": "",
        "principal": "",
        "seed_identity": "",
        "seed_hash": "",
        "seed_origin": seed_origin,
        "database_host": {"host": host_db, "container": container_db},
    }
    if isolate_db:
        admin_url = admin_url_from_env()
        docker_container = os.environ.get("AI_OS_EXECUTION_DB_CONTAINER", "").strip()
        if not admin_url and not docker_container:
            raise TaskError(
                "execution-plane DB isolation requested but no admin channel; "
                "set AI_OS_EXECUTION_ADMIN_DATABASE_URL or AI_OS_EXECUTION_DB_CONTAINER"
            )
        db_info = provision_isolated_database(
            execution_id=execution_id,
            execution_mode=execution_mode,
            seed_origin=seed_origin,
            admin_url=admin_url,
            docker_container=docker_container,
            host_side_host=host_db,
            container_side_host=container_db,
            port=str(getattr(args, "db_port", None) or os.environ.get("MAILBOX_MEMORY_PG_PORT") or "54129"),
        )
        for key in ("MAILBOX_MEMORY_DATABASE_URL", "MAILBOX_MEMORY_ASOF_DATABASE_URL", "DATABASE_URL"):
            host_env[key] = db_info["host_dsn"]
            container_env[key] = db_info["container_dsn"]
        host_env["MAILBOX_MEMORY_CANONICAL_DATABASE_URL"] = ""
        container_env["MAILBOX_MEMORY_CANONICAL_DATABASE_URL"] = ""
    merged_store_env = dict(os.environ)
    merged_store_env.update(host_env)
    store_rows = inspect_env_stores(
        merged_store_env,
        execution_mode=execution_mode,
        task_database=str(db_info.get("database_name") or ""),
        task_principal=str(db_info.get("principal") or ""),
    )
    fail_closed_if_canonical_writable(store_rows, execution_mode=execution_mode)
    bundle["database"] = {
        key: value
        for key, value in db_info.items()
        if key not in {"password", "host_dsn", "container_dsn"}
    }

    capabilities = collect_tool_capabilities(host_db_host=host_db, container_db_host=container_db)
    preflight = write_preflight(execution_id, capabilities, topology, graph, store_rows)
    require_preflight_pass(preflight)
    bundle["tooling"] = {
        "preflight_manifest": preflight["preflight_path"],
        "graph_freshness": graph,
    }

    env_layers = _write_env_layers(root, host_env, container_env)
    bundle["environment_manifest_hash"] = env_layers["hash"]
    secrets_path = root / "task.env.secret"
    if isolate_db:
        secrets_path.write_text(
            "\n".join(f"{key}={value}" for key, value in host_env.items() if "URL" in key) + "\n",
            encoding="utf-8",
        )

    owned_paths = [f"{item['repo']}:{item['path']}" for item in data["declared_write_scope"]]
    if mutation_mode == "MUTATE":
        first_repo = data["target_repositories"][0]
        lease = acquire_lease(
            task_id=data["task_id"],
            execution_id=execution_id,
            repo=first_repo,
            owned_paths=owned_paths,
        )
        bundle["ownership"] = {
            "lease_id": lease["lease_id"],
            "owned_paths": owned_paths,
            "expires_at": lease["expires_at"],
        }
    else:
        bundle["ownership"] = {"lease_id": "", "owned_paths": owned_paths, "expires_at": ""}

    save_bundle(bundle)
    write_task_entry(
        bundle,
        goal=str(data.get("task_title") or ""),
        owned_paths=owned_paths,
        stop_conditions=[
            "Do not mutate product behavior outside owned paths.",
            "Do not use canonical writable DB credentials.",
            "Do not treat historical plans/transcripts as active instructions.",
            "FINAL_HEAD_GATE is required after the last commit before task-close.",
        ],
        references=[
            "HISTORICAL_CONTEXT: older Cursor/Codex plans and transcripts",
            "knowledge/system-atlas/tooling/EXECUTION_PLANE_V1.md",
        ],
    )
    generate_campaign_state(current_task_id=data["task_id"], current_program=bundle["campaign_id"])
    return bundle


def refresh_bundle_heads(bundle: dict[str, Any]) -> dict[str, Any]:
    for name, entry in (bundle.get("repos") or {}).items():
        path = Path(entry["worktree_path"])
        if path.exists():
            entry["current_sha"] = worktree_head(path)
            entry["branch"] = run(["git", "branch", "--show-current"], path).stdout.strip()
    save_bundle(bundle)
    return bundle


def resume_execution(task_id: str) -> dict[str, Any]:
    bundle = load_bundle_for_task(task_id)
    if not bundle:
        raise TaskError(f"no execution bundle for task {task_id}")
    os.environ["AI_OS_EXECUTION_ID"] = bundle["execution_id"]
    os.environ["AI_OS_TASK_ID"] = task_id
    heartbeat_lease(bundle["execution_id"])
    bundle = refresh_bundle_heads(bundle)
    proof = {}
    proof_path = execution_dir(bundle["execution_id"]) / "PROOF_BUNDLE.json"
    if proof_path.exists():
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    generate_campaign_state(current_task_id=task_id, current_program=bundle.get("campaign_id") or "")
    return {
        "status": "RESUMED",
        "task_id": task_id,
        "execution_id": bundle["execution_id"],
        "execution_bundle": _public_bundle(bundle),
        "worktrees": {name: entry.get("worktree_path") for name, entry in bundle["repos"].items()},
        "heads": {name: entry.get("current_sha") for name, entry in bundle["repos"].items()},
        "owned_paths": (bundle.get("ownership") or {}).get("owned_paths") or [],
        "runtime": bundle.get("runtime") or {},
        "latest_valid_proof": proof.get("verdict") if proof else "",
        "current_first_divergence": (bundle.get("benchmark") or {}).get("first_divergence") or "",
        "next_action": "",
        "task_entry": str(execution_dir(bundle["execution_id"]) / "TASK_ENTRY.md"),
    }


def destroy_execution(task_id: str, *, retain_evidence: bool = True) -> dict[str, Any]:
    bundle = load_bundle_for_task(task_id)
    if not bundle:
        raise TaskError(f"no execution bundle for task {task_id}")
    release_leases(bundle["execution_id"])
    for name, entry in (bundle.get("repos") or {}).items():
        dest = Path(entry.get("worktree_path") or "")
        if dest.exists():
            remove_repo_worktree(name, dest, force=True)
    bundle["status"] = "CLOSED_RETAINED" if retain_evidence else "DESTROYABLE"
    save_bundle(bundle)
    return {"execution_id": bundle["execution_id"], "status": bundle["status"]}


def _public_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(bundle))
    db = clone.get("database") or {}
    for key in ("password", "host_dsn", "container_dsn"):
        db.pop(key, None)
    clone["database"] = db
    return clone


def print_task_ready(bundle: dict[str, Any]) -> None:
    print("TASK READY")
    print(f"task_id: {bundle['task_id']}")
    print(f"execution_id: {bundle['execution_id']}")
    print(f"mode: {bundle.get('execution_mode')}")
    print(f"scratch: {bundle.get('scratch_path')}")
    print(f"runtime_namespace: {(bundle.get('runtime') or {}).get('namespace')}")
    db = bundle.get("database") or {}
    print(f"db: {db.get('isolation_mode')} {db.get('database_name')} principal={db.get('principal')}")
    for name, entry in (bundle.get("repos") or {}).items():
        print(f"worktree[{name}]: {entry.get('worktree_path')} {entry.get('current_sha')}")
    print(f"entry: {execution_dir(bundle['execution_id']) / 'TASK_ENTRY.md'}")
