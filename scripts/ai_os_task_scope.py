from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_os_task_errors import TaskError

def normalize_scope_path(path: str) -> str:
    raw = path.replace("\\", "/").strip()
    if raw in {"", ".", "*"}:
        return "*"
    parts: list[str] = []
    for segment in raw.split("/"):
        if segment in {"", "."}:
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts) if parts else "*"

def scope_entries_overlap(left: dict[str, str], right: dict[str, str]) -> bool:
    if left["repo"] != right["repo"]:
        return False
    left_path = normalize_scope_path(left["path"])
    right_path = normalize_scope_path(right["path"])
    if left_path == "*" or right_path == "*":
        return True
    if left_path == right_path:
        return True
    return left_path.startswith(right_path + "/") or right_path.startswith(left_path + "/")

def scopes_conflict(left: list[dict[str, str]], right: list[dict[str, str]]) -> list[tuple[dict[str, str], dict[str, str]]]:
    pairs: list[tuple[dict[str, str], dict[str, str]]] = []
    for left_item in left:
        for right_item in right:
            if scope_entries_overlap(left_item, right_item):
                pairs.append((left_item, right_item))
    return pairs

def normalize_rel(path: str) -> str:
    return path.replace("\\", "/").strip("/")

def parse_scope(values: list[str]) -> list[dict[str, str]]:
    scope: list[dict[str, str]] = []
    for raw in values:
        if ":" not in raw:
            raise TaskError(f"scope must use repo:path form: {raw}")
        repo, rel = raw.split(":", 1)
        repo = repo.strip()
        rel = normalize_rel(rel)
        if not repo or not rel:
            raise TaskError(f"invalid scope: {raw}")
        scope.append({"repo": repo, "path": rel})
    return scope

def scopes_for_repo(scope: list[dict[str, str]], repo: str) -> list[str]:
    paths = [item["path"] for item in scope if item["repo"] == repo]
    return paths or ["."]
