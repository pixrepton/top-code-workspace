"""Three-way reasoning that separates task changes from pre-existing work."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ai_os_task_ownership_git import State


ABSORBED_FOREIGN_DELTA = "task state absorbed a pre-existing foreign delta"
OVERLAPPING_FOREIGN_HUNK = "task change overlaps a pre-existing foreign hunk"
MERGE_TEMP_PREFIX = "ai-os-ownership-"
SUBTRACT_TEMP_PREFIX = "ai-os-ownership-subtract-"


@dataclass(frozen=True)
class GuardMessages:
    non_file: str
    binary: str


MERGE_GUARDS = GuardMessages(
    non_file="non-file baseline delta cannot be merged safely",
    binary="binary baseline delta overlaps a task change",
)
SUBTRACT_GUARDS = GuardMessages(
    non_file="non-file baseline delta cannot be subtracted safely",
    binary="binary baseline delta cannot be subtracted safely",
)


@dataclass(frozen=True)
class StateTriple:
    """Task state, task-start base state and the foreign state to preserve."""

    current: State
    base: State
    foreign: State

    @property
    def states(self) -> tuple[State, State, State]:
        return (self.current, self.base, self.foreign)

    @property
    def current_missing(self) -> bool:
        return self.current[0] == "missing"

    @property
    def base_missing(self) -> bool:
        return self.base[0] == "missing"

    @property
    def foreign_missing(self) -> bool:
        return self.foreign[0] == "missing"


@dataclass(frozen=True)
class MergeOutcome:
    state: State | None
    error: str


def _guard_reason(triple: StateTriple, messages: GuardMessages) -> str:
    if not all(state[0] == "file" for state in triple.states):
        return messages.non_file
    if any(b"\0" in (state[1] or b"") for state in triple.states):
        return messages.binary
    return ""


def _write_merge_inputs(directory: Path, states: tuple[State, State, State]) -> list[str]:
    names = ("ours", "base", "theirs")
    written: list[str] = []
    for name, state in zip(names, states):
        target = directory / name
        target.write_bytes(state[1] or b"")
        written.append(str(target))
    return written


def _run_merge_file(
    states: tuple[State, State, State],
    prefix: str,
) -> subprocess.CompletedProcess[bytes]:
    # Git for Windows can fail to open merge inputs when a pytest/state path nears MAX_PATH.
    with tempfile.TemporaryDirectory(prefix=prefix) as tmp_raw:
        inputs = _write_merge_inputs(Path(tmp_raw), states)
        return subprocess.run(["git", "merge-file", "-p", *inputs], capture_output=True)


def _failure_reason(proc: subprocess.CompletedProcess[bytes], label: str) -> str:
    detail = proc.stderr.decode(errors="replace").strip()
    return f"three-way ownership {label} failed: {detail or proc.returncode}"


def _merge_missing_base(triple: StateTriple) -> MergeOutcome:
    if triple.foreign_missing:
        return MergeOutcome(triple.current, "")
    if triple.current_missing:
        return MergeOutcome(triple.foreign, "")
    return MergeOutcome(
        None,
        "task committed or staged a path that was foreign and untracked at task start",
    )


def _resolve_merge_missing(triple: StateTriple) -> MergeOutcome | None:
    if triple.base_missing:
        return _merge_missing_base(triple)
    if triple.foreign_missing:
        if triple.current == triple.base:
            return MergeOutcome(triple.foreign, "")
        return MergeOutcome(None, "task overlapped or committed a pre-existing foreign deletion")
    if triple.current_missing:
        if triple.foreign == triple.base:
            return MergeOutcome(triple.current, "")
        return MergeOutcome(None, "task deleted a path carrying a pre-existing foreign delta")
    return None


def _resolve_merge_identical(triple: StateTriple) -> MergeOutcome | None:
    if triple.foreign == triple.base:
        return MergeOutcome(triple.current, "")
    if triple.current == triple.base:
        return MergeOutcome(triple.foreign, "")
    if triple.current == triple.foreign:
        return MergeOutcome(None, ABSORBED_FOREIGN_DELTA)
    return None


def _merged_content_outcome(merged: bytes, current: State) -> MergeOutcome:
    if merged == (current[1] or b""):
        return MergeOutcome(None, ABSORBED_FOREIGN_DELTA)
    return MergeOutcome(("file", merged), "")


def _resolve_merge_three_way(triple: StateTriple) -> MergeOutcome:
    guard = _guard_reason(triple, MERGE_GUARDS)
    if guard:
        return MergeOutcome(None, guard)
    proc = _run_merge_file(triple.states, MERGE_TEMP_PREFIX)
    if proc.returncode == 0:
        return _merged_content_outcome(proc.stdout, triple.current)
    if proc.returncode == 1:
        return MergeOutcome(None, OVERLAPPING_FOREIGN_HUNK)
    return MergeOutcome(None, _failure_reason(proc, "merge"))


def merge_expected(current: State, base: State, foreign: State) -> tuple[State | None, str]:
    """Expected state when the foreign task-start delta is re-applied to current."""
    triple = StateTriple(current, base, foreign)
    outcome = _resolve_merge_missing(triple)
    if outcome is None:
        outcome = _resolve_merge_identical(triple)
    if outcome is None:
        outcome = _resolve_merge_three_way(triple)
    return outcome.state, outcome.error


def _subtract_missing_base(triple: StateTriple) -> MergeOutcome:
    if triple.foreign_missing:
        return MergeOutcome(triple.current, "")
    return MergeOutcome(
        None,
        "cannot isolate task changes from a file that was foreign and untracked at task start",
    )


def _resolve_subtract_early(triple: StateTriple) -> MergeOutcome | None:
    if triple.foreign == triple.base:
        return MergeOutcome(triple.current, "")
    if triple.base_missing:
        return _subtract_missing_base(triple)
    if triple.foreign_missing:
        return MergeOutcome(
            None,
            "cannot isolate task changes across a pre-existing foreign deletion",
        )
    if triple.current_missing:
        return MergeOutcome(
            None,
            "cannot preserve a pre-existing foreign delta when the task deletes the path",
        )
    if triple.current == triple.foreign:
        return MergeOutcome(triple.base, "")
    return None


def _resolve_subtract_three_way(triple: StateTriple) -> MergeOutcome:
    guard = _guard_reason(triple, SUBTRACT_GUARDS)
    if guard:
        return MergeOutcome(None, guard)
    inputs = (triple.current, triple.foreign, triple.base)
    proc = _run_merge_file(inputs, SUBTRACT_TEMP_PREFIX)
    if proc.returncode == 0:
        return MergeOutcome(("file", proc.stdout), "")
    if proc.returncode == 1:
        return MergeOutcome(None, OVERLAPPING_FOREIGN_HUNK)
    return MergeOutcome(None, _failure_reason(proc, "subtraction"))


def remove_foreign_delta(combined: State, base: State, foreign: State) -> tuple[State | None, str]:
    """Task-only state, with the task-start foreign delta removed from combined."""
    triple = StateTriple(combined, base, foreign)
    outcome = _resolve_subtract_early(triple)
    if outcome is None:
        outcome = _resolve_subtract_three_way(triple)
    return outcome.state, outcome.error
