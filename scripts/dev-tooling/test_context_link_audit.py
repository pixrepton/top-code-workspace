"""Tests for workspace context_link_audit."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

WORKSPACE = Path(__file__).resolve().parents[2]
AUDIT = WORKSPACE / "scripts" / "context_link_audit.py"


def _load_audit():
    spec = importlib.util.spec_from_file_location("context_link_audit", AUDIT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # @dataclass resolves __module__ through sys.modules during exec_module,
    # so the module must be registered before it runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(scope: str) -> subprocess.CompletedProcess[str]:
    # encoding/errors are explicit: the default Windows codec raised
    # UnicodeDecodeError on non-UTF-8 bytes in child output and produced
    # PytestUnhandledThreadExceptionWarning noise.
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(AUDIT), "--scope", scope],
        cwd=WORKSPACE,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_context_link_audit_workspace_scope():
    proc = _run("workspace")
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.xfail(
    reason=(
        "Backtick-path auditing surfaced 22 pre-existing dead routes in "
        "gmail-agent/.cursor/rules/*.mdc, mostly wrong '../' depth: from "
        "gmail-agent/.cursor/rules/ a citation of '../../knowledge/INDEX.md' "
        "resolves to gmail-agent/knowledge/INDEX.md. Fixing them belongs to the "
        "gmail-agent repo, which is outside this task's scope and partly owned by "
        "another active checkpoint. Do NOT relax the audit to make this pass; fix "
        "the rules and delete this marker (it will XPASS first)."
    ),
    strict=False,
)
def test_context_link_audit_gmail_agent_scope():
    proc = _run("gmail-agent")
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- Regression: backticked path citations ---------------------------------
# This workspace expresses canonical routes as backticked paths, not markdown
# links. Auditing only markdown links reported broken=0 while six canonical
# routes were dead. These tests fail if that blindness returns.


def _scan(tmp_path, body: str, rel_path: str = "AGENTS.md"):
    module = _load_audit()
    target = tmp_path / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return module, module.scan_backtick_paths(tmp_path, rel_path, body, set())


def test_backticked_dead_route_is_detected(tmp_path):
    _, findings = _scan(tmp_path, "Canonical procedure:\n\n`knowledge/system-atlas/tooling/NOPE.md`\n")
    assert [f.resolved_as for f in findings] == ["unresolved_missing"]


def test_backticked_live_route_resolves(tmp_path):
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "knowledge" / "INDEX.md").write_text("x", encoding="utf-8")
    _, findings = _scan(tmp_path, "See `knowledge/INDEX.md` first.\n")
    assert [f.resolved_as for f in findings] == ["local_abs"]


def test_dotfile_path_is_not_mangled(tmp_path):
    """str.lstrip('./') strips a character set, not a prefix.

    It turned '.cursor/rules/x.mdc' into 'cursor/rules/x.mdc', reporting every
    dot-prefixed path as a dead route.
    """
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "40-context7-auto-docs.mdc").write_text("x", encoding="utf-8")
    _, findings = _scan(
        tmp_path,
        "Rule: `.cursor/rules/40-context7-auto-docs.mdc`\n",
        rel_path=".agents/skills/demo/SKILL.md",
    )
    assert [f.resolved_as for f in findings] == ["local_abs"]


def test_bare_filename_is_not_treated_as_route(tmp_path):
    _, findings = _scan(tmp_path, "Update `SKILL.md` and `world-state.yaml` afterwards.\n")
    assert findings == []


def test_fenced_code_is_ignored(tmp_path):
    body = "Run it:\n\n```powershell\npython scripts/does/not/exist.py\n```\n"
    _, findings = _scan(tmp_path, body)
    assert findings == []


def test_placeholder_citation_is_ignored(tmp_path):
    _, findings = _scan(tmp_path, "Example: `repo/path/to/file.py` and `scripts/ai_os_task*.py`\n")
    assert findings == []


# --- Regression: cross_repo must not excuse a present repository ------------


def test_missing_file_in_present_repo_is_not_excused(tmp_path, monkeypatch):
    module = _load_audit()
    monkeypatch.setattr(module, "WORKSPACE_ROOT", tmp_path)
    (tmp_path / "knowledge").mkdir()
    assert module.classify_missing("knowledge/system-atlas/tooling/GONE.md") == "unresolved_missing"


def test_missing_file_in_absent_repo_stays_cross_repo(tmp_path, monkeypatch):
    module = _load_audit()
    monkeypatch.setattr(module, "WORKSPACE_ROOT", tmp_path)
    assert module.classify_missing("gmail-agent/docs/whatever.md") == "cross_repo"
