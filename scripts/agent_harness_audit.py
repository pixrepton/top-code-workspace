#!/usr/bin/env python3
"""Manifest-driven agent harness audit for top-code workspace.

Exit non-zero on FAIL. WARN/INFO are informational.
Source lineage: gmail-agent-legacy@f83845d, rewritten for multi-repo workspace.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - PyYAML optional; minimal parser fallback
    yaml = None  # type: ignore


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    WORKSPACE_ROOT
    / "knowledge"
    / "system-atlas"
    / "tooling"
    / "agent-harness"
    / "AGENT_HARNESS_MANIFEST.yaml"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def load_manifest() -> dict:
    text = _read(MANIFEST_PATH)
    if yaml is not None:
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    # Minimal fallback without PyYAML
    data: dict = {"capabilities": {}, "core_skills": [], "skill_root": ".agents/skills"}
    in_skills = False
    for line in text.splitlines():
        if line.strip() == "core_skills:":
            in_skills = True
            continue
        if in_skills:
            m = re.match(r"\s*-\s+(\S+)", line)
            if m:
                data.setdefault("core_skills", []).append(m.group(1))
            elif line.strip() and not line.startswith(" "):
                in_skills = False
        m = re.match(r"\s+(\w+):\s*$", line)
        if m and line.startswith("  ") and not line.startswith("    "):
            cur = m.group(1)
            data.setdefault("capabilities", {})[cur] = {}
        m = re.match(r"\s+path:\s+(.+)", line)
        if m and "capabilities" in data:
            for key in list(data["capabilities"]):
                if isinstance(data["capabilities"][key], dict) and "path" not in data["capabilities"][key]:
                    data["capabilities"][key]["path"] = m.group(1).strip()
                    break
    return data


def check_capabilities(manifest: dict) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    oks: list[str] = []
    caps = manifest.get("capabilities") or {}
    for name, spec in caps.items():
        if not isinstance(spec, dict):
            continue
        rel = spec.get("path")
        if not rel:
            continue
        path = WORKSPACE_ROOT / str(rel).replace("/", "\\")
        if spec.get("required") and not path.is_file():
            fails.append(f"Missing required capability {name}: {rel}")
        else:
            oks.append(f"capability:{name}")
    return oks, fails


def check_core_skills(manifest: dict) -> tuple[list[str], list[str]]:
    fails: list[str] = []
    oks: list[str] = []
    root = WORKSPACE_ROOT / str(manifest.get("skill_root", ".agents/skills"))
    for name in manifest.get("core_skills") or []:
        skill = root / name / "SKILL.md"
        if not skill.is_file():
            fails.append(f"Missing core skill: {skill.relative_to(WORKSPACE_ROOT).as_posix()}")
        else:
            oks.append(f"skill:{name}")
    return oks, fails


def check_registry_lists_skills(manifest: dict) -> list[str]:
    fails: list[str] = []
    reg = WORKSPACE_ROOT / "knowledge/system-atlas/tooling/agent-harness/AGENT_SKILLS_REGISTRY.md"
    if not reg.is_file():
        fails.append("Missing AGENT_SKILLS_REGISTRY.md")
        return fails
    body = _read(reg)
    for name in manifest.get("core_skills") or []:
        if name not in body:
            fails.append(f"Registry missing mention of core skill: {name}")
    return fails


def check_forbidden_phrases(manifest: dict) -> list[str]:
    fails: list[str] = []
    targets = [
        WORKSPACE_ROOT / "knowledge/system-atlas/tooling/agent-harness/AGENT_DEVELOPMENT_HARNESS.md",
        WORKSPACE_ROOT / "AGENTS.md",
    ]
    phrases = manifest.get("forbidden_phrases") or []
    for p in targets:
        if not p.is_file():
            continue
        lower = _read(p).lower()
        rel = p.relative_to(WORKSPACE_ROOT).as_posix()
        for phrase in phrases:
            if str(phrase).lower() in lower:
                fails.append(f"Forbidden phrase in {rel}: {phrase!r}")
    return fails


def check_no_memory_bank_in_active_rules() -> list[str]:
    fails: list[str] = []
    ga_rules = WORKSPACE_ROOT / "gmail-agent/.cursor/rules"
    if not ga_rules.is_dir():
        return fails
    for mdc in ga_rules.glob("*.mdc"):
        text = _read(mdc)
        for line in text.splitlines():
            lower = line.lower()
            if "memory-bank" not in lower:
                continue
            if re.search(r"do not|don't|never|not use|forbidden|prohibited", lower):
                continue
            fails.append(
                f"gmail-agent rule positively routes to memory-bank: {mdc.name}: {line.strip()[:80]}"
            )
    return fails


def main() -> int:
    parser = argparse.ArgumentParser(description="Workspace agent harness audit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not MANIFEST_PATH.is_file():
        print(f"FAIL: manifest missing: {MANIFEST_PATH}", file=sys.stderr)
        return 1

    manifest = load_manifest()
    oks: list[str] = []
    fails: list[str] = []
    warns: list[str] = []

    o, f = check_capabilities(manifest)
    oks.extend(o)
    fails.extend(f)

    o, f = check_core_skills(manifest)
    oks.extend(o)
    fails.extend(f)

    fails.extend(check_registry_lists_skills(manifest))
    fails.extend(check_forbidden_phrases(manifest))
    fails.extend(check_no_memory_bank_in_active_rules())

  # MCP declared_vs_client: informational only in slice
    mcp = manifest.get("mcp_audit") or {}
    ws_mcp = WORKSPACE_ROOT / str(mcp.get("workspace_declared", ".cursor/mcp.json"))
    if ws_mcp.is_file():
        oks.append("mcp:workspace_declared_present")
    else:
        warns.append("workspace .cursor/mcp.json missing")

    result = {
        "verdict": "FAIL" if fails else "PASS",
        "pass": len(oks),
        "fail": len(fails),
        "warn": len(warns),
        "oks": oks,
        "fails": fails,
        "warns": warns,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"agent_harness_audit — {result['verdict']}")
        print(f"PASS: {result['pass']}  WARN: {result['warn']}  FAIL: {result['fail']}")
        for line in fails:
            print(f"[FAIL] {line}")
        for line in warns:
            print(f"[WARN] {line}")
        for line in oks:
            print(f"[PASS] {line}")

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
