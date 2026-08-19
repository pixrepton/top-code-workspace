"""Agent-facing commit decision evaluation for task-commit-plan.

The engine emits a structured decision so agents reason and act — they do not
ask the operator "czy commit?" for routine scoped work.
"""

from __future__ import annotations

from typing import Any

from ai_os_task_ownership import scope_contains
from ai_os_task_scope import normalize_rel

DECISION_COMMIT_NOW = "COMMIT_NOW"
DECISION_COMMIT_LATER = "COMMIT_LATER"
DECISION_NO_COMMIT = "NO_COMMIT"
DECISION_DEFER_OPERATOR = "DEFER_OPERATOR"

_TERMINAL_TASK_STATUSES = frozenset({"CLOSED", "ABORTED_WITH_EVIDENCE"})


def _scope_entry(repo: str, path: str) -> dict[str, str]:
    return {"repo": repo, "path": normalize_rel(path)}


def paths_outside_scope(data: dict[str, Any], repo: str, owned_paths: list[str]) -> list[str]:
    scope = data.get("declared_write_scope", [])
    return [path for path in owned_paths if not scope_contains(scope, _scope_entry(repo, path))]


def _owned_paths_for_repo(data: dict[str, Any], repo: str) -> list[str]:
    prefix = f"{repo}:"
    values: set[str] = set()
    for key in ("own_staged_files", "own_unstaged_files", "own_untracked_files"):
        for item in data.get(key, []):
            if item.startswith(prefix):
                values.add(normalize_rel(item[len(prefix) :]))
    return sorted(values)


def other_repos_with_owned_paths(data: dict[str, Any], repo: str) -> list[str]:
    return [
        other
        for other in data.get("target_repositories", [])
        if other != repo and _owned_paths_for_repo(data, other)
    ]


def evaluate_commit_decision(data: dict[str, Any], repo: str, plan: dict[str, Any]) -> dict[str, Any]:
    verdict = str(plan.get("verdict", ""))
    owned = list(plan.get("owned_paths", []))
    reasons = list(plan.get("reasons", []))
    warnings = list(plan.get("warnings", []))

    rationale: list[str] = []
    blockers: list[str] = []
    next_steps: list[str] = []

    status = str(data.get("status", ""))
    next_action = str(data.get("next_action") or "").strip()
    publication = str(data.get("publication_mode", "LOCAL_ONLY"))
    conflicts = list(data.get("ownership_conflicts", []))
    out_of_scope = paths_outside_scope(data, repo, owned)
    other_dirty = other_repos_with_owned_paths(data, repo)

    if verdict == "NO_COMMIT":
        decision = DECISION_NO_COMMIT
        rationale.append("Brak task-owned sciezek do commita w tym repo.")
        next_steps.append("Kontynuuj prace albo zamknij task, jesli nie ma residue.")
    elif verdict == "BLOCKED":
        decision = DECISION_COMMIT_LATER
        rationale.append("task-commit-plan verdict=BLOCKED — commit mechanicznie zablokowany.")
        blockers.extend(reasons)
        next_steps.extend(
            [
                "Napraw blockery (gate fingerprint, branch, ownership, secrets).",
                "python scripts/ai_os_task.py task-commit-plan --repo <repo> --json",
            ]
        )
    else:
        deferred: list[str] = []
        if status in _TERMINAL_TASK_STATUSES:
            deferred.append(f"task status={status} — otworz mikro-task przed commitem")
        if next_action:
            deferred.append(f"next_action niepuste: {next_action[:120]}")
        if out_of_scope:
            deferred.append(
                f"{len(out_of_scope)} owned path(s) poza declared_write_scope: "
                + ", ".join(out_of_scope[:5])
            )
        if conflicts:
            deferred.append(f"{len(conflicts)} ownership conflict(s)")

        if deferred:
            decision = DECISION_COMMIT_LATER
            blockers.extend(deferred)
            next_steps.extend(
                [
                    "Dokoncz logiczny slice albo rozszerz scope/adopt-baseline.",
                    "python scripts/ai_os_task.py task-commit-plan --repo <repo> --json",
                ]
            )
        else:
            decision = DECISION_COMMIT_NOW
            rationale.append("verdict=COMMIT_READY; scope spojny; brak otwartych blockerow slice.")
            if publication in {"PUBLISH", "SHIP"}:
                rationale.append(
                    f"publication={publication}: commit lokalny dozwolony; push/PR wymaga osobnej autoryzacji."
                )
            next_steps.append(
                f'python scripts/ai_os_task.py task-commit --repo {repo} --message "<opis slice>"'
            )
            if other_dirty:
                rationale.append(
                    "Inne repo ma task-owned residue: " + ", ".join(other_dirty) + " — commit per repo."
                )
                for other in other_dirty:
                    next_steps.append(f"python scripts/ai_os_task.py task-commit-plan --repo {other} --json")

    if conflicts and decision != DECISION_NO_COMMIT:
        foreign = [item for item in conflicts if "foreign" in str(item).lower()]
        if foreign:
            decision = DECISION_DEFER_OPERATOR
            blockers.append("ownership conflict z obca praca — wymaga decyzji operatora")
            next_steps.insert(0, "Rozstrzygnij konflikt ownership przed commitem.")

    agent_report = _format_agent_report(
        decision=decision,
        repo=repo,
        verdict=verdict,
        owned=owned,
        rationale=rationale,
        blockers=blockers,
        warnings=warnings,
        next_steps=next_steps,
    )

    return {
        "decision": decision,
        "verdict": verdict,
        "rationale": rationale,
        "blockers": blockers,
        "warnings": warnings,
        "next_steps": next_steps,
        "paths_outside_scope": out_of_scope,
        "other_repos_pending": other_dirty,
        "agent_report": agent_report,
        "ask_operator": decision == DECISION_DEFER_OPERATOR,
    }


def _format_agent_report(
    *,
    decision: str,
    repo: str,
    verdict: str,
    owned: list[str],
    rationale: list[str],
    blockers: list[str],
    warnings: list[str],
    next_steps: list[str],
) -> str:
    lines = [
        "## Decyzja commit (task engine)",
        f"- Werdykt: {decision}",
        f"- Repo: {repo}",
        f"- Plan: {verdict}",
    ]
    if owned:
        preview = ", ".join(owned[:8])
        if len(owned) > 8:
            preview += ", ..."
        lines.append(f"- Owned paths ({len(owned)}): {preview}")
    for item in rationale:
        lines.append(f"- Uzasadnienie: {item}")
    for item in blockers:
        lines.append(f"- Bloker: {item}")
    for item in warnings[:5]:
        lines.append(f"- Warning: {item}")
    if next_steps:
        lines.append("- Nastepny krok:")
        lines.extend(f"  - {step}" for step in next_steps[:8])
    return "\n".join(lines)


def print_commit_decision(decision: dict[str, Any], as_json: bool) -> None:
    if as_json:
        return
    print("--- commit decision ---")
    print(decision["agent_report"].replace("## Decyzja commit (task engine)", "DECISION").strip())
