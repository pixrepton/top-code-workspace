"""Environment preflight: tool capabilities, graph freshness, host/container topology."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ai_os_execution import GRAPH_STATUSES
from ai_os_execution.bundle import atomic_json, execution_dir
from ai_os_task_constants import WORKSPACE
from ai_os_task_errors import TaskError
from ai_os_task_paths import utc_now


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True)


def _version(args: list[str]) -> dict[str, Any]:
    executable = shutil.which(args[0])
    if not executable:
        return {"available": False, "executable": "", "version": "", "error": f"{args[0]} not on PATH"}
    proc = _run(args)
    text = ((proc.stdout or proc.stderr or "").strip().splitlines() or [""])[0]
    return {
        "available": proc.returncode == 0,
        "executable": executable,
        "version": text,
        "error": "" if proc.returncode == 0 else (proc.stderr or proc.stdout or "").strip()[:300],
    }


def graph_freshness_for_repo(repo_path: Path, repo_sha: str) -> dict[str, Any]:
    """Machine-readable graph status. Never requires the agent to narrate commit lag."""
    index_sha = ""
    status = "UNAVAILABLE"
    gitnexus_meta = repo_path / ".gitnexus" / "meta.json"
    workspace_gitnexus = WORKSPACE / ".gitnexus" / "meta.json"
    for candidate in (gitnexus_meta, workspace_gitnexus):
        if not candidate.exists():
            continue
        try:
            meta = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        index_sha = str(meta.get("lastCommit") or meta.get("commit") or meta.get("head") or "")
        break
    env_index = os.environ.get("AI_OS_GRAPH_INDEX_SHA", "").strip()
    if env_index:
        index_sha = env_index
    if index_sha and repo_sha:
        status = "CURRENT" if index_sha == repo_sha else "STALE_ADVISORY"
    elif not index_sha:
        status = "UNAVAILABLE"
    if status not in GRAPH_STATUSES:
        status = "UNAVAILABLE"
    return {
        "repo_sha": repo_sha,
        "index_sha": index_sha,
        "status": status,
    }


def collect_tool_capabilities(
    *,
    host_db_host: str = "127.0.0.1",
    container_db_host: str = "mailbox-memory-db",
    mcp_required: list[str] | None = None,
) -> dict[str, Any]:
    powershell = _version(["powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"])
    convert_from_json = False
    if powershell.get("available"):
        probe = _run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "try { '{}' | ConvertFrom-Json | Out-Null; 'yes' } catch { 'no' }",
            ]
        )
        convert_from_json = (probe.stdout or "").strip() == "yes"
    docker = _version(["docker", "version", "--format", "{{.Server.Version}}"])
    compose = _version(["docker", "compose", "version"])
    postgres = _version(["psql", "--version"])
    git = _version(["git", "--version"])
    mcp_required = mcp_required or ["gitnexus", "codebase-memory", "serena", "codescene"]
    mcp: dict[str, Any] = {}
    cursor_mcp = WORKSPACE / ".cursor" / "mcp.json"
    declared: set[str] = set()
    if cursor_mcp.exists():
        try:
            payload = json.loads(cursor_mcp.read_text(encoding="utf-8"))
            declared = {str(name).lower() for name in (payload.get("mcpServers") or {})}
        except json.JSONDecodeError:
            declared = set()
    for name in mcp_required:
        mcp[name] = {
            "declared": name.lower() in declared or any(name.lower() in item for item in declared),
            "required": True,
        }
    return {
        "created_at": utc_now(),
        "powershell": {**powershell, "convert_from_json": convert_from_json},
        "python": {
            "available": True,
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "git": git,
        "docker": docker,
        "compose": compose,
        "postgres": postgres,
        "runtime_hostnames": {
            "host_side": host_db_host,
            "container_side": container_db_host,
        },
        "mcp": mcp,
    }


def precheck_host_container_topology(
    *,
    host_side_host: str,
    container_side_host: str,
    expected_container_host: str = "mailbox-memory-db",
) -> dict[str, Any]:
    errors: list[str] = []
    if not host_side_host:
        errors.append("host-side DB hostname missing")
    if not container_side_host:
        errors.append("container-side DB hostname missing")
    if container_side_host in {"127.0.0.1", "localhost"}:
        errors.append(
            f"container hostname {container_side_host} is a host-loopback address; "
            f"expected {expected_container_host}"
        )
    if host_side_host == expected_container_host:
        errors.append(
            f"host-side hostname {host_side_host} is the container DNS name; expected 127.0.0.1/localhost"
        )
    return {
        "host_side": host_side_host,
        "container_side": container_side_host,
        "ok": not errors,
        "errors": errors,
    }


def write_preflight(
    execution_id: str,
    capabilities: dict[str, Any],
    topology: dict[str, Any],
    graph: dict[str, Any],
    stores: list[dict[str, Any]],
) -> dict[str, str]:
    root = execution_dir(execution_id)
    root.mkdir(parents=True, exist_ok=True)
    capabilities_path = root / "TOOL_CAPABILITIES.json"
    preflight_path = root / "PREFLIGHT.json"
    atomic_json(capabilities, capabilities_path)
    payload = {
        "created_at": utc_now(),
        "capabilities_path": str(capabilities_path),
        "topology": topology,
        "graph_freshness": graph,
        "writable_stores": stores,
        "verdict": "PASS" if topology.get("ok") else "FAIL",
    }
    atomic_json(payload, preflight_path)
    digest = hashlib.sha256(preflight_path.read_bytes()).hexdigest()
    return {
        "capabilities_path": str(capabilities_path),
        "preflight_path": str(preflight_path),
        "preflight_hash": digest,
        "verdict": payload["verdict"],
    }


def require_preflight_pass(preflight: dict[str, str]) -> None:
    if preflight.get("verdict") != "PASS":
        raise TaskError("environment preflight FAIL CLOSED")
