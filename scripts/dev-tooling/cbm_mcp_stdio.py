#!/usr/bin/env python3
"""Shared stdio JSON-RPC client for the Codebase Memory MCP server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CBM_ENV = {
    "CBM_ALLOWED_ROOT": "C:/Users/compg/Desktop/top-code workspace",
    "CBM_CACHE_DIR": "C:/ai-os-codebase-memory",
}
CBM_EXE = Path.home() / ".local" / "bin" / "codebase-memory-mcp.exe"
CBM_UVX_ARGS = ["--from", "codebase-memory-mcp==0.9.0", "codebase-memory-mcp"]
PROTOCOL_VERSION = "2024-11-05"


def resolve_cbm_launch() -> tuple[str, list[str]]:
    if CBM_EXE.exists():
        return str(CBM_EXE), []
    return "uvx", CBM_UVX_ARGS


def resolve_executable(command: str) -> str:
    """Resolve a launcher to something Popen can execute on this platform."""
    if Path(command).exists():
        return command
    found = shutil.which(command)
    if found:
        return found
    if os.name == "nt":
        return shutil.which(f"{command}.cmd") or command
    return command


def spawn_cbm(cwd: Path) -> subprocess.Popen[str]:
    command, args = resolve_cbm_launch()
    env = os.environ.copy()
    env.update(CBM_ENV)
    return subprocess.Popen(
        [resolve_executable(command), *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        cwd=str(cwd),
    )


def shutdown(proc: subprocess.Popen[str], timeout: float) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()


def list_index_files() -> list[dict[str, Any]]:
    cache = Path(CBM_ENV["CBM_CACHE_DIR"])
    rows: list[dict[str, Any]] = []
    if not cache.exists():
        return rows
    for path in sorted(cache.glob("*.db")):
        if path.name.endswith(("-shm", "-wal")):
            continue
        rows.append(
            {
                "name": path.name,
                "mb": round(path.stat().st_size / (1024 * 1024), 2),
                "mtime": path.stat().st_mtime,
            }
        )
    return sorted(rows, key=lambda row: row["mb"], reverse=True)


class McpStdioSession:
    """Line-delimited JSON-RPC over the MCP server's stdin/stdout."""

    def __init__(self, proc: subprocess.Popen[str], *, poll_interval: float = 0.05) -> None:
        self.proc = proc
        self.poll_interval = poll_interval
        self._next_id = 0

    def send(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def _drain_stderr(self) -> str:
        if self.proc.stderr is None:
            return ""
        try:
            return self.proc.stderr.read()[:4000]
        except Exception:
            return ""

    def read_json_line(self, timeout: float, req_id: int | None = None) -> dict[str, Any]:
        assert self.proc.stdout is not None
        start = time.perf_counter()
        while time.perf_counter() - start < timeout:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    break
                time.sleep(self.poll_interval)
                continue
            payload = self._decode(line)
            if payload is None:
                continue
            if req_id is not None and payload.get("id") != req_id:
                continue
            return payload
        raise TimeoutError(f"no JSON response within {timeout}s; stderr={self._drain_stderr()!r}")

    @staticmethod
    def _decode(line: str) -> dict[str, Any] | None:
        stripped = line.strip()
        if not stripped:
            return None
        return json.loads(stripped)

    def request(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        self._next_id += 1
        req_id = self._next_id
        self.send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return self.read_json_line(timeout, req_id)

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
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self, timeout: float) -> dict[str, Any]:
        return self.request("tools/list", {}, timeout)

    def call_tool(self, tool: str, arguments: dict[str, Any], timeout: float) -> dict[str, Any]:
        return self.request("tools/call", {"name": tool, "arguments": arguments}, timeout)


@contextmanager
def cbm_session(*, poll_interval: float = 0.05, shutdown_timeout: float = 3.0) -> Iterator[McpStdioSession]:
    proc = spawn_cbm(ROOT)
    try:
        yield McpStdioSession(proc, poll_interval=poll_interval)
    finally:
        shutdown(proc, shutdown_timeout)
