#!/usr/bin/env python3
"""Deterministic agent-map audit for top-code workspace.

Verifies that the designed control plane gives an agent a navigable map:
cold-start chain, workspace goals, skill contracts, scenario→skill routing,
declared MCP roles, nested-repo AGENTS.md, and proof vs graph boundaries.

Does not call LLMs. Exit non-zero on FAIL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_PATH = (
    WORKSPACE_ROOT
    / "knowledge"
    / "system-atlas"
    / "tooling"
    / "agent-harness"
    / "AGENT_MAP_SCENARIOS.yaml"
)
MANIFEST_PATH = (
    WORKSPACE_ROOT
    / "knowledge"
    / "system-atlas"
    / "tooling"
    / "agent-harness"
    / "AGENT_HARNESS_MANIFEST.yaml"
)
MCP_PATH = WORKSPACE_ROOT / ".cursor" / "mcp.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _load_yaml(path: Path) -> dict[str, Any]:
    text = _read(path)
    if yaml is not None:
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    raise RuntimeError(f"PyYAML required to load {path}")


def _rel(path: Path) -> str:
    return path.relative_to(WORKSPACE_ROOT).as_posix()


def _resolve(rel: str) -> Path:
    return WORKSPACE_ROOT / rel.replace("/", "\\")


def check_files_exist(rels: list[str], label: str) -> tuple[list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []
    for rel in rels:
        path = _resolve(rel)
        if path.is_file():
            oks.append(f"{label}:{rel}")
        else:
            fails.append(f"{label} missing: {rel}")
    return oks, fails


def check_markers(rel: str, markers: list[str], label: str) -> tuple[list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []
    path = _resolve(rel)
    if not path.is_file():
        return oks, [f"{label} missing document: {rel}"]
    body = _read(path)
    for marker in markers:
        if marker in body:
            oks.append(f"{label}:{rel}::{marker[:48]}")
        else:
            fails.append(f"{label} missing marker in {rel}: {marker!r}")
    return oks, fails


def check_skill_contracts(skill_root: str, core_skills: list[str], sections: list[str]) -> tuple[list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []
    root = _resolve(skill_root)
    for name in core_skills:
        skill = root / name / "SKILL.md"
        if not skill.is_file():
            fails.append(f"skill_contract missing: {skill_root}/{name}/SKILL.md")
            continue
        body = _read(skill)
        # frontmatter name
        if f"name: {name}" not in body and f'name: "{name}"' not in body:
            fails.append(f"skill_contract frontmatter name mismatch: {name}")
        else:
            oks.append(f"skill_contract:name:{name}")
        if "description:" not in body:
            fails.append(f"skill_contract missing description: {name}")
        else:
            oks.append(f"skill_contract:description:{name}")
        for section in sections:
            if section not in body:
                fails.append(f"skill_contract missing {section!r} in {name}")
            else:
                oks.append(f"skill_contract:section:{name}:{section}")
    return oks, fails


def check_scenarios(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []
    for scenario in spec.get("scenarios") or []:
        sid = scenario.get("id", "<unknown>")
        for rel in scenario.get("must_load") or []:
            if _resolve(rel).is_file():
                oks.append(f"scenario:{sid}:load:{rel}")
            else:
                fails.append(f"scenario:{sid} must_load missing: {rel}")
        for req in scenario.get("required_markers") or []:
            rel = req.get("path", "")
            o, f = check_markers(rel, list(req.get("markers") or []), f"scenario:{sid}")
            oks.extend(o)
            fails.extend(f)
    return oks, fails


def check_mcp(spec: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []
    warns: list[str] = []
    if not MCP_PATH.is_file():
        return oks, ["mcp: .cursor/mcp.json missing"], warns
    try:
        data = json.loads(_read(MCP_PATH))
    except json.JSONDecodeError as exc:
        return oks, [f"mcp: invalid JSON: {exc}"], warns
    servers = data.get("mcpServers") or {}
    for name in spec.get("required_mcp_servers") or []:
        if name in servers:
            oks.append(f"mcp:server:{name}")
        else:
            fails.append(f"mcp: required server missing: {name}")
    roles_doc = spec.get("mcp_roles_document")
    if roles_doc:
        o, f = check_markers(
            roles_doc,
            [str(v) for v in (spec.get("mcp_role_markers") or {}).values()],
            "mcp_roles",
        )
        # Also require tool names appear
        role_keys = list((spec.get("mcp_role_markers") or {}).keys())
        body = _read(_resolve(roles_doc)) if _resolve(roles_doc).is_file() else ""
        for key in role_keys:
            if key in body:
                oks.append(f"mcp_roles:named:{key}")
            else:
                fails.append(f"mcp_roles missing tool name in {roles_doc}: {key}")
        oks.extend(o)
        fails.extend(f)
    return oks, fails, warns


def check_nested_repos(names: list[str]) -> tuple[list[str], list[str]]:
    oks: list[str] = []
    fails: list[str] = []
    for name in names:
        repo = WORKSPACE_ROOT / name
        if not (repo / ".git").exists():
            fails.append(f"nested_repo not a git root: {name}")
            continue
        agents = repo / "AGENTS.md"
        if agents.is_file():
            oks.append(f"nested_repo:AGENTS.md:{name}")
        else:
            fails.append(f"nested_repo missing AGENTS.md: {name}")
    return oks, fails


def check_exploration_policy_coherence() -> tuple[list[str], list[str], list[str]]:
    """Cursor exploration skill must be MCP-first; warn if TOOLING_POLICY still rg-first."""
    oks: list[str] = []
    fails: list[str] = []
    warns: list[str] = []
    skill = _resolve(".agents/skills/code-intelligence-routing/SKILL.md")
    if not skill.is_file():
        return oks, ["exploration_policy: skill missing"], warns
    skill_body = _read(skill)
    for marker in ("Explore via MCP/graph", "before broad Read/Grep", "CODE_INTELLIGENCE_ROUTER.md"):
        if marker in skill_body:
            oks.append(f"exploration_policy:skill:{marker}")
        else:
            fails.append(f"exploration_policy skill missing MCP-first marker: {marker!r}")
    tooling = _resolve("knowledge/TOOLING_POLICY.md")
    if tooling.is_file():
        tooling_body = _read(tooling)
        if "default to direct Git, source reads and `rg`" in tooling_body:
            warns.append(
                "TOOLING_POLICY still states Codex safe-mode rg-first; "
                "Cursor exploration uses code-intelligence-routing MCP-first — keep both intentional"
            )
        else:
            oks.append("exploration_policy:tooling_aligned")
    return oks, fails, warns


def check_registry_scenario_coverage(core_skills: list[str], scenarios: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Every core skill should be referenced by at least one scenario must_load."""
    oks: list[str] = []
    fails: list[str] = []
    joined = "\n".join(
        "\n".join(str(p) for p in (s.get("must_load") or [])) for s in scenarios
    )
    for name in core_skills:
        needle = f".agents/skills/{name}/"
        if needle in joined or f".agents/skills/{name}/SKILL.md" in joined:
            oks.append(f"scenario_coverage:{name}")
        else:
            fails.append(f"core skill not covered by any scenario must_load: {name}")
    return oks, fails


