#!/usr/bin/env python3
"""MCP stdio smoke and read-only proof helpers for local harness verification."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / ".mcp.json"
DEFAULT_ARTIFACT_ROOT = ROOT / ".artifacts" / "tooling-optimization"
DEFAULT_CBM_PROJECT = "C-Users-compg-Desktop-top-code-workspace-gmail-agent"
DEFAULT_SERENA_REPO = ROOT / "gmail-agent"
PROTOCOL_VERSION = "2024-11-05"


def send(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def read_json_line(proc: subprocess.Popen[str], timeout: float, req_id: int | None = None) -> dict[str, Any]:
    assert proc.stdout is not None
    lines: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        line = proc.stdout.readline()
        if line:
            lines.put(line)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        remaining = max(0.0, deadline - time.time())
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            break
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if req_id is not None and payload.get("id") != req_id:
            continue
        return payload
    raise TimeoutError("no JSON response from MCP server")


def resolve_command(command: str) -> str:
    if os.path.isabs(command) or Path(command).exists():
        return command
    resolved = shutil.which(command)
    if resolved:
        return resolved
    if os.name == "nt" and not command.lower().endswith(".cmd"):
        resolved = shutil.which(f"{command}.cmd")
        if resolved:
            return resolved
    return command


def spawn_stdio(
    command: str,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.Popen[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.Popen(
        [resolve_command(command), *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged,
        cwd=str(cwd or ROOT),
    )


class McpSession:
    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc
        self.next_id = 0

    def request(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.next_id += 1
        req_id = self.next_id
        send(self.proc, {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return read_json_line(self.proc, timeout, req_id)

    def initialize(self, client_name: str, timeout: float) -> dict[str, Any]:
        return self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": client_name, "version": "1.0"},
            },
            timeout,
        )

    def notify_initialized(self) -> None:
        send(self.proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self, timeout: float) -> dict[str, Any]:
        return self.request("tools/list", {}, timeout)

    def call_tool(self, name: str, arguments: dict[str, Any], timeout: float) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments}, timeout)


def terminate(proc: subprocess.Popen[str]) -> None:
    if os.name == "nt" and proc.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            text=True,
            capture_output=True,
            check=False,
        )
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def smoke_stdio(
    command: str,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 45.0,
    cwd: Path | None = None,
) -> dict[str, Any]:
    proc = spawn_stdio(command, args, env=env, cwd=cwd)
    try:
        session = McpSession(proc)
        init_resp = session.initialize("mcp-smoke-probe", timeout)
        session.notify_initialized()
        tools_resp = session.list_tools(timeout)
        tools = tools_resp.get("result", {}).get("tools", [])
        return {
            "ok": bool(tools),
            "server": init_resp.get("result", {}).get("serverInfo", {}),
            "tool_count": len(tools),
            "tool_names": [tool.get("name") for tool in tools[:20]],
        }
    finally:
        terminate(proc)


def safe_json(value: Any, limit: int = 4000) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return {"truncated": True, "chars": len(text), "prefix": text[:limit]}


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def server_config(path: Path, name: str) -> dict[str, Any]:
    config = load_config(path)
    servers = config.get("mcpServers", {})
    if name not in servers:
        raise KeyError(f"MCP server not configured: {name}")
    server = servers[name]
    if "command" not in server:
        raise KeyError(f"MCP server has no stdio command: {name}")
    return server


def git_head(repo: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=str(repo),
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def tool_names(tools_resp: dict[str, Any]) -> list[str]:
    tools = tools_resp.get("result", {}).get("tools", [])
    return [str(tool.get("name")) for tool in tools if tool.get("name")]


def call_if_present(
    session: McpSession,
    names: set[str],
    tool: str,
    arguments: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    if tool not in names:
        return {"tool": tool, "status": "TOOL_NOT_LISTED"}
    try:
        resp = session.call_tool(tool, arguments, timeout)
    except Exception as exc:  # noqa: BLE001 - proof artifact records the failure
        return {"tool": tool, "status": "CALL_FAILED", "error": str(exc)}
    status = "CALL_OK"
    if "error" in resp:
        status = "CALL_ERROR"
    if resp.get("result", {}).get("isError"):
        status = "CALL_RESULT_ERROR"
    return {"tool": tool, "status": status, "response": safe_json(resp)}


def cbm_probe(session: McpSession, names: set[str], project: str) -> dict[str, Any]:
    schema = call_if_present(session, names, "get_graph_schema", {"project": project}, 60.0)
    search_tool = "search_code" if "search_code" in names else "search_graph"
    query_key = "pattern" if search_tool == "search_code" else "search_query"
    search = call_if_present(
        session,
        names,
        search_tool,
        {"project": project, query_key: "CaseContextPack", "limit": 5},
        60.0,
    )
    return {
        "project": project,
        "repo_head": git_head(ROOT / "gmail-agent"),
        "calls": [schema, search],
    }


def gitnexus_probe(session: McpSession, names: set[str]) -> dict[str, Any]:
    repos = call_if_present(session, names, "list_repos", {}, 60.0)
    query = call_if_present(
        session,
        names,
        "query",
        {"repo": "gmail-agent", "search_query": "CaseContextPack"},
        60.0,
    )
    return {"calls": [repos, query], "workspace_head": git_head(ROOT)}


def serena_probe(session: McpSession, names: set[str]) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    calls.append(call_if_present(session, names, "initial_instructions", {}, 120.0))
    calls.append(
        call_if_present(
            session,
            names,
            "find_symbol",
            {
                "name_path_pattern": "CaseContextPack",
                "relative_path": "tools/gmail_audit",
                "include_body": False,
                "max_matches": 5,
            },
            120.0,
        )
    )
    return {"repo": str(DEFAULT_SERENA_REPO), "repo_head": git_head(DEFAULT_SERENA_REPO), "calls": calls}


def proof_status(probe: dict[str, Any]) -> str:
    if probe.get("status") != "TOOL_LISTED":
        return "NOT_PROVEN"
    calls = probe.get("read_only_calls", {}).get("calls", [])
    if not calls:
        return "TOOL_CALL_PROVEN"
    bad = [call for call in calls if call.get("status") not in {"CALL_OK"}]
    return "TOOL_CALL_PROVEN" if not bad else "PARTIAL"


def run_configured_probe(
    name: str,
    config_path: Path,
    *,
    cbm_project: str,
    timeout: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "server_name": name,
        "configured": False,
        "status": "CONFIG_MISSING",
    }
    try:
        server = server_config(config_path, name)
    except Exception as exc:  # noqa: BLE001 - proof artifact records the failure
        result["error"] = str(exc)
        return result

    result["configured"] = True
    result["status"] = "CONFIGURED"
    command = str(server["command"])
    args = [str(item) for item in server.get("args", [])]
    env = {str(key): str(value) for key, value in (server.get("env") or {}).items()}
    cwd = DEFAULT_SERENA_REPO if name == "serena" else ROOT
    proc = spawn_stdio(command, args, env=env, cwd=cwd)
    try:
        session = McpSession(proc)
        init_resp = session.initialize(f"mcp-proof-{name}", timeout)
        session.notify_initialized()
        tools_resp = session.list_tools(timeout)
        names = set(tool_names(tools_resp))
        result.update(
            {
                "status": "TOOL_LISTED" if names else "NO_TOOLS",
                "server": init_resp.get("result", {}).get("serverInfo", {}),
                "tool_count": len(names),
                "tool_names": sorted(names),
            }
        )
        if name == "codebase-memory":
            result["read_only_calls"] = cbm_probe(session, names, cbm_project)
        elif name == "gitnexus":
            result["read_only_calls"] = gitnexus_probe(session, names)
        elif name == "serena":
            result["read_only_calls"] = serena_probe(session, names)
    except Exception as exc:  # noqa: BLE001 - proof artifact records the failure
        result["status"] = "CALL_FAILED"
        result["error"] = str(exc)
    finally:
        terminate(proc)
    result["proof_status"] = proof_status(result)
    return result


def timestamp_dir(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return root / stamp


def tooling_proof_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run read-only MCP proof and write an artifact.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--cbm-project", default=DEFAULT_CBM_PROJECT)
    parser.add_argument("--include-serena", action="store_true")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    output_dir = Path(args.output_dir) if args.output_dir else timestamp_dir(DEFAULT_ARTIFACT_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    servers = ["codebase-memory", "gitnexus"]
    if args.include_serena:
        servers.append("serena")
    payload = {
        "schema": "aios.tooling.mcp-proof.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "evidence_model": {
            "configured": "server exists in MCP config",
            "tool_listed": "stdio initialize plus tools/list returned tool names",
            "tool_call_proven": "at least one read-only domain call succeeded",
            "runtime_truth": False,
        },
        "servers": [
            run_configured_probe(
                name,
                config_path,
                cbm_project=args.cbm_project,
                timeout=args.timeout,
            )
            for name in servers
        ],
    }
    payload["summary"] = {
        item["server_name"]: item.get("proof_status", item.get("status"))
        for item in payload["servers"]
    }
    target = output_dir / "mcp-proof.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"artifact": str(target), "summary": payload["summary"]}, ensure_ascii=False, indent=2))
    return 0 if all(status == "TOOL_CALL_PROVEN" for status in payload["summary"].values()) else 1


def legacy_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parser.add_argument("--env", action="append", default=[], help="KEY=VALUE")
    args = parser.parse_args(argv)
    env = {}
    for item in args.env:
        key, value = item.split("=", 1)
        env[key] = value
    result = smoke_stdio(args.command, args.args, env=env or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    actual = list(sys.argv[1:] if argv is None else argv)
    if actual and actual[0] == "proof":
        return tooling_proof_main(actual[1:])
    return legacy_main(actual)


if __name__ == "__main__":
    raise SystemExit(main())
