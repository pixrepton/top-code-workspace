from __future__ import annotations

import os
from pathlib import Path


ENV_FILE_OVERRIDE_VAR = "GMAIL_AGENT_ENV_FILE"
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_LOCAL_VPS_ENV = WORKSPACE_ROOT / "gmail-agent" / ".env.local-vps"


def ensure_gmail_agent_env_file() -> Path | None:
    """Prefer the canonical local-vps env for host-side scripts unless an override exists."""
    current = str(os.environ.get(ENV_FILE_OVERRIDE_VAR) or "").strip()
    if current:
        return Path(current)
    if CANONICAL_LOCAL_VPS_ENV.is_file():
        os.environ[ENV_FILE_OVERRIDE_VAR] = str(CANONICAL_LOCAL_VPS_ENV)
        return CANONICAL_LOCAL_VPS_ENV
    return None
