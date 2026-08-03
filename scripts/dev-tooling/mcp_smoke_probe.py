#!/usr/bin/env python3
"""Minimal MCP stdio smoke probe for local harness verification."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def send(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def read_json_line(proc: subprocess.Popen[str], timeout: float) -> dict[str, Any]:
    assert proc.stdout is not None
    start = time.time()
    while time.time() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        return json.loads(line)
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


def smoke_stdio(command: str, args: list[str], *, env: dict[str, str] | None = None, timeout: float = 45.0) -> dict[str, Any]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    executable = resolve_command(command)
    proc = subprocess.Popen(
        [executable, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged,
        cwd=str(ROOT),
    )
    try:
        send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-smoke-probe", "version": "1.0"},
                },
            },
        )
        init_resp = read_json_line(proc, timeout)
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_resp = read_json_line(proc, timeout)
        tools = tools_resp.get("result", {}).get("tools", [])
        return {
            "ok": bool(tools),
            "server": init_resp.get("result", {}).get("serverInfo", {}),
            "tool_count": len(tools),
            "tool_names": [tool.get("name") for tool in tools[:20]],
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    parser.add_argument("--env", action="append", default=[], help="KEY=VALUE")
    args = parser.parse_args()
    env = {}
    for item in args.env:
        key, value = item.split("=", 1)
        env[key] = value
    result = smoke_stdio(args.command, args.args, env=env or None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
