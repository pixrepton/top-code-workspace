"""Regression and integration tests for per-client MCP configuration."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "dev-tooling"))

from mcp_smoke_probe import smoke_stdio  # noqa: E402

CLAUDE_MCP = ROOT / ".mcp.json"
CURSOR_MCP = ROOT / ".cursor" / "mcp.json"
CURSOR_PERMISSIONS = ROOT / ".cursor" / "permissions.json"
CODEX_CONFIG = Path.home() / ".codex" / "config.toml"

CBM_PIN = "codebase-memory-mcp==0.9.0"
PLAYWRIGHT_PIN = "@playwright/mcp@0.0.78"
CODESCENE_PIN = "@codescene/codehealth-mcp@1.4.1"

REQUIRED_SERVERS = {"codebase-memory", "gitnexus", "playwright"}
SMOKE_CONFIRMED_OPTIONAL = {"codescene"}
FORBIDDEN_SERVERS = {"openmemory"}
# NOT_PROVEN/DISABLED: smoke probe did not confirm MCP handshake; not marked BROKEN.
DISABLED_NOT_PROVEN_SERVERS = {"serena"}

SERENA_SMOKE_OPT_IN = os.environ.get("RUN_SERENA_SMOKE") == "1"
SERENA_SMOKE_SKIP_REASON = (
    "Serena smoke is opt-in (RUN_SERENA_SMOKE=1); status NOT_PROVEN/DISABLED"
)

CLAUDE_SETTINGS_LOCAL = ROOT / ".claude" / "settings.local.json"

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    re.compile(r'"password"\s*:\s*"[^"]+"', re.IGNORECASE),
    re.compile(r'"api[_-]?key"\s*:\s*"[^"]+"', re.IGNORECASE),
)

LOCAL_ONLY_PATH_MARKERS = (
    "C:/Users/",
    "C:\\Users\\",
    "C:/ai-os-",
    "C:\\ai-os-",
    "${workspaceFolder}",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(flatten_strings(item))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(flatten_strings(item))
        return out
    return []


def server_names(config: dict) -> set[str]:
    return set(config.get("mcpServers", {}))


def args_blob(server: dict) -> str:
    return json.dumps(server.get("args", []))


@pytest.fixture(scope="module")
def claude_config() -> dict:
    return load_json(CLAUDE_MCP)


@pytest.fixture(scope="module")
def cursor_config() -> dict:
    return load_json(CURSOR_MCP)


@pytest.fixture(scope="module")
def cursor_permissions() -> dict:
    return load_json(CURSOR_PERMISSIONS)


class TestMcpJsonSyntax:
    def test_claude_mcp_json_parses(self, claude_config):
        assert "mcpServers" in claude_config

    def test_cursor_mcp_json_parses(self, cursor_config):
        assert "mcpServers" in cursor_config

    def test_cursor_permissions_json_parses(self, cursor_permissions):
        assert "mcpAllowlist" in cursor_permissions


class TestRequiredCapabilities:
    @pytest.mark.parametrize("config_name", ["claude", "cursor"])
    def test_required_servers_present(self, config_name, claude_config, cursor_config):
        config = claude_config if config_name == "claude" else cursor_config
        names = server_names(config)
        missing = REQUIRED_SERVERS - names
        assert not missing, f"{config_name} missing required servers: {sorted(missing)}"

    def test_claude_has_codescene_after_smoke(self, claude_config):
        assert "codescene" in server_names(claude_config)

    def test_cursor_has_codescene_after_smoke(self, cursor_config):
        assert "codescene" in server_names(cursor_config)


class TestForbiddenAndPins:
    def test_no_openmemory(self, claude_config, cursor_config):
        assert FORBIDDEN_SERVERS.isdisjoint(server_names(claude_config))
        assert FORBIDDEN_SERVERS.isdisjoint(server_names(cursor_config))

    @pytest.mark.parametrize("config_name", ["claude", "cursor"])
    def test_disabled_serena_not_in_active_configs(self, config_name, claude_config, cursor_config):
        config = claude_config if config_name == "claude" else cursor_config
        present = DISABLED_NOT_PROVEN_SERVERS & server_names(config)
        assert not present, (
            f"{config_name} must not enable NOT_PROVEN/DISABLED servers: {sorted(present)}"
        )

    def test_serena_not_in_cursor_allowlist(self, cursor_permissions):
        allowlist = cursor_permissions.get("mcpAllowlist", [])
        roots = {entry.split(":", 1)[0] for entry in allowlist}
        assert "serena" not in roots

    def test_serena_not_enabled_in_claude_local_settings_when_present(self):
        if not CLAUDE_SETTINGS_LOCAL.exists():
            pytest.skip("local Claude settings not present on this machine")
        settings = load_json(CLAUDE_SETTINGS_LOCAL)
        enabled = set(settings.get("enabledMcpjsonServers", []))
        assert "serena" not in enabled

    def test_no_latest_tags(self, claude_config, cursor_config):
        for label, config in (("claude", claude_config), ("cursor", cursor_config)):
            blob = json.dumps(config)
            assert "@latest" not in blob, f"{label} still uses @latest"

    def test_pinned_versions_present(self, claude_config, cursor_config):
        for config in (claude_config, cursor_config):
            cbm = config["mcpServers"]["codebase-memory"]
            assert CBM_PIN in args_blob(cbm)
            pw = config["mcpServers"]["playwright"]
            assert PLAYWRIGHT_PIN in args_blob(pw)
            cs = config["mcpServers"]["codescene"]
            assert CODESCENE_PIN in args_blob(cs)


class TestClaudeWindowsWrapper:
    def test_playwright_uses_cmd_wrapper(self, claude_config):
        pw = claude_config["mcpServers"]["playwright"]
        assert pw["command"] == "cmd.exe"
        joined = " ".join(pw["args"])
        assert "npx.cmd" in joined
        assert PLAYWRIGHT_PIN in joined

    def test_codescene_uses_cmd_wrapper(self, claude_config):
        cs = claude_config["mcpServers"]["codescene"]
        assert cs["command"] == "cmd.exe"
        joined = " ".join(cs["args"])
        assert "npx.cmd" in joined
        assert CODESCENE_PIN in joined

    def test_gitnexus_command(self, claude_config):
        gn = claude_config["mcpServers"]["gitnexus"]
        assert gn["command"] == "gitnexus"
        assert gn["args"] == ["mcp"]


class TestCursorNativeShape:
    def test_playwright_uses_native_npx(self, cursor_config):
        pw = cursor_config["mcpServers"]["playwright"]
        assert pw["command"] == "npx"
        assert PLAYWRIGHT_PIN in args_blob(pw)
        assert "cmd.exe" not in args_blob(pw)

    def test_codebase_memory_env(self, cursor_config):
        env = cursor_config["mcpServers"]["codebase-memory"]["env"]
        assert "CBM_ALLOWED_ROOT" in env
        assert "CBM_CACHE_DIR" in env


class TestCursorAllowlist:
    def test_allowlist_covers_configured_servers(self, cursor_config, cursor_permissions):
        configured = server_names(cursor_config)
        allowlist = cursor_permissions.get("mcpAllowlist", [])
        allowed_roots = {entry.split(":", 1)[0] for entry in allowlist}
        missing = configured - allowed_roots
        assert not missing, f"allowlist missing configured servers: {sorted(missing)}"

    def test_no_openmemory_in_allowlist(self, cursor_permissions):
        allowlist = cursor_permissions.get("mcpAllowlist", [])
        assert not any(entry.startswith("openmemory:") for entry in allowlist)


class TestSecretsAndLocalPaths:
    @pytest.mark.parametrize(
        "path",
        [CLAUDE_MCP, CURSOR_MCP, CURSOR_PERMISSIONS],
    )
    def test_no_secrets_in_committed_configs(self, path):
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(text), f"possible secret in {path.name}"

    @pytest.mark.parametrize(
        "path",
        [CLAUDE_MCP, CURSOR_MCP],
    )
    def test_machine_paths_are_local_only(self, path):
        config = load_json(path)
        strings = flatten_strings(config)
        hits = [value for value in strings if any(marker in value for marker in LOCAL_ONLY_PATH_MARKERS)]
        assert hits, f"{path.name} should document local machine paths for CBM/cache"
        assert all(any(marker in value for marker in LOCAL_ONLY_PATH_MARKERS) for value in hits)

    def test_codex_config_classified_local_only_not_in_workspace(self):
        assert CODEX_CONFIG.exists(), "local Codex config expected on developer machine"
        assert CODEX_CONFIG.is_relative_to(Path.home())
        assert not (ROOT / ".codex" / "config.toml").exists()


@pytest.mark.integration
class TestMcpSmoke:
    """Behavioral smoke: process starts, publishes tools, read-only call works."""

    CBM_ENV = {
        "CBM_ALLOWED_ROOT": "C:/Users/compg/Desktop/top-code workspace",
        "CBM_CACHE_DIR": "C:/ai-os-codebase-memory",
    }

    def test_codebase_memory_smoke(self):
        result = smoke_stdio(
            "uvx",
            ["--from", CBM_PIN, "codebase-memory-mcp"],
            env=self.CBM_ENV,
        )
        assert result["ok"]
        assert result["tool_count"] >= 1
        assert "get_graph_schema" in result["tool_names"]

    def test_gitnexus_smoke(self):
        result = smoke_stdio("gitnexus", ["mcp"])
        assert result["ok"]
        assert "list_repos" in result["tool_names"]

    def test_playwright_smoke(self):
        result = smoke_stdio(
            "npx",
            [
                "-y",
                PLAYWRIGHT_PIN,
                "--browser=firefox",
                "--allowed-hosts",
                "127.0.0.1,localhost",
            ],
        )
        assert result["ok"]
        assert "browser_navigate" in result["tool_names"]

    def test_playwright_claude_wrapper_smoke(self):
        result = smoke_stdio(
            "cmd.exe",
            [
                "/d",
                "/s",
                "/c",
                f"npx.cmd -y {PLAYWRIGHT_PIN} --browser=firefox --allowed-hosts 127.0.0.1,localhost",
            ],
        )
        assert result["ok"]

    def test_codescene_smoke(self):
        result = smoke_stdio("npx", ["-y", CODESCENE_PIN])
        assert result["ok"]
        assert "get_config" in result["tool_names"]

    @pytest.mark.skipif(not SERENA_SMOKE_OPT_IN, reason=SERENA_SMOKE_SKIP_REASON)
    def test_serena_smoke(self):
        result = smoke_stdio(
            r"C:\Users\compg\.local\bin\serena.exe",
            [
                "start-mcp-server",
                "--context",
                "ide",
                "--project",
                str(ROOT),
            ],
            timeout=120.0,
        )
        assert result["ok"]
