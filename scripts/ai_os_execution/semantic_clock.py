"""Semantic clock pins vs wall clock for replay/P3 scoring paths."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ai_os_execution import SEED_ORIGINS
from ai_os_task_errors import TaskError
from ai_os_task_paths import utc_now

DEFAULT_TIMEZONE = "Europe/Warsaw"
SEMANTIC_CLOCK_STATUS_CONTROLLED = "CONTROLLED"
SEMANTIC_CLOCK_STATUS_UNPINNED = "UNPINNED"
SEMANTIC_CLOCK_STATUS_BLOCKED = "BLOCKED_TIME_NOT_CONTROLLED"

_REQUIRED_REPLAY_PINS = (
    "replay_as_of",
    "timezone",
    "schema_revision",
    "evaluator_version",
    "fixture_hash",
)


def _parse_replay_as_of(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        if raw.endswith("Z"):
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            datetime.fromisoformat(raw)
    except ValueError as exc:
        raise TaskError(f"invalid replay_as_of: {raw}: {exc}") from exc
    return raw


def build_semantic_clock(
    *,
    seed_origin: str,
    execution_mode: str,
    seed_identity: str = "",
    replay_as_of: str = "",
    timezone_name: str = DEFAULT_TIMEZONE,
    schema_revision: str = "",
    evaluator_version: str = "",
    fixture_hash: str = "",
    scoring_paths_proven: bool = False,
) -> dict[str, Any]:
    if seed_origin == "SNAPSHOT" and execution_mode == "BENCHMARK":
        raise TaskError("SNAPSHOT seed is forbidden in BENCHMARK mode")

    pins = {
        "replay_as_of": _parse_replay_as_of(replay_as_of) if replay_as_of else "",
        "timezone": (timezone_name or DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE,
        "schema_revision": (schema_revision or "").strip(),
        "evaluator_version": (evaluator_version or "").strip(),
        "fixture_hash": (fixture_hash or "").strip(),
        "seed_identity": (seed_identity or "").strip(),
    }

    if seed_origin == "HISTORICAL_REPLAY":
        missing = [key for key in _REQUIRED_REPLAY_PINS if not pins.get(key)]
        if missing:
            return {
                "status": SEMANTIC_CLOCK_STATUS_BLOCKED,
                "timezone": pins["timezone"],
                "pins": pins,
                "missing_pins": missing,
                "scoring_paths_proven": False,
                "reason": f"HISTORICAL_REPLAY requires pins: {', '.join(missing)}",
            }
        if not scoring_paths_proven:
            return {
                "status": SEMANTIC_CLOCK_STATUS_BLOCKED,
                "timezone": pins["timezone"],
                "pins": pins,
                "missing_pins": [],
                "scoring_paths_proven": False,
                "reason": "temporal scoring paths not mechanically proven for semantic clock",
            }
        return {
            "status": SEMANTIC_CLOCK_STATUS_CONTROLLED,
            "timezone": pins["timezone"],
            "pins": pins,
            "missing_pins": [],
            "scoring_paths_proven": True,
            "reason": "",
        }

    if seed_origin not in SEED_ORIGINS:
        raise TaskError(f"unsupported seed_origin: {seed_origin}")

    return {
        "status": SEMANTIC_CLOCK_STATUS_UNPINNED,
        "timezone": pins["timezone"],
        "pins": pins,
        "missing_pins": [],
        "scoring_paths_proven": False,
        "reason": "",
    }


def require_semantic_clock_ready(clock: dict[str, Any]) -> None:
    if clock.get("status") == SEMANTIC_CLOCK_STATUS_BLOCKED:
        raise TaskError(f"{SEMANTIC_CLOCK_STATUS_BLOCKED}: {clock.get('reason') or 'semantic clock not controlled'}")


def semantic_env_from_clock(clock: dict[str, Any]) -> dict[str, str]:
    """Declared public env keys for child workloads (pins are not secrets)."""
    if clock.get("status") != SEMANTIC_CLOCK_STATUS_CONTROLLED:
        return {}
    pins = clock.get("pins") or {}
    env: dict[str, str] = {"AI_OS_SEMANTIC_CLOCK": clock["status"]}
    if pins.get("replay_as_of"):
        env["AI_OS_REPLAY_AS_OF"] = str(pins["replay_as_of"])
    if pins.get("timezone"):
        env["AI_OS_REPLAY_TIMEZONE"] = str(pins["timezone"])
    if pins.get("schema_revision"):
        env["AI_OS_SCHEMA_REVISION"] = str(pins["schema_revision"])
    if pins.get("evaluator_version"):
        env["AI_OS_EVALUATOR_VERSION"] = str(pins["evaluator_version"])
    if pins.get("fixture_hash"):
        env["AI_OS_FIXTURE_HASH"] = str(pins["fixture_hash"])
    return env


def scoring_temporal_instant(clock: dict[str, Any]) -> datetime:
    """Sentinel for P3 scoring paths — uses replay_as_of when clock is CONTROLLED."""
    if clock.get("status") != SEMANTIC_CLOCK_STATUS_CONTROLLED:
        raise TaskError(f"scoring_temporal_instant requires CONTROLLED semantic clock, got {clock.get('status')}")
    pins = clock.get("pins") or {}
    replay = str(pins.get("replay_as_of") or "").strip()
    tz_name = str(clock.get("timezone") or DEFAULT_TIMEZONE)
    if not replay:
        raise TaskError("semantic clock CONTROLLED but replay_as_of missing")
    if replay.endswith("Z"):
        dt = datetime.fromisoformat(replay.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(replay)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


def wall_clock_now() -> str:
    """Wall clock for proof bundles and audit (never substituted for semantic scoring)."""
    return utc_now()


def wall_clock_datetime() -> datetime:
    return datetime.now(timezone.utc)
