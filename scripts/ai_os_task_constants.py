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

WORKSPACE = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = 3

LEGACY_SCHEMA_VERSIONS = {1, 2}

ALLOWED_STATUSES = {
    "INITIALIZED",
    "IN_PROGRESS",
    "BLOCKED",
    "READY_TO_CLOSE",
    "CLOSED",
    "ABORTED_WITH_EVIDENCE",
}

ALLOWED_CLASSES = {"SMALL", "MEDIUM", "CRITICAL"}

ALLOWED_PUBLICATION_MODES = {"LOCAL_ONLY", "PUBLISH", "SHIP"}

ACTIVE_TASK_STATUSES = {"INITIALIZED", "IN_PROGRESS", "BLOCKED", "READY_TO_CLOSE"}

PROTECTED_BRANCH_NAMES = {"main", "master", "trunk"}

PASSING_GATE_VERDICTS = {"PASS", "DEDUPLICATED"}

REGISTRY_LOCK_NAME = "registry.lock"

REGISTRY_LOCK_STALE_SECONDS = 30

REGISTRY_LOCK_TIMEOUT_SECONDS = 10

REPO_COMMIT_LOCK_TIMEOUT_SECONDS = 10

TASK_CHECKPOINT_LOCK_TIMEOUT_SECONDS = 10

TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

_HELD_FILE_LOCKS: set[str] = set()

FROZEN_PATHS = {
    "knowledge": {
        "system-atlas/workflows/WORKFLOW_REGISTRY.yaml",
        "system-atlas/workflows/WORKFLOW_EVIDENCE.jsonl",
    }
}

SECRET_PATH_PATTERNS = (
    re.compile(r"(^|/)(?:\.env(?:\..+)?|credentials(?:\..+)?|id_(?:rsa|dsa|ecdsa|ed25519)|[^/]+\.(?:pem|p12|pfx|key))$", re.I),
)

SECRET_CONTENT_PATTERNS = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GitHub token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("OpenAI-style secret", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Anthropic secret", re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
)

FORBIDDEN_COMMAND_MARKERS = (
    "git push",
    "git reset",
    "git clean",
    "ssh ",
    "scp ",
    "deploy",
    "kubectl ",
)

# Nested product repos are independent Git units; never commit their paths via workspace root.
NESTED_PRODUCT_REPO_DIRS = frozenset(
    {
        "knowledge",
        "gmail-agent",
        "kalk-top",
        "daszek",
        "rag-chat-asystent",
        "rag-widget",
        "cieplo-orchestrator",
        "top-instal-generator",
        "fast-kalk",
    }
)
