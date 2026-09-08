"""Cold-start projection: READ + generate CAMPAIGN_STATE / TASK_ENTRY. No execution mutation."""

from __future__ import annotations

from typing import Any

from ai_os_execution.bundle import execution_dir, load_bundle_for_task
from ai_os_execution.campaign import (
    format_session_inject,
    generate_campaign_state,
    write_task_entry,
)
from ai_os_task_paths import list_active_task_ids


def project_session_state(*, task_id: str = "", current_program: str = "") -> dict[str, Any]:
    """Generate projections for the current task. Does not takeover, heartbeat, or mutate the bundle."""
    active = list_active_task_ids()
    current = task_id
    if not current and len(active) == 1:
        current = active[0]
    if not current and len(active) > 1:
        state = generate_campaign_state(current_task_id="", current_program=current_program)
        state["kind"] = "MULTIPLE"
        state["active_tasks"] = active
        inject = (
            "CURRENT TASK: multiple\n"
            f"ACTIVE: {', '.join(active)}\n"
            "Set AI_OS_TASK_ID. Do not invent an Execution Bundle."
        )
        return {"state": state, "inject": inject, "mutated_execution": False}
    state = generate_campaign_state(current_task_id=current, current_program=current_program)
    bundle = load_bundle_for_task(current) if current and state.get("kind") == "PLANE" else None
    checkpoint = None
    if current:
        try:
            from ai_os_task_state import load_checkpoint

            checkpoint = load_checkpoint(current)
        except Exception:
            checkpoint = None
    if bundle:
        path = write_task_entry(
            bundle,
            goal=str((checkpoint or {}).get("task_title") or ""),
            checkpoint=checkpoint,
            campaign=state,
        )
        state["task_entry"] = str(path)
    else:
        state["task_entry"] = (
            str(execution_dir(bundle["execution_id"]) / "TASK_ENTRY.md") if bundle else ""
        )
    return {
        "state": state,
        "inject": format_session_inject(state),
        "mutated_execution": False,
    }