def run_audit() -> dict[str, Any]:
    if not SCENARIOS_PATH.is_file():
        return {
            "verdict": "FAIL",
            "pass": 0,
            "fail": 1,
            "warn": 0,
            "oks": [],
            "fails": [f"scenarios file missing: {_rel(SCENARIOS_PATH)}"],
            "warns": [],
        }

    spec = _load_yaml(SCENARIOS_PATH)
    manifest: dict[str, Any] = {}
    if MANIFEST_PATH.is_file():
        try:
            manifest = _load_yaml(MANIFEST_PATH)
        except RuntimeError:
            manifest = {}

    oks: list[str] = []
    fails: list[str] = []
    warns: list[str] = []

    o, f = check_files_exist(list(spec.get("cold_start_chain") or []), "cold_start")
    oks.extend(o)
    fails.extend(f)

    goals = spec.get("workspace_goals") or {}
    if goals.get("document"):
        o, f = check_markers(goals["document"], list(goals.get("required_markers") or []), "workspace_goal")
        oks.extend(o)
        fails.extend(f)

    index = spec.get("index_routes") or {}
    if index.get("document"):
        o, f = check_markers(index["document"], list(index.get("required_markers") or []), "index_route")
        oks.extend(o)
        fails.extend(f)

    o, f = check_files_exist(list(spec.get("always_apply_cursor_rules") or []), "cursor_rule")
    oks.extend(o)
    fails.extend(f)

    o, f = check_files_exist(list(spec.get("claude_subagents") or []), "claude_subagent")
    oks.extend(o)
    fails.extend(f)

    core_skills = list(manifest.get("core_skills") or [])
    skill_root = str(manifest.get("skill_root", ".agents/skills"))
    o, f = check_skill_contracts(skill_root, core_skills, list(spec.get("skill_required_sections") or []))
    oks.extend(o)
    fails.extend(f)

    o, f = check_scenarios(spec)
    oks.extend(o)
    fails.extend(f)

    o, f = check_registry_scenario_coverage(core_skills, list(spec.get("scenarios") or []))
    oks.extend(o)
    fails.extend(f)

    o, f, w = check_mcp(spec)
    oks.extend(o)
    fails.extend(f)
    warns.extend(w)

    o, f = check_nested_repos(list(spec.get("nested_repos_with_agents_md") or []))
    oks.extend(o)
    fails.extend(f)

    o, f, w = check_exploration_policy_coherence()
    oks.extend(o)
    fails.extend(f)
    warns.extend(w)

    return {
        "verdict": "FAIL" if fails else "PASS",
        "pass": len(oks),
        "fail": len(fails),
        "warn": len(warns),
        "oks": oks,
        "fails": fails,
        "warns": warns,
        "scenario_count": len(spec.get("scenarios") or []),
        "core_skill_count": len(core_skills),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent map / harness navigation audit")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_audit()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"agent_map_audit — {result['verdict']}")
        print(
            f"PASS: {result['pass']}  WARN: {result['warn']}  FAIL: {result['fail']}  "
            f"scenarios: {result.get('scenario_count', 0)}  core_skills: {result.get('core_skill_count', 0)}"
        )
        for line in result["fails"]:
            print(f"[FAIL] {line}")
        for line in result["warns"]:
            print(f"[WARN] {line}")
        for line in result["oks"]:
            print(f"[PASS] {line}")
    return 1 if result["fails"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
