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
from ai_os_execution.capabilities import (
    assert_mutate_denies_gmail_send,
    capability_trigger_keys,
    compile_effective_capabilities,
)
from ai_os_execution.semantic_clock import (
    build_semantic_clock,
    require_semantic_clock_ready,
    semantic_env_from_clock,
)
from ai_os_execution.stores import fail_closed_if_canonical_writable, inspect_env_stores
from ai_os_execution.child_env import (
    control_plane_fingerprint,
    provision_hermetic_profile,
    revoke_workload_secrets,
    write_public_env_file,
    write_workload_secrets_file,
)
from ai_os_execution.generation import (
    append_worktree_history,
    bump_lease_generation,
    fencing_token,
    mark_repo_revoked,
)
from ai_os_execution.runtime_profile import (
    record_image_digest,
    require_container_image_provenance,
    uses_container,
)
from ai_os_execution.public_bundle import public_bundle as serialize_public_bundle
from ai_os_execution.worktree import (
    add_repo_worktree,
    generation_worktree_dest,
    remove_repo_worktree,
    task_branch_name,
    worktree_head,
)
from ai_os_task_errors import TaskError
from ai_os_task_git import canonical_repo_path, run
from ai_os_task_paths import utc_now
from ai_os_task_scope import scopes_for_repo


def _source_tree_hash(worktree: Path) -> str:
    proc = run(["git", "rev-parse", "HEAD"], worktree)
    return hashlib.sha256(proc.stdout.strip().encode()).hexdigest()


