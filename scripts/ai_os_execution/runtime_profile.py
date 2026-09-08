"""Runtime profile + container image provenance (V1.1 F3)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ai_os_task_errors import TaskError
from ai_os_task_paths import utc_now

RUNTIME_PROFILES = frozenset({"host", "container"})


def uses_container(profile: str) -> bool:
    return str(profile or "host").strip() == "container"


def context_hash(worktree: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(worktree.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(worktree).as_posix().encode()
        digest.update(rel)
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_image_record(
    *,
    repo: str,
    digest: str,
    source_sha: str,
    worktree_path: str | Path,
    worktree_clean_at_build: bool = True,
) -> dict[str, Any]:
    worktree = Path(worktree_path)
    return {
        "repo": repo,
        "digest": digest.strip(),
        "source_sha": source_sha.strip(),
        "context_hash": context_hash(worktree) if worktree.exists() else "",
        "build_context": "worktree",
        "worktree_path": str(worktree),
        "worktree_clean_at_build": bool(worktree_clean_at_build),
        "recorded_at": utc_now(),
    }


def record_image_digest(
    bundle: dict[str, Any],
    *,
    repo: str,
    digest: str,
    source_sha: str,
    worktree_clean_at_build: bool = True,
) -> dict[str, Any]:
    entry = bundle.get("repos", {}).get(repo) or {}
    worktree_path = str(entry.get("worktree_path") or "")
    current_sha = str(entry.get("current_sha") or source_sha)
    record = build_image_record(
        repo=repo,
        digest=digest,
        source_sha=source_sha or current_sha,
        worktree_path=worktree_path,
        worktree_clean_at_build=worktree_clean_at_build,
    )
    runtime = bundle.setdefault("runtime", {})
    digests = runtime.setdefault("image_digests", {})
    digests[repo] = record
    return record


def require_container_image_provenance(bundle: dict[str, Any]) -> None:
    runtime = bundle.get("runtime") or {}
    profile = str(runtime.get("profile") or "host")
    if not uses_container(profile):
        return
    digests = runtime.get("image_digests") or {}
    if not digests:
        raise TaskError(
            "container runtime profile requires image_digests with digest, source_sha, "
            "context_hash, build_context=worktree, worktree_clean_at_build"
        )
    for repo, entry in digests.items():
        if isinstance(entry, str):
            entry = {"digest": entry}
        missing = [
            field
            for field in ("digest", "source_sha", "context_hash", "build_context")
            if not str(entry.get(field) or "").strip()
        ]
        if missing or entry.get("build_context") != "worktree":
            raise TaskError(f"incomplete image provenance for {repo}: missing {missing or ['build_context']}")
        if "worktree_clean_at_build" not in entry:
            raise TaskError(f"incomplete image provenance for {repo}: missing worktree_clean_at_build")
