"""Compile EFFECTIVE_CAPABILITIES from mode × seed × profile; fail closed on denied requests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_os_task_errors import TaskError

_DATA_DIR = Path(__file__).resolve().parent / "data"
_DEFAULTS_PATH = _DATA_DIR / "CAPABILITY_DEFAULTS.json"


def _load_defaults(path: Path | None = None) -> dict[str, Any]:
    target = path or _DEFAULTS_PATH
    if not target.exists():
        raise TaskError(f"capability defaults missing: {target}")
    return json.loads(target.read_text(encoding="utf-8"))


def _matrix_key(execution_mode: str, seed_origin: str, capability_profile: str) -> str:
    return f"{execution_mode}+{seed_origin}+{capability_profile}"


def capability_trigger_keys(defaults_path: Path | None = None) -> frozenset[str]:
    catalog = _load_defaults(defaults_path)
    return frozenset(str(k) for k in (catalog.get("env_triggers") or {}))


def compile_effective_capabilities(
    *,
    execution_mode: str,
    seed_origin: str,
    capability_profile: str,
    declared_env: dict[str, str] | None = None,
    declared_secrets: dict[str, str] | None = None,
    defaults_path: Path | None = None,
) -> dict[str, Any]:
    catalog = _load_defaults(defaults_path)
    capability_ids = list(catalog.get("capabilities") or [])
    base = dict((catalog.get("defaults") or {}).get("*") or {})
    overlay = dict((catalog.get("defaults") or {}).get(_matrix_key(execution_mode, seed_origin, capability_profile)) or {})
    effective = {cap: overlay.get(cap, base.get(cap, "DENY")) for cap in capability_ids}

    declared_env = declared_env or {}
    declared_secrets = declared_secrets or {}
    merged = {**declared_env, **declared_secrets}
    triggers = catalog.get("env_triggers") or {}
    requested: dict[str, str] = {}
    for key, value in merged.items():
        if not str(value).strip():
            continue
        cap = triggers.get(key)
        if cap:
            requested[cap] = key

    violations: list[str] = []
    for cap, trigger_key in requested.items():
        verdict = effective.get(cap, "DENY")
        if verdict == "DENY":
            violations.append(f"{cap} requested via {trigger_key} but EFFECTIVE= DENY")
        elif verdict == "ALLOW_DECLARED":
            secret_name = f"AI_OS_DECLARED_{cap.upper()}_SECRET"
            if not str(merged.get(secret_name) or merged.get(f"{cap}_secret".upper()) or "").strip():
                violations.append(f"{cap} requires declared workload secret for ALLOW_DECLARED")

    if violations:
        raise TaskError("START FAIL CLOSED: capability request denied — " + "; ".join(violations))

    return {
        "execution_mode": execution_mode,
        "seed_origin": seed_origin,
        "capability_profile": capability_profile,
        "matrix_key": _matrix_key(execution_mode, seed_origin, capability_profile),
        "effective": effective,
        "requested_via_env": requested,
    }


def assert_mutate_denies_gmail_send(
    *,
    execution_mode: str,
    seed_origin: str,
    capability_profile: str,
    declared_env: dict[str, str],
) -> None:
    """Explicit guard for test 4: MUTATE + production Gmail send always FAIL."""
    if execution_mode != "MUTATE":
        return
    caps = compile_effective_capabilities(
        execution_mode=execution_mode,
        seed_origin=seed_origin,
        capability_profile=capability_profile,
        declared_env=declared_env,
        declared_secrets={},
    )
    if caps["effective"].get("gmail_send") != "DENY":
        raise TaskError("MUTATE mode must DENY gmail_send")
