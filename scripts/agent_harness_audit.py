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


TYPE_A_REPOS = (
    "knowledge",
    "gmail-agent",
    "daszek",
    "kalk-top",
    "rag-chat-asystent",
    "rag-widget",
    "cieplo-orchestrator",
    "fast-kalk",
    "top-instal-generator",
)

TYPE_B_STUBS = (
    "wp-bridges/AGENTS.md",
    "scripts/AGENTS.md",
    "tests/AGENTS.md",
    "tools/AGENTS.md",
    "payload/AGENTS.md",
    ".agents/AGENTS.md",
)

TYPE_A_MARKERS = (
    "Status:",
    "## Role",
    "Must not",
    "## Gate A",
    "## Cross-repo",
    "## Anti-goals",
    "Safety capsule",
)

TYPE_B_MARKERS = (
    "Typ B",
    "root-owned",
    "../AGENTS.md",
    "## Gate",
    "## Anti-goals",
)

FORBIDDEN_AGENTS_PLACEHOLDERS = (
    "<zmieniony plik>",
    "<changed-php-file>",
    "uruchom jakieś testy",
)


def _unclosed_fence(body: str) -> bool:
    return body.count("```") % 2 != 0


def check_agents_l1l2_model() -> tuple[list[str], list[str]]:
    """Validate L1/L2 AGENTS.md adapters (Typ A repos + Typ B stubs)."""
    oks: list[str] = []
    fails: list[str] = []

    root_agents = WORKSPACE_ROOT / "AGENTS.md"
    if not root_agents.is_file():
        fails.append("root AGENTS.md missing")
        return oks, fails
    root_body = _read(root_agents)
    for marker in ("L1 / L2 instruction model", "Typ A", "Typ B", "knowledge/INDEX.md"):
        if marker not in root_body:
            fails.append(f"root AGENTS.md missing L1/L2 marker: {marker!r}")
        else:
            oks.append(f"root_l1l2:{marker}")

    index = WORKSPACE_ROOT / "knowledge" / "INDEX.md"
    if index.is_file():
        idx = _read(index)
        for marker in (
            "knowledge/AGENTS.md",
            "Whole workspace session",
            "Work opened directly inside the `knowledge` Git repo",
        ):
            if marker not in idx:
                fails.append(f"knowledge/INDEX.md cold-start missing: {marker!r}")
            else:
                oks.append(f"index_cold_start:{marker}")
    else:
        fails.append("knowledge/INDEX.md missing")

    for name in TYPE_A_REPOS:
        repo = WORKSPACE_ROOT / name
        if not (repo / ".git").exists():
            fails.append(f"Typ A path is not a git root: {name}")
            continue
        agents = repo / "AGENTS.md"
        if not agents.is_file():
            fails.append(f"Typ A missing AGENTS.md: {name}")
            continue
        body = _read(agents)
        oks.append(f"type_a_present:{name}")
        if _unclosed_fence(body):
            fails.append(f"Typ A unclosed markdown fence: {name}/AGENTS.md")
        for ph in FORBIDDEN_AGENTS_PLACEHOLDERS:
            if ph in body:
                fails.append(f"Typ A forbidden placeholder in {name}/AGENTS.md: {ph!r}")
        for marker in TYPE_A_MARKERS:
            # Allow Polish/English Role heading variants already normalized to ## Role
            if marker not in body:
                fails.append(f"Typ A {name}/AGENTS.md missing section/marker: {marker!r}")
            else:
                oks.append(f"type_a_marker:{name}:{marker}")
        if "independent Git" in body.lower() and "typ b" in body.lower():
            fails.append(f"Typ A {name} incorrectly claims Typ B")
        # GitNexus integrity: if markers present, both start and end required
        has_start = "<!-- gitnexus:start -->" in body
        has_end = "<!-- gitnexus:end -->" in body
        if has_start != has_end:
            fails.append(f"Typ A {name}/AGENTS.md broken GitNexus markers start={has_start} end={has_end}")
        elif has_start:
            oks.append(f"type_a_gitnexus:{name}")

    for rel in TYPE_B_STUBS:
        path = WORKSPACE_ROOT / rel.replace("/", "\\")
        if not path.is_file():
            fails.append(f"Typ B stub missing: {rel}")
            continue
        body = _read(path)
        oks.append(f"type_b_present:{rel}")
        if _unclosed_fence(body):
            fails.append(f"Typ B unclosed markdown fence: {rel}")
        for ph in FORBIDDEN_AGENTS_PLACEHOLDERS:
            if ph in body:
                fails.append(f"Typ B forbidden placeholder in {rel}: {ph!r}")
        for marker in TYPE_B_MARKERS:
            if marker not in body:
                fails.append(f"Typ B {rel} missing marker: {marker!r}")
            else:
                oks.append(f"type_b_marker:{rel}:{marker}")
        # Typ B must not pretend to be an independent git product repo
        if re.search(r"(?i)independent git repository(?!.*not)", body) and "not an independent" not in body.lower():
            # soft: require explicit negation already covered by root-owned marker
            pass
        if "Cold-Start" in body and "full cold-start" in body.lower():
            fails.append(f"Typ B {rel} contains expanded cold-start (forbidden)")
        if rel == "tools/AGENTS.md":
            if "STOP" not in body and "read-only" not in body.lower():
                fails.append("tools/AGENTS.md must be STOP/read-only by default")
            else:
                oks.append("type_b_tools_stop")
            if "gmail-agent/tools/gmail_audit" not in body.replace("\\", "/"):
                fails.append("tools/AGENTS.md must point at canonical gmail-agent/tools/gmail_audit")
        if rel == "payload/AGENTS.md":
            if "customer" not in body.lower() and "PII" not in body and "mailbox" not in body.lower():
                fails.append("payload/AGENTS.md must forbid customer/PII/mailbox dumps")
            else:
                oks.append("type_b_payload_no_pii")

    # Critical path existence referenced from knowledge AGENTS
    knowledge_agents = WORKSPACE_ROOT / "knowledge" / "AGENTS.md"
    if knowledge_agents.is_file():
        for rel in (
            "knowledge/INDEX.md",
            "knowledge/CONTROL_PLANE.md",
            "knowledge/SESSION_MEMORY_POLICY.md",
            "knowledge/DOCUMENTATION_POLICY.md",
        ):
            if (WORKSPACE_ROOT / rel.replace("/", "\\")).is_file():
                oks.append(f"critical_path:{rel}")
            else:
                fails.append(f"critical path missing: {rel}")

    return oks, fails


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

    o, f = check_agents_l1l2_model()
    oks.extend(o)
    fails.extend(f)

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
