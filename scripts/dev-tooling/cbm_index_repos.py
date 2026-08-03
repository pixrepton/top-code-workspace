#!/usr/bin/env python3
"""Call CBM index_repository via stdio MCP."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CBM_ENV = {
    "CBM_ALLOWED_ROOT": "C:/Users/compg/Desktop/top-code workspace",
    "CBM_CACHE_DIR": "C:/ai-os-codebase-memory",
}


def send(proc: subprocess.Popen[str], payload: dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    proc.stdin.flush()


def read_json_line(proc: subprocess.Popen[str], timeout: float, *, req_id: int | None = None) -> dict[str, Any]:
    assert proc.stdout is not None
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if req_id is not None and payload.get("id") != req_id:
            continue
        return payload
    stderr = ""
    if proc.stderr is not None:
        stderr = proc.stderr.read()[:4000]
    raise TimeoutError(f"no JSON response within {timeout}s; stderr={stderr!r}")


def call_tool(proc: subprocess.Popen[str], tool: str, arguments: dict[str, Any], req_id: int, timeout: float) -> dict[str, Any]:
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    return read_json_line(proc, timeout)


def index_repo(repo_path: Path, *, mode: str | None = None, timeout: float = 3600.0) -> dict[str, Any]:
    exe = Path.home() / ".local" / "bin" / "codebase-memory-mcp.exe"
    if exe.exists():
        command, args = str(exe), []
    else:
        command, args = "uvx", ["--from", "codebase-memory-mcp==0.9.0", "codebase-memory-mcp"]
    env = os.environ.copy()
    env.update(CBM_ENV)
    executable = command
    if not Path(executable).exists():
        executable = shutil.which(command) or command

    proc = subprocess.Popen(
        [executable, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
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
                    "clientInfo": {"name": "cbm-index", "version": "1.0"},
                },
            },
        )
        read_json_line(proc, 120.0, req_id=1)
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        payload: dict[str, Any] = {
            "repo_path": str(repo_path).replace("\\", "/"),
            "mode": mode or "full",
        }
        return call_tool(proc, "index_repository", payload, 2, timeout)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


NESTED_REPOS = (
    "gmail-agent",
    "kalk-top",
    "daszek",
    "cieplo-orchestrator",
    "rag-chat-asystent",
    "rag-widget",
    "top-instal-generator",
    "fast-kalk",
    "knowledge",
    "wp-bridges",
)


def main() -> int:
    workspace = Path(r"C:/Users/compg/Desktop/top-code workspace")
    only = {item.strip() for item in sys.argv[1:] if item.strip()}
    targets: list[tuple[str, Path, str | None]] = []
    if not only or "workspace-root" in only or "workspace" in only:
        targets.append(("workspace-root", workspace, None))
    for name in NESTED_REPOS:
        if only and name not in only:
            continue
        path = workspace / name
        if path.exists():
            targets.append((name, path, None))
        else:
            print(f"SKIP missing: {path}", flush=True)

    results = []
    failures = 0
    for label, path, mode in targets:
        print(f"INDEX {label}: {path}", flush=True)
        t0 = time.perf_counter()
        try:
            resp = index_repo(path, mode=mode)
            elapsed = time.perf_counter() - t0
            entry = {"label": label, "path": str(path), "seconds": round(elapsed, 1), "response": resp}
            results.append(entry)
            is_error = bool(resp.get("result", {}).get("isError"))
            if is_error:
                failures += 1
            print(json.dumps(entry, ensure_ascii=False)[:2000], flush=True)
        except Exception as exc:
            failures += 1
            results.append({"label": label, "path": str(path), "error": str(exc)})
            print(f"ERROR {label}: {exc}", flush=True)
    print(json.dumps({"failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
