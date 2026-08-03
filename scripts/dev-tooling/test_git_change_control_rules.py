from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / ".codex" / "rules" / "git-change-control.rules"


def test_rules_cover_required_git_boundaries():
    text = RULES.read_text(encoding="utf-8")
    required = (
        '["git", "add"]',
        '["git", "commit"]',
        '["git", "push"]',
        '["git", "reset"]',
        '["git", "clean"]',
        '["git", "stash", ["drop", "clear"]]',
        '["git", "branch", "-D"]',
        '["git", "restore"]',
        '["gh", "pr", "create"]',
        '["gh", "pr", "merge"]',
        'decision = "forbidden"',
        'decision = "prompt"',
        'match =',
        'not_match =',
    )
    for item in required:
        assert item in text


def test_raw_commit_routes_to_task_wrapper():
    text = RULES.read_text(encoding="utf-8")
    assert "task-commit-plan" in text
    assert "task-commit" in text
    assert "foreign staged" in text
