"""Isolated Postgres database + principal provisioning. Permissions first, guards second."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

from ai_os_execution import SEED_ORIGINS
from ai_os_execution.stores import parse_dsn
from ai_os_task_errors import TaskError
from ai_os_task_paths import utc_now

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(value: str) -> str:
    if not _IDENT.fullmatch(value):
        raise TaskError(f"unsafe SQL identifier: {value}")
    return value


def admin_url_from_env(env: dict[str, str] | None = None) -> str:
    env = env or dict(os.environ)
    for key in (
        "AI_OS_EXECUTION_ADMIN_DATABASE_URL",
        "MAILBOX_MEMORY_ADMIN_DATABASE_URL",
    ):
        value = (env.get(key) or "").strip()
        if value:
            return value
    return ""


def database_name_for(execution_id: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", execution_id.lower())[-24:]
    return _ident(f"aios_{compact}")


def principal_for(execution_id: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", execution_id.lower())[-20:]
    return _ident(f"aios_{compact}_rw")


def readonly_principal_for(execution_id: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", execution_id.lower())[-20:]
    return _ident(f"aios_{compact}_ro")


def _psql(admin_url: str, sql: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["psql", admin_url, "-v", "ON_ERROR_STOP=1", "-c", sql],
        text=True,
        capture_output=True,
    )


def _docker_admin_user() -> str:
    return os.environ.get("AI_OS_EXECUTION_DB_ADMIN_USER", "").strip() or "postgres"


def _docker_psql(container: str, sql: str, user: str = "") -> subprocess.CompletedProcess[str]:
    admin = user or _docker_admin_user()
    return subprocess.run(
        ["docker", "exec", "-i", container, "psql", "-U", admin, "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql],
        text=True,
        capture_output=True,
    )


def run_admin_sql(sql: str, *, admin_url: str = "", docker_container: str = "") -> str:
    if admin_url:
        proc = _psql(admin_url, sql)
    elif docker_container:
        proc = _docker_psql(docker_container, sql)
    else:
        raise TaskError("no execution-plane DB admin channel (AI_OS_EXECUTION_ADMIN_DATABASE_URL or docker container)")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise TaskError(f"admin SQL failed: {detail}")
    return (proc.stdout or "").strip()


def render_provision_sql(
    *,
    database_name: str,
    principal: str,
    password: str,
    canonical_database: str = "mailbox_memory",
    seed_origin: str = "EMPTY",
) -> str:
    db = _ident(database_name)
    role = _ident(principal)
    canonical = _ident(canonical_database)
    if seed_origin not in SEED_ORIGINS:
        raise TaskError(f"invalid seed_origin: {seed_origin}")
    escaped = password.replace("'", "''")
    return "\n".join(
        [
            f"DO $$ BEGIN CREATE ROLE {role} LOGIN PASSWORD '{escaped}'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;",
            f"ALTER ROLE {role} WITH LOGIN PASSWORD '{escaped}' NOSUPERUSER NOCREATEDB NOCREATEROLE;",
            f"SELECT 'ok' FROM pg_database WHERE datname = '{db}';",
            f"REVOKE ALL ON DATABASE {canonical} FROM {role};",
            f"REVOKE CONNECT ON DATABASE {canonical} FROM {role};",
        ]
    )


def create_database_if_missing(*, admin_url: str = "", docker_container: str = "", database_name: str, principal: str) -> None:
    db = _ident(database_name)
    role = _ident(principal)
    existing = run_admin_sql(
        f"SELECT 1 FROM pg_database WHERE datname = '{db}';",
        admin_url=admin_url,
        docker_container=docker_container,
    )
    if "1" not in existing:
        run_admin_sql(f"CREATE DATABASE {db} OWNER {role};", admin_url=admin_url, docker_container=docker_container)
    run_admin_sql(f"GRANT ALL PRIVILEGES ON DATABASE {db} TO {role};", admin_url=admin_url, docker_container=docker_container)
    run_admin_sql(f"REVOKE CONNECT ON DATABASE {db} FROM PUBLIC;", admin_url=admin_url, docker_container=docker_container)
    run_admin_sql(f"GRANT CONNECT ON DATABASE {db} TO {role};", admin_url=admin_url, docker_container=docker_container)


def provision_isolated_database(
    *,
    execution_id: str,
    execution_mode: str,
    seed_origin: str = "EMPTY",
    seed_identity: str = "",
    canonical_database: str = "mailbox_memory",
    admin_url: str = "",
    docker_container: str = "",
    host_side_host: str = "127.0.0.1",
    container_side_host: str = "mailbox-memory-db",
    port: str = "54129",
) -> dict[str, Any]:
    if seed_origin not in SEED_ORIGINS:
        raise TaskError(f"invalid seed_origin: {seed_origin}")
    if execution_mode == "BENCHMARK" and seed_origin not in {"FIXTURE", "HISTORICAL_REPLAY"}:
        raise TaskError("BENCHMARK seed_origin must be FIXTURE or HISTORICAL_REPLAY, not a live mailbox snapshot")
    database_name = database_name_for(execution_id)
    principal = principal_for(execution_id)
    password = secrets.token_urlsafe(24)
    sql = render_provision_sql(
        database_name=database_name,
        principal=principal,
        password=password,
        canonical_database=canonical_database,
        seed_origin=seed_origin,
    )
    # CREATE ROLE must run before CREATE DATABASE OWNER
    for statement in sql.split("\n"):
        if statement.startswith("SELECT "):
            continue
        run_admin_sql(statement, admin_url=admin_url, docker_container=docker_container)
    create_database_if_missing(
        admin_url=admin_url,
        docker_container=docker_container,
        database_name=database_name,
        principal=principal,
    )
    run_admin_sql(
        f"REVOKE ALL ON DATABASE {_ident(canonical_database)} FROM {principal}; "
        f"REVOKE CONNECT ON DATABASE {_ident(canonical_database)} FROM {principal};",
        admin_url=admin_url,
        docker_container=docker_container,
    )
    harden_canonical_write_denial(
        principal=principal,
        canonical_database=canonical_database,
        admin_url=admin_url,
        docker_container=docker_container,
    )
    seed_identity = seed_identity or f"{seed_origin}:{database_name}"
    seed_hash = hashlib.sha256(f"{seed_origin}:{database_name}:{utc_now()}".encode()).hexdigest()
    user = quote(principal, safe="")
    pw = quote(password, safe="")
    host_dsn = f"postgresql://{user}:{pw}@{host_side_host}:{port}/{database_name}"
    container_dsn = f"postgresql://{user}:{pw}@{container_side_host}:5432/{database_name}"
    return {
        "isolation_mode": "SHARED_SERVER_SEPARATE_DB_PRINCIPAL",
        "database_name": database_name,
        "database_host": {"host": host_side_host, "container": container_side_host},
        "principal": principal,
        "password": password,
        "seed_identity": seed_identity,
        "seed_hash": seed_hash,
        "seed_origin": seed_origin,
        "created_at": utc_now(),
        "host_dsn": host_dsn,
        "container_dsn": container_dsn,
        "canonical_database": canonical_database,
    }


def probe_live_write_denied(
    *,
    task_dsn: str,
    canonical_database: str = "mailbox_memory",
    canonical_host: str = "",
    canonical_port: str = "",
) -> dict[str, Any]:
    """Attempt INSERT into canonical mailbox using task credentials. Must be rejected."""
    parsed = urlparse(task_dsn)
    host = canonical_host or parsed.hostname or ""
    port = canonical_port or str(parsed.port or 5432)
    user = parsed.username or ""
    password = parsed.password or ""
    probe_dsn = f"postgresql://{quote(user, safe='')}:{quote(password or '', safe='')}@{host}:{port}/{canonical_database}"
    sql = "INSERT INTO mailbox_memory_cases (id) VALUES ('aios-exec-plane-probe') ON CONFLICT DO NOTHING;"
    proc = subprocess.run(
        ["psql", probe_dsn, "-v", "ON_ERROR_STOP=1", "-c", sql],
        text=True,
        capture_output=True,
    )
    denied = proc.returncode != 0
    detail = (proc.stderr or proc.stdout or "").strip()
    return {
        "attempted": True,
        "canonical_database": canonical_database,
        "denied": denied,
        "exit_code": proc.returncode,
        "detail": detail[:500],
        "verdict": "PASS" if denied else "FAIL",
    }


def harden_canonical_write_denial(
    *,
    principal: str,
    canonical_database: str = "mailbox_memory",
    admin_url: str = "",
    docker_container: str = "",
) -> None:
    """Second-line grants: task principal must not write canonical tables.

    Do not REVOKE CONNECT FROM PUBLIC on a shared server — that would break
    live mailbox clients. Table/schema privileges are the write barrier.
    """
    role = _ident(principal)
    canonical = _ident(canonical_database)
    statements = [
        f"REVOKE ALL ON DATABASE {canonical} FROM {role};",
        f"REVOKE CONNECT ON DATABASE {canonical} FROM {role};",
    ]
    for statement in statements:
        run_admin_sql(statement, admin_url=admin_url, docker_container=docker_container)
    # Schema/table rights must be revoked on the canonical database itself.
    if docker_container:
        proc = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                docker_container,
                "psql",
                "-U",
                os.environ.get("AI_OS_EXECUTION_DB_ADMIN_USER", "").strip() or "postgres",
                "-d",
                canonical,
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                f"REVOKE ALL ON SCHEMA public FROM {role}; "
                f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}; "
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {role};",
            ],
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise TaskError((proc.stderr or proc.stdout or "canonical revoke failed").strip())
        return
    if not admin_url:
        raise TaskError("canonical write-denial harden requires admin_url or docker_container")
    parsed = urlparse(admin_url)
    canonical_url = urlunparse(parsed._replace(path=f"/{canonical}"))
    proc = _psql(
        canonical_url,
        f"REVOKE ALL ON SCHEMA public FROM {role}; "
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}; "
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM {role};",
    )
    if proc.returncode != 0:
        raise TaskError((proc.stderr or proc.stdout or "canonical revoke failed").strip())


def drop_isolated_database(
    *,
    database_name: str,
    principal: str,
    admin_url: str = "",
    docker_container: str = "",
) -> None:
    db = _ident(database_name)
    role = _ident(principal)
    run_admin_sql(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db}' AND pid <> pg_backend_pid();",
        admin_url=admin_url,
        docker_container=docker_container,
    )
    run_admin_sql(f"DROP DATABASE IF EXISTS {db};", admin_url=admin_url, docker_container=docker_container)
    run_admin_sql(f"DROP ROLE IF EXISTS {role};", admin_url=admin_url, docker_container=docker_container)
