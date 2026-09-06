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
CONTEXT7_PIN = "@upstash/context7-mcp@3.2.5"
EXPECTED_CBM_ENV = {
    "CBM_ALLOWED_ROOT": "C:/Users/compg/Desktop/top-code workspace",
    "CBM_CACHE_DIR": "C:/ai-os-codebase-memory",
}

REQUIRED_SERVERS = {"codebase-memory", "gitnexus", "playwright"}
SMOKE_CONFIRMED_OPTIONAL = {"codescene", "context7"}
FORBIDDEN_SERVERS = {"openmemory"}
DISABLED_NOT_PROVEN_SERVERS: set[str] = set()

SERENA_SMOKE_OPT_IN = os.environ.get("RUN_SERENA_SMOKE") == "1"
SERENA_SMOKE_SKIP_REASON = (
    "Serena smoke is opt-in (RUN_SERENA_SMOKE=1); LSP init can exceed probe timeout"
)
SERENA_ARGS = [
    "start-mcp-server",
    "--context",
    "ide",
    "--project-from-cwd",
]

CLAUDE_SETTINGS_LOCAL = ROOT / ".claude" / "settings.local.json"
SOURCEBOT_COMPOSE = ROOT / "docker-compose.sourcebot-local.yml"
SOURCEBOT_CONFIG = ROOT / "sourcebot" / "config.json"

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    re.compile(r'"password"\s*:\s*"[^"]+"', re.IGNORECASE),
    re.compile(r'"api[_-]?key"\s*:\s*"[^"]+"', re.IGNORECASE),
)

MACHINE_PATH_MARKERS = (
    "C:/Users/",
    "C:\\Users\\",
    "C:/ai-os-",
    "C:\\ai-os-",
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

    def test_sourcebot_not_registered_as_free_mcp(self, claude_config, cursor_config):
        assert "sourcebot" not in server_names(claude_config)
        assert "sourcebot" not in server_names(cursor_config)


class TestForbiddenAndPins:
    def test_no_openmemory(self, claude_config, cursor_config):
        assert FORBIDDEN_SERVERS.isdisjoint(server_names(claude_config))
        assert FORBIDDEN_SERVERS.isdisjoint(server_names(cursor_config))

    @pytest.mark.parametrize("config_name", ["claude", "cursor"])
    def test_disabled_serena_not_in_active_configs(self, config_name, claude_config, cursor_config):
        if not DISABLED_NOT_PROVEN_SERVERS:
            pytest.skip("no disabled servers")
        config = claude_config if config_name == "claude" else cursor_config
        present = DISABLED_NOT_PROVEN_SERVERS & server_names(config)
        assert not present, (
            f"{config_name} must not enable NOT_PROVEN/DISABLED servers: {sorted(present)}"
        )

    def test_serena_present_in_configs(self, claude_config, cursor_config):
        assert "serena" in server_names(claude_config)
        assert "serena" in server_names(cursor_config)

    def test_context7_present_in_configs(self, claude_config, cursor_config):
        assert "context7" in server_names(claude_config)
        assert "context7" in server_names(cursor_config)

    def test_serena_in_cursor_allowlist(self, cursor_permissions):
        allowlist = cursor_permissions.get("mcpAllowlist", [])
        roots = {entry.split(":", 1)[0] for entry in allowlist}
        assert "serena" in roots

    def test_context7_in_cursor_allowlist(self, cursor_permissions):
        allowlist = cursor_permissions.get("mcpAllowlist", [])
        roots = {entry.split(":", 1)[0] for entry in allowlist}
        assert "context7" in roots

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
            assert CONTEXT7_PIN in args_blob(config["mcpServers"]["context7"])

    def test_no_tool_whitelists_or_host_locks(self, claude_config, cursor_config):
        for label, config in (("claude", claude_config), ("cursor", cursor_config)):
            blob = json.dumps(config)
            assert "CS_ENABLED_TOOLS" not in blob, f"{label} still whitelists CodeScene tools"
            assert "allowed-hosts" not in blob, f"{label} still locks Playwright hosts"
            assert "--browser=" not in blob, f"{label} still forces Playwright browser"


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

    def test_codebase_memory_has_expected_scoped_env(self, cursor_config, claude_config):
        for config in (cursor_config, claude_config):
            env = config["mcpServers"]["codebase-memory"].get("env") or {}
            assert env == EXPECTED_CBM_ENV

    def test_serena_uses_path_and_cwd_project(self, cursor_config, claude_config):
        for config in (cursor_config, claude_config):
            serena = config["mcpServers"]["serena"]
            assert serena["command"] == "serena"
            assert "--project-from-cwd" in serena["args"]
            assert not any("C:/" in arg or "C:\\" in arg for arg in serena["args"])


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
    def test_no_machine_absolute_paths_in_configs(self, path):
        config = load_json(path)
        strings = flatten_strings(config)
        allowed = set(EXPECTED_CBM_ENV.values())
        hits = [
            value
            for value in strings
            if value not in allowed and any(marker in value for marker in MACHINE_PATH_MARKERS)
        ]
        assert not hits, f"{path.name} must not hardcode machine paths: {hits}"

    def test_codex_config_classified_local_only_not_in_workspace(self):
        assert CODEX_CONFIG.exists(), "local Codex config expected on developer machine"
        assert CODEX_CONFIG.is_relative_to(Path.home())
        assert not (ROOT / ".codex" / "config.toml").exists()


class TestSourcebotLocalConfig:
    def test_sourcebot_config_parses_and_uses_local_git_urls(self):
        config = load_json(SOURCEBOT_CONFIG)
        connections = config.get("connections") or {}
        assert {"gmail-agent", "kalk-top"}.issubset(connections)
        for name, connection in connections.items():
            assert connection["type"] == "git", name
            assert connection["url"].startswith("file:///repos/top-code"), name

    def test_sourcebot_compose_is_local_read_only_and_telemetry_off(self):
        text = SOURCEBOT_COMPOSE.read_text(encoding="utf-8")
        assert "127.0.0.1:3000:3000" in text
        assert "./:/repos/top-code:ro" in text
        assert 'SOURCEBOT_TELEMETRY_DISABLED: "true"' in text
        assert "/api/mcp" not in text


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
        result = smoke_stdio("npx", ["-y", PLAYWRIGHT_PIN])
        assert result["ok"]
        assert "browser_navigate" in result["tool_names"]

    def test_playwright_claude_wrapper_smoke(self):
        result = smoke_stdio(
            "cmd.exe",
            ["/d", "/s", "/c", f"npx.cmd -y {PLAYWRIGHT_PIN}"],
        )
        assert result["ok"]

    def test_codescene_smoke(self):
        result = smoke_stdio("npx", ["-y", CODESCENE_PIN])
        assert result["ok"]
        assert "get_config" in result["tool_names"]

    def test_context7_smoke(self):
        result = smoke_stdio("npx", ["-y", CONTEXT7_PIN])
        assert result["ok"]
        assert "resolve-library-id" in result["tool_names"]

    @pytest.mark.skipif(not SERENA_SMOKE_OPT_IN, reason=SERENA_SMOKE_SKIP_REASON)
    def test_serena_smoke(self):
        result = smoke_stdio("serena", SERENA_ARGS, timeout=300.0)
        assert result["ok"]
