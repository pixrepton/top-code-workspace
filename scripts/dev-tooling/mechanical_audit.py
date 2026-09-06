#!/usr/bin/env python3
"""Read-only mechanical tooling audit for ast-grep, OpenGrep and Promptfoo."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / ".artifacts" / "tooling-optimization"


def run_command(args: list[str], *, timeout: float = 60.0) -> dict[str, Any]:
    started = time.perf_counter()
    resolved = [resolve_command(args[0]), *args[1:]]
    proc = subprocess.run(resolved, cwd=str(ROOT), text=True, capture_output=True, timeout=timeout, check=False)
    return {
        "args": resolved,
        "returncode": proc.returncode,
        "seconds": round(time.perf_counter() - started, 2),
        "stdout": proc.stdout[:4000],
        "stderr": proc.stderr[:4000],
    }


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None or (shutil.which(f"{name}.cmd") is not None)


def resolve_command(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if not name.lower().endswith(".cmd"):
        found = shutil.which(f"{name}.cmd")
        if found:
            return found
    return name


def ast_grep_command() -> list[str]:
    if command_exists("ast-grep"):
        return ["ast-grep"]
    if command_exists("sg"):
        return ["sg"]
    if command_exists("npx"):
        return ["npx", "-y", "-p", "@ast-grep/cli", "ast-grep"]
    return []


def ast_grep_probe() -> dict[str, Any]:
    cmd = ast_grep_command()
    if not cmd:
        return {"tool": "ast-grep", "installed": False, "status": "SKIP_NPX_NOT_AVAILABLE"}
    version = run_command([*cmd, "--version"], timeout=120.0)
    sample = run_command(
        [*cmd, "--pattern", "subprocess.run($$$ARGS)", "--lang", "python", "scripts"],
        timeout=120.0,
    )
    return {
        "tool": "ast-grep",
        "mode": "local-bin" if cmd[0] != "npx" else "npx-cache",
        "installed": version["returncode"] == 0,
        "version": version,
        "sample_read_only_scan": sample,
    }


def opengrep_probe() -> dict[str, Any]:
    if not command_exists("opengrep"):
        return {
            "tool": "opengrep",
            "installed": False,
            "status": "SKIP_NOT_INSTALLED",
            "note": "OpenGrep is intentionally read-only/optional in v1; install separately when SAST rules are needed.",
        }
    version = run_command(["opengrep", "--version"], timeout=60.0)
    return {"tool": "opengrep", "installed": version["returncode"] == 0, "version": version}


def promptfoo_probe() -> dict[str, Any]:
    if not command_exists("npx"):
        return {"tool": "promptfoo", "status": "SKIP_NPX_NOT_AVAILABLE"}
    version = run_command(["npx", "-y", "promptfoo@latest", "--version"], timeout=180.0)
    return {
        "tool": "promptfoo",
        "status": "AVAILABLE_FOR_LLM_BENCHMARKS" if version["returncode"] == 0 else "NOT_PROVEN",
        "version": version,
        "blocks_regular_coding": False,
    }


def write_artifact(payload: dict[str, Any]) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ARTIFACT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "mechanical-tooling-proof.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--include-promptfoo", action="store_true")
    parser.add_argument("--write-artifact", action="store_true")
    args = parser.parse_args()

    payload: dict[str, Any] = {
        "schema": "aios.tooling.mechanical-proof.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "probes": [ast_grep_probe(), opengrep_probe()],
    }
    if args.include_promptfoo:
        payload["probes"].append(promptfoo_probe())
    payload["evidence_model"] = {
        "ast_grep": "structural search proof only; rewrites require a separate task",
        "opengrep": "read-only SAST availability only; no CI blocking in v1",
        "promptfoo": "only for LLM benchmark tasks, not regular coding gates",
    }
    if args.write_artifact:
        payload["artifact"] = str(write_artifact(payload))
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    ast = payload["probes"][0]
    return 0 if ast.get("installed") and ast.get("sample_read_only_scan", {}).get("returncode") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