def _write_env_layers(root: Path, host_env: dict[str, str], container_env: dict[str, str]) -> dict[str, str]:
    public_host = {k: v for k, v in host_env.items() if "://" not in str(v)}
    public_container = {k: v for k, v in container_env.items() if "://" not in str(v)}
    host_path = root / "HOST_ENV.json"
    container_path = root / "CONTAINER_ENV.json"
    host_path.write_text(json.dumps(public_host, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    container_path.write_text(json.dumps(public_container, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "host_env": public_host,
        "container_env": public_container,
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
    hermetic_env = provision_hermetic_profile(root)
    target_repos = data["target_repositories"]
    host_store_rows = inspect_env_stores(
        dict(os.environ),
        execution_mode=execution_mode,
        task_database="",
        task_principal="",
        target_repositories=[],
    )
    fail_closed_if_canonical_writable(host_store_rows, execution_mode=execution_mode)
    assert_scope_leases_free(data["declared_write_scope"])

    repos: dict[str, dict[str, Any]] = {}
    graph: dict[str, Any] = {}
    created_worktrees: list[tuple[str, Path]] = []
    try:
        for repo in data["target_repositories"]:
            canonical = canonical_repo_path(repo)
            base_sha = run(["git", "rev-parse", "--verify", "HEAD"], canonical).stdout.strip()
            branch = task_branch_name(data["task_id"], execution_id, repo, generation=1)
            dest = generation_worktree_dest(root, repo, 1)
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
    capability_profile = str(getattr(args, "capability_profile", None) or "NO_EXTERNAL")
    bundle["seed_origin"] = seed_origin
    bundle["capability_profile"] = capability_profile
    bundle["scratch_path"] = str(scratch)
    bundle["hermetic"] = dict(hermetic_env)
    bundle["fencing_token"] = fencing_token(execution_id, 1)
    bundle["ownership"]["fencing_token"] = bundle["fencing_token"]
    bundle["ownership"]["lease_generation"] = 1

    runtime_profile = str(getattr(args, "runtime_profile", None) or "").strip()
    if not runtime_profile:
        runtime_profile = "container" if isolate_db else "host"
    bundle["runtime"]["profile"] = runtime_profile

    declared_public: dict[str, str] = {
        "AI_OS_EXECUTION_ID": execution_id,
        "AI_OS_TASK_ID": data["task_id"],
        "AI_OS_EXECUTION_MODE": execution_mode,
        "COMPOSE_PROJECT_NAME": docker_namespace(execution_id),
    }
    declared_public.update(hermetic_env)
    workload_secrets: dict[str, str] = {}
    host_db = str(getattr(args, "db_host", None) or os.environ.get("AI_OS_DB_HOST", "") or "127.0.0.1")
    container_db = str(
        getattr(args, "db_container_host", None) or os.environ.get("AI_OS_DB_CONTAINER_HOST", "") or "mailbox-memory-db"
    )
    topology = precheck_host_container_topology(host_side_host=host_db, container_side_host=container_db)
    if not topology["ok"]:
        raise TaskError("HOST/CONTAINER precheck failed: " + "; ".join(topology["errors"]))

    container_env = dict(declared_public)
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
            workload_secrets[key] = db_info["host_dsn"]
            container_env[f"CONTAINER_{key}"] = db_info["container_dsn"]
        workload_secrets["MAILBOX_MEMORY_CANONICAL_DATABASE_URL"] = ""
        container_env["CONTAINER_MAILBOX_MEMORY_CANONICAL_DATABASE_URL"] = ""
    merged_store_env = dict(declared_public)
    merged_store_env.update(workload_secrets)
    capability_env = dict(merged_store_env)
    for key in capability_trigger_keys():
        value = os.environ.get(key, "").strip()
        if value:
            capability_env[key] = value
    store_rows = inspect_env_stores(
        merged_store_env,
        execution_mode=execution_mode,
        task_database=str(db_info.get("database_name") or ""),
        task_principal=str(db_info.get("principal") or ""),
        target_repositories=target_repos,
    )
    fail_closed_if_canonical_writable(store_rows, execution_mode=execution_mode)

    effective_caps = compile_effective_capabilities(
        execution_mode=execution_mode,
        seed_origin=seed_origin,
        capability_profile=capability_profile,
        declared_env=capability_env,
        declared_secrets={},
    )
    assert_mutate_denies_gmail_send(
        execution_mode=execution_mode,
        seed_origin=seed_origin,
        capability_profile=capability_profile,
        declared_env=capability_env,
    )
    bundle["capabilities"] = effective_caps

    semantic_clock = build_semantic_clock(
        seed_origin=seed_origin,
        execution_mode=execution_mode,
        seed_identity=str(db_info.get("seed_identity") or ""),
        replay_as_of=str(getattr(args, "replay_as_of", None) or ""),
        timezone_name=str(getattr(args, "replay_timezone", None) or ""),
        schema_revision=str(getattr(args, "schema_revision", None) or ""),
        evaluator_version=str(getattr(args, "evaluator_version", None) or ""),
        fixture_hash=str(getattr(args, "fixture_hash", None) or ""),
        scoring_paths_proven=bool(getattr(args, "scoring_paths_proven", False)),
    )
    if seed_origin == "HISTORICAL_REPLAY":
        require_semantic_clock_ready(semantic_clock)
    bundle["semantic_clock"] = semantic_clock
    declared_public.update(semantic_env_from_clock(semantic_clock))
    bundle["database"] = {
        key: value
        for key, value in db_info.items()
        if key not in {"password", "host_dsn", "container_dsn"}
    }
    bundle["database"]["control_plane_fingerprint"] = control_plane_fingerprint(
        admin_url=admin_url if isolate_db else "",
        docker_container=os.environ.get("AI_OS_EXECUTION_DB_CONTAINER", "").strip() if isolate_db else "",
        admin_user=os.environ.get("AI_OS_EXECUTION_DB_ADMIN_USER", "").strip() if isolate_db else "",
    )

    capabilities = collect_tool_capabilities(host_db_host=host_db, container_db_host=container_db)
    preflight = write_preflight(
        execution_id,
        capabilities,
        topology,
        graph,
        store_rows,
        effective_capabilities=effective_caps,
        semantic_clock=semantic_clock,
    )
    require_preflight_pass(preflight)
    image_digest = str(getattr(args, "image_digest", None) or "").strip()
    image_repo = str(getattr(args, "image_repo", None) or (target_repos[0] if target_repos else "")).strip()
    if image_digest and image_repo:
        record_image_digest(
            bundle,
            repo=image_repo,
            digest=image_digest,
            source_sha=str((bundle["repos"].get(image_repo) or {}).get("current_sha") or ""),
            worktree_clean_at_build=True,
        )
    if uses_container(runtime_profile):
        require_container_image_provenance(bundle)
    bundle["tooling"] = {
        "preflight_manifest": preflight["preflight_path"],
        "graph_freshness": graph,
    }

    env_layers = _write_env_layers(root, declared_public, container_env)
    bundle["environment_manifest_hash"] = env_layers["hash"]
    write_public_env_file(execution_id, declared_public)
    if workload_secrets:
        write_workload_secrets_file(execution_id, workload_secrets)

    owned_paths = [f"{item['repo']}:{item['path']}" for item in data["declared_write_scope"]]
    if mutation_mode == "MUTATE":
        first_repo = data["target_repositories"][0]
        lease = acquire_lease(
            task_id=data["task_id"],
            execution_id=execution_id,
            repo=first_repo,
            owned_paths=owned_paths,
            lease_generation=1,
        )
        bundle["ownership"] = {
            "lease_id": lease["lease_id"],
            "owned_paths": owned_paths,
            "expires_at": lease["expires_at"],
            "lease_generation": 1,
            "fencing_token": bundle["fencing_token"],
        }
    else:
        bundle["ownership"] = {
            "lease_id": "",
            "owned_paths": owned_paths,
            "expires_at": "",
            "lease_generation": 1,
            "fencing_token": bundle["fencing_token"],
        }

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
        "execution_bundle": serialize_public_bundle(bundle),
        "worktrees": {name: entry.get("worktree_path") for name, entry in bundle["repos"].items()},
        "heads": {name: entry.get("current_sha") for name, entry in bundle["repos"].items()},
        "owned_paths": (bundle.get("ownership") or {}).get("owned_paths") or [],
        "runtime": bundle.get("runtime") or {},
        "latest_valid_proof": proof.get("verdict") if proof else "",
        "current_first_divergence": (bundle.get("benchmark") or {}).get("first_divergence") or "",
        "next_action": "",
        "task_entry": str(execution_dir(bundle["execution_id"]) / "TASK_ENTRY.md"),
    }


def takeover_execution(task_id: str) -> dict[str, Any]:
    """Bump lease generation and provision fresh physical worktrees (F3)."""
    bundle = load_bundle_for_task(task_id)
    if not bundle:
        raise TaskError(f"no execution bundle for task {task_id}")
    if bundle.get("status") not in {"ACTIVE"}:
        raise TaskError(f"takeover requires ACTIVE bundle, got {bundle.get('status')}")

    execution_id = bundle["execution_id"]
    root = execution_dir(execution_id)
    generation = bump_lease_generation(bundle)
    mutation_mode = "READ_ONLY" if bundle.get("execution_mode") == "LIVE_READ_ONLY" else "MUTATE"
    owned_paths = list((bundle.get("ownership") or {}).get("owned_paths") or [])
    first_repo = next(iter((bundle.get("repos") or {}).keys()), "")
    created: list[tuple[str, Path]] = []
    revoked_entries: dict[str, dict[str, Any]] = {}

    try:
        for repo, entry in list((bundle.get("repos") or {}).items()):
            if str(entry.get("worktree_status") or "ACTIVE") != "ACTIVE":
                continue
            revoked = mark_repo_revoked(entry, generation=generation - 1)
            append_worktree_history(bundle, repo, revoked)
            revoked_entries[repo] = revoked

            canonical = canonical_repo_path(repo)
            base_sha = run(["git", "rev-parse", "--verify", "HEAD"], canonical).stdout.strip()
            branch = task_branch_name(task_id, execution_id, repo, generation=generation)
            dest = generation_worktree_dest(root, repo, generation)
            added = add_repo_worktree(repo=repo, dest=dest, branch=branch, base_sha=base_sha)
            created.append((repo, dest))
            bundle["repos"][repo] = empty_repo_entry(
                canonical_repo=str(canonical),
                worktree_path=added["worktree_path"],
                base_sha=base_sha,
                current_sha=added["current_sha"],
                branch=added["branch"],
                mutation_mode=mutation_mode,
                lease_generation=generation,
                worktree_status="ACTIVE",
            )
    except Exception:
        for repo, dest in created:
            try:
                remove_repo_worktree(repo, dest, force=True)
            except TaskError:
                pass
        raise

    for repo, revoked in revoked_entries.items():
        bundle.setdefault("revoked_worktrees", {})[repo] = revoked

    if mutation_mode == "MUTATE" and first_repo and owned_paths:
        lease = acquire_lease(
            task_id=task_id,
            execution_id=execution_id,
            repo=first_repo,
            owned_paths=owned_paths,
            takeover=True,
            lease_generation=generation,
        )
        bundle["ownership"]["lease_id"] = lease["lease_id"]
        bundle["ownership"]["expires_at"] = lease["expires_at"]
    bundle["ownership"]["lease_generation"] = generation
    bundle["ownership"]["fencing_token"] = bundle["fencing_token"]
    from ai_os_execution.tainted import clear_tainted

    clear_tainted(bundle)
    bundle["final_head"] = {
        **(bundle.get("final_head") or {}),
        "required": True,
        "valid": False,
        "gate_id": "FINAL_HEAD_GATE",
        "invalidated_reason": f"takeover generation {generation}",
    }
    save_bundle(bundle)
    state = generate_campaign_state(current_task_id=task_id, current_program=bundle.get("campaign_id") or "")
    write_task_entry(bundle, campaign=state)
    return {
        "task_id": task_id,
        "execution_id": execution_id,
        "lease_generation": generation,
        "fencing_token": bundle["fencing_token"],
        "worktrees": {name: entry.get("worktree_path") for name, entry in bundle["repos"].items()},
        "revoked_worktrees": {name: entry.get("worktree_path") for name, entry in revoked_entries.items()},
    }


def close_execution(task_id: str) -> dict[str, Any]:
    """Retain evidence; revoke workload secrets and release leases."""
    bundle = load_bundle_for_task(task_id)
    if not bundle:
        raise TaskError(f"no execution bundle for task {task_id}")
    removed = revoke_workload_secrets(bundle["execution_id"])
    release_leases(bundle["execution_id"])
    bundle["status"] = "CLOSED_RETAINED"
    bundle["secrets_revoked_at"] = utc_now()
    save_bundle(bundle)
    return {
        "execution_id": bundle["execution_id"],
        "status": bundle["status"],
        "secrets_removed": removed,
    }


def destroy_execution(task_id: str, *, retain_evidence: bool = True) -> dict[str, Any]:
    bundle = load_bundle_for_task(task_id)
    if not bundle:
        raise TaskError(f"no execution bundle for task {task_id}")
    removed = revoke_workload_secrets(bundle["execution_id"])
    release_leases(bundle["execution_id"])
    for name, entry in (bundle.get("repos") or {}).items():
        if str(entry.get("worktree_status") or "ACTIVE") == "ACTIVE":
            dest = Path(entry.get("worktree_path") or "")
            if dest.exists():
                remove_repo_worktree(name, dest, force=True)
    for name, entry in (bundle.get("revoked_worktrees") or {}).items():
        dest = Path(entry.get("worktree_path") or "")
        if dest.exists():
            try:
                remove_repo_worktree(name, dest, force=True)
            except TaskError:
                pass
    bundle["status"] = "CLOSED_RETAINED" if retain_evidence else "DESTROYABLE"
    bundle["secrets_revoked_at"] = utc_now()
    save_bundle(bundle)
    return {
        "execution_id": bundle["execution_id"],
        "status": bundle["status"],
        "secrets_removed": removed,
    }

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
