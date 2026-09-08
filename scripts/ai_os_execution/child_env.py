"""Synthesized workload child environment + hermetic execution profile (V1.1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ai_os_execution.bundle import execution_dir, load_bundle, load_bundle_for_task
from ai_os_execution.stores import load_catalog
from ai_os_task_errors import TaskError

# Keys always copied from host when present (OS/runtime plumbing only).
_SAFE_BASE_KEYS = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramData",
        "LOCALAPPDATA",
        "APPDATA",
        "USERDOMAIN",
        "USERNAME",
        "USERDOMAIN_ROAMINGPROFILE",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER",
        "OS",
    }
)

# Never inherited from host into workload children.
_BLOCKED_HOST_PREFIXES = (
    "MAILBOX_",
    "GMAIL_",
    "GOOGLE_",
    "DATABASE_",
    "GRAPHSTORE_",
    "PGVECTOR_",
    "NEO4J_",
    "OPENAI_",
    "ANTHROPIC_",
    "AWS_",
    "AZURE_",
    "CHROMA_",
    "QDRANT_",
    "MINIO_",
    "TEMPORAL_",
    "RAG_",
    "AI_OS_EXECUTION_ADMIN_",
    "MAILBOX_MEMORY_ADMIN_",
)

_BLOCKED_HOST_KEYS = frozenset(
    {
        "DATABASE_URL",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "SSH_AUTH_SOCK",
        "SSH_AGENT_PID",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "DOCKER_HOST",
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "NETRC",
        "AI_OS_TASK_ID",
    }
)

_CONTROL_PLANE_ENV_KEYS = frozenset(
    {
        "AI_OS_EXECUTION_ADMIN_DATABASE_URL",
        "MAILBOX_MEMORY_ADMIN_DATABASE_URL",
        "AI_OS_EXECUTION_DB_CONTAINER",
        "AI_OS_EXECUTION_DB_ADMIN_USER",
    }
)

_SECRET_FILE_NAME = "task.env.secret"
_PUBLIC_ENV_FILE = "HOST_ENV.json"
_HERMETIC_ROOT_NAME = "profile"


def store_env_keys() -> frozenset[str]:
    keys: set[str] = set()
    try:
        catalog = load_catalog()
    except TaskError:
        return frozenset(keys)
    for store in catalog.get("stores") or []:
        env_key = str(store.get("env") or "").strip()
        if env_key:
            keys.add(env_key)
    keys.add("MAILBOX_MEMORY_CANONICAL_DATABASE_URL")
    keys.add("MAILBOX_MEMORY_TEST_DATABASE_URL")
    return frozenset(keys)


def _is_blocked_host_key(key: str) -> bool:
    if key in _BLOCKED_HOST_KEYS or key in _CONTROL_PLANE_ENV_KEYS:
        return True
    if key in store_env_keys():
        return True
    upper = key.upper()
    return any(upper.startswith(prefix) for prefix in _BLOCKED_HOST_PREFIXES)


def safe_base_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in _SAFE_BASE_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            env[key] = value
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONLEGACYWINDOWSSTDIO", "0")
    env["PYTHONNOUSERSITE"] = "1"
    return env


def load_hermetic_profile(execution_root: Path) -> dict[str, str]:
    """Return hermetic profile env; create dirs if missing."""
    profile = execution_root / "scratch" / _HERMETIC_ROOT_NAME
    home = profile / "home"
    if not home.exists():
        return provision_hermetic_profile(execution_root)
    config = profile / "config"
    cache = profile / "cache"
    tmp = profile / "tmp"
    docker_cfg = profile / "docker"
    secrets = profile / "secrets"
    gitconfig = config / ".gitconfig"
    return {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(config),
        "XDG_CACHE_HOME": str(cache),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "DOCKER_CONFIG": str(docker_cfg),
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_SYSTEM": os.devnull,
        "AI_OS_HERMETIC_SECRETS_DIR": str(secrets),
    }


def provision_hermetic_profile(execution_root: Path) -> dict[str, str]:
    """Create isolated HOME/profile dirs; return env vars pointing at them."""
    profile = execution_root / "scratch" / _HERMETIC_ROOT_NAME
    home = profile / "home"
    config = profile / "config"
    cache = profile / "cache"
    tmp = profile / "tmp"
    docker_cfg = profile / "docker"
    secrets = profile / "secrets"
    for path in (home, config, cache, tmp, docker_cfg, secrets):
        path.mkdir(parents=True, exist_ok=True)

    gitconfig = config / ".gitconfig"
    if not gitconfig.exists():
        gitconfig.write_text(
            "[credential]\n\thelper =\n",
            encoding="utf-8",
        )

    return {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(config),
        "XDG_CACHE_HOME": str(cache),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "DOCKER_CONFIG": str(docker_cfg),
        "GIT_CONFIG_GLOBAL": str(gitconfig),
        "GIT_CONFIG_SYSTEM": os.devnull,
        "AI_OS_HERMETIC_SECRETS_DIR": str(secrets),
    }


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_workload_secrets(execution_id: str) -> dict[str, str]:
    path = execution_dir(execution_id) / _SECRET_FILE_NAME
    secrets = parse_env_file(path)
    for key in _CONTROL_PLANE_ENV_KEYS:
        secrets.pop(key, None)
    return secrets


def load_declared_public_env(execution_id: str) -> dict[str, str]:
    path = execution_dir(execution_id) / _PUBLIC_ENV_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TaskError(f"invalid HOST_ENV.json: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TaskError(f"HOST_ENV.json must be an object: {path}")
    return {str(k): str(v) for k, v in data.items() if v is not None}


def write_public_env_file(execution_id: str, declared: dict[str, str]) -> Path:
    path = execution_dir(execution_id) / _PUBLIC_ENV_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    public = {k: v for k, v in declared.items() if "://" not in str(v) and "PASSWORD" not in k.upper()}
    path.write_text(json.dumps(public, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def revoke_workload_secrets(execution_id: str) -> list[str]:
    """Delete workload secret files; return paths removed."""
    root = execution_dir(execution_id)
    removed: list[str] = []
    secret_path = root / _SECRET_FILE_NAME
    if secret_path.exists():
        secret_path.unlink()
        removed.append(str(secret_path))
    hermetic_secrets = root / "scratch" / _HERMETIC_ROOT_NAME / "secrets"
    if hermetic_secrets.exists():
        for item in hermetic_secrets.iterdir():
            if item.is_file():
                item.unlink()
                removed.append(str(item))
    return removed


def write_workload_secrets_file(execution_id: str, secrets: dict[str, str]) -> Path:
    path = execution_dir(execution_id) / _SECRET_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    for key in _CONTROL_PLANE_ENV_KEYS:
        secrets.pop(key, None)
    lines = [f"{key}={value}" for key, value in sorted(secrets.items()) if value]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


def merge_declared_env(
    *,
    declared_public: dict[str, str],
    workload_secrets: dict[str, str],
    hermetic: dict[str, str],
    extra_declared: dict[str, str] | None = None,
) -> dict[str, str]:
    merged: dict[str, str] = {}
    merged.update(declared_public)
    if extra_declared:
        for key, value in extra_declared.items():
            if _is_blocked_host_key(key):
                continue
            merged[key] = value
    merged.update(workload_secrets)
    merged.update(hermetic)
    return merged


def build_effective_child_env(
    bundle: dict[str, Any],
    *,
    cwd: str | Path | None = None,
    extra_declared: dict[str, str] | None = None,
    include_execution_ids: bool = True,
) -> dict[str, str]:
    execution_id = str(bundle["execution_id"])
    env = safe_base_env()
    hermetic = load_hermetic_profile(execution_dir(execution_id))
    declared = load_declared_public_env(execution_id)
    secrets = load_workload_secrets(execution_id)
    merged = merge_declared_env(
        declared_public=declared,
        workload_secrets=secrets,
        hermetic=hermetic,
        extra_declared=extra_declared,
    )
    env.update(merged)
    if include_execution_ids:
        env["AI_OS_EXECUTION_ID"] = execution_id
        env["AI_OS_TASK_ID"] = str(bundle.get("task_id") or "")
        env["AI_OS_EXECUTION_MODE"] = str(bundle.get("execution_mode") or "TEST")
    env.pop("AI_OS_TASK_ID", None)  # gate children must not inherit parent task routing
    if cwd is not None:
        env["PWD"] = str(cwd)
    _assert_no_host_poison(env)
    return env


def build_effective_child_env_for_task(
    task_id: str,
    *,
    cwd: str | Path | None = None,
    extra_declared: dict[str, str] | None = None,
) -> dict[str, str]:
    bundle = load_bundle_for_task(task_id)
    if not bundle:
        raise TaskError(f"no execution bundle for task {task_id}")
    return build_effective_child_env(bundle, cwd=cwd, extra_declared=extra_declared)


def minimal_legacy_gate_env() -> dict[str, str]:
    """Legacy checkpoint gates: small safe base only, never full host copy."""
    env = safe_base_env()
    for key in ("HOME", "USERPROFILE", "TMP", "TEMP"):
        value = os.environ.get(key, "").strip()
        if value:
            env[key] = value
    env.pop("AI_OS_TASK_ID", None)
    return env


def gate_subprocess_env(
    *,
    task_id: str,
    execution_id: str,
    cwd: str | Path,
    repo: str = "",
    operation_kind: str = "GATE",
) -> dict[str, str]:
    if execution_id:
        from ai_os_execution.execution_context import compile_execution_context

        if not repo:
            raise TaskError("gate_subprocess_env requires repo when execution_id is set")
        context = compile_execution_context(
            execution_id=execution_id,
            repo=repo,
            operation_kind=operation_kind,
        )
        return dict(context["synthesized_env"])
    return minimal_legacy_gate_env()


def _assert_no_host_poison(env: dict[str, str]) -> None:
    for key in env:
        if key in _CONTROL_PLANE_ENV_KEYS:
            raise TaskError(f"control-plane credential leaked into workload env: {key}")
    for key in env:
        if _is_blocked_host_key(key) and key not in store_env_keys():
            raise TaskError(f"blocked host env key leaked into workload: {key}")


def control_plane_fingerprint(*, admin_url: str = "", docker_container: str = "", admin_user: str = "") -> str:
    import hashlib

    parts = [
        f"admin_url={admin_url}",
        f"container={docker_container}",
        f"user={admin_user}",
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
