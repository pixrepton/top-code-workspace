import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_shared_policy_has_one_commit_route():
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    engineering = (ROOT / "knowledge" / "ENGINEERING_POLICY.md").read_text(encoding="utf-8")
    git_policy = (
        ROOT / "knowledge" / "system-atlas" / "tooling" / "GIT_AND_CHANGE_CONTROL.md"
    ).read_text(encoding="utf-8")
    for text in (agents, engineering, git_policy):
        assert "task-commit-plan" in text
        assert "task-commit" in text
        assert "LOCAL_ONLY" in text
    assert "does not authorize push" in agents
    assert "Do not use raw `git add` or `git commit`" in agents


def test_claude_and_codex_adapters_are_valid_and_portable():
    claude = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    codex_text = (ROOT / ".codex" / "hooks.json").read_text(encoding="utf-8")
    codex = json.loads(codex_text)
    assert {"SessionStart", "PreCompact", "PreToolUse", "PostToolUse", "TaskCompleted", "SessionEnd"} <= set(
        claude["hooks"]
    )
    assert "ai_os_claude_hook.py" in json.dumps(claude)
    assert "C:/Users/" not in codex_text
    assert "ai_os_codex_hook.py" in json.dumps(codex)


def test_claude_configuration_sources_can_be_versioned():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for path in ("!/.claude/agents/**", "!/.claude/hooks/**", "!/.claude/rules/**", "!/.claude/skills/**"):
        assert path in ignore


def test_execution_map_routes_to_git_policy():
    execution_map = (
        ROOT / "knowledge" / "system-atlas" / "tooling" / "CODEX_EXECUTION_MAP.md"
    ).read_text(encoding="utf-8")
    assert "[Git And Change Control](GIT_AND_CHANGE_CONTROL.md)" in execution_map
    assert "task-branch ->" in execution_map
    assert "task-commit-plan/task-commit" in execution_map
