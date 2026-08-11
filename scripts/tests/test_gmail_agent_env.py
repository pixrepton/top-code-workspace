from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import _gmail_agent_env as gmail_agent_env  # noqa: E402


def test_preserves_explicit_override(monkeypatch, tmp_path):
    override = tmp_path / "override.env"
    override.write_text("X=1\n", encoding="utf-8")
    monkeypatch.setenv(gmail_agent_env.ENV_FILE_OVERRIDE_VAR, str(override))
    assert gmail_agent_env.ensure_gmail_agent_env_file() == override


def test_sets_canonical_local_vps_when_missing(monkeypatch, tmp_path):
    canonical = tmp_path / ".env.local-vps"
    canonical.write_text("X=1\n", encoding="utf-8")
    monkeypatch.delenv(gmail_agent_env.ENV_FILE_OVERRIDE_VAR, raising=False)
    monkeypatch.setattr(gmail_agent_env, "CANONICAL_LOCAL_VPS_ENV", canonical)
    resolved = gmail_agent_env.ensure_gmail_agent_env_file()
    assert resolved == canonical
    assert os.environ[gmail_agent_env.ENV_FILE_OVERRIDE_VAR] == str(canonical)


def test_noop_when_canonical_file_missing(monkeypatch, tmp_path):
    missing = tmp_path / ".env.local-vps"
    monkeypatch.delenv(gmail_agent_env.ENV_FILE_OVERRIDE_VAR, raising=False)
    monkeypatch.setattr(gmail_agent_env, "CANONICAL_LOCAL_VPS_ENV", missing)
    assert gmail_agent_env.ensure_gmail_agent_env_file() is None
    assert gmail_agent_env.ENV_FILE_OVERRIDE_VAR not in os.environ
